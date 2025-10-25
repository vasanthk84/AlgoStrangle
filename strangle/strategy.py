"""
Short Strangle trading strategy implementation
"""

import logging
from datetime import datetime, date, time as dt_time
from typing import Optional, Tuple
import pandas as pd

from .config import Config
from .models import MarketData, Trade, Direction
from .broker import BrokerInterface
from .trade_manager import TradeManager
from .notifier import NotificationManager
from .utils import Utils


class ShortStrangleStrategy:
    def __init__(self, broker: BrokerInterface, trade_manager: TradeManager, notifier: NotificationManager):
        self.broker = broker
        self.trade_manager = trade_manager
        self.notifier = notifier
        self.market_data = MarketData()
        self.vix_history = []
        self.entry_allowed_today = True
        # STATE TRACKING FOR SMART LOGGING
        self.last_entry_decision = None
        self.last_entry_reason = None
        self.entry_checks_today = 0

    def calculate_iv_percentile(self) -> float:
        if len(self.vix_history) < 30:
            self.vix_history.append(self.market_data.india_vix)
            return 50.0
        self.vix_history.append(self.market_data.india_vix)
        if len(self.vix_history) > 252:
            self.vix_history.pop(0)
        current_vix = self.market_data.india_vix
        below_current = sum(1 for v in self.vix_history if v < current_vix)
        percentile = (below_current / len(self.vix_history)) * 100
        return percentile

    def should_enter_trade(self) -> Tuple[bool, str]:
        vix = self.market_data.india_vix
        iv_percentile = self.calculate_iv_percentile()

        if vix < Config.VIX_LOW_THRESHOLD:
            reason = f"VIX too low ({vix:.2f} < {Config.VIX_LOW_THRESHOLD})"
            return False, reason
        if vix > Config.VIX_HIGH_THRESHOLD * 1.5:
            reason = f"VIX extremely high ({vix:.2f} > {Config.VIX_HIGH_THRESHOLD * 1.5})"
            return False, reason
        if iv_percentile < Config.MIN_IV_PERCENTILE:
            reason = f"IV percentile too low ({iv_percentile:.1f}% < {Config.MIN_IV_PERCENTILE}%)"
            return False, reason
        if iv_percentile > Config.MAX_IV_PERCENTILE:
            reason = f"IV percentile too high ({iv_percentile:.1f}% > {Config.MAX_IV_PERCENTILE}%)"
            return False, reason
        if len(self.trade_manager.active_trades) >= 2:
            reason = "Already have active positions"
            return False, reason

        reason = f"Entry approved - VIX: {vix:.2f}, IV Percentile: {iv_percentile:.1f}%"
        return True, reason

    def calculate_position_size(self, combined_premium: float) -> int:
        max_lots = Config.CAPITAL // (combined_premium * self.broker.get_lot_size("NIFTY") * 100)
        if self.market_data.india_vix > Config.VIX_THRESHOLD:
            return min(max_lots // 2, Config.REDUCED_LOTS)
        return min(max_lots, Config.BASE_LOTS)

    def select_strike(self, current_date: Optional[date] = None) -> Tuple[str, str]:
        spot = self.market_data.nifty_spot
        vix = self.market_data.india_vix

        if vix < Config.VIX_LOW_THRESHOLD:
            otm_distance = Config.OTM_DISTANCE_NORMAL - 50
        elif vix > Config.VIX_HIGH_THRESHOLD:
            otm_distance = Config.OTM_DISTANCE_HIGH_VIX + 100
        else:
            vix_range = Config.VIX_HIGH_THRESHOLD - Config.VIX_LOW_THRESHOLD
            vix_position = (vix - Config.VIX_LOW_THRESHOLD) / vix_range
            otm_distance = Config.OTM_DISTANCE_NORMAL + int(
                vix_position * (Config.OTM_DISTANCE_HIGH_VIX - Config.OTM_DISTANCE_NORMAL))

        ce_strike = round(spot / 50) * 50 + otm_distance
        pe_strike = round(spot / 50) * 50 - otm_distance

        # NEW SEBI RULES: Weekly expiry on TUESDAY (weekday 1), not Thursday
        # Calculate next Tuesday expiry
        current = pd.to_datetime(current_date or datetime.now())
        days_until_tuesday = (1 - current.weekday()) % 7  # Tuesday is weekday 1
        if days_until_tuesday == 0 and current.time() >= dt_time(15, 30):
            # If today is Tuesday after market close, get next Tuesday
            days_until_tuesday = 7
        expiry = (current + pd.Timedelta(days=days_until_tuesday)).date()

        ce_symbol = Utils.prepare_option_symbol(ce_strike, "CE", expiry)
        pe_symbol = Utils.prepare_option_symbol(pe_strike, "PE", expiry)

        logging.info(f"STRIKES SELECTED: CE={ce_strike}, PE={pe_strike}, OTM Distance={otm_distance}, VIX={vix:.2f}")
        return ce_symbol, pe_symbol

    def execute_entry(self, ce_symbol: str, pe_symbol: str, qty: int):
        ce_price = self.broker.get_quote(ce_symbol)
        pe_price = self.broker.get_quote(pe_symbol)
        combined_premium = ce_price + pe_price

        logging.info(f"ENTRY EXECUTION: CE={ce_price:.2f}, PE={pe_price:.2f}, Combined={combined_premium:.2f}")

        if Config.MIN_COMBINED_PREMIUM <= combined_premium <= Config.MAX_COMBINED_PREMIUM:
            for symbol, option_type in [(ce_symbol, "CE"), (pe_symbol, "PE")]:
                price = ce_price if option_type == "CE" else pe_price
                if price > 0:  # Only place order if valid price
                    order_id = self.broker.place_order(symbol, qty, Direction.SELL, price)
                    if order_id:
                        trade = Trade(order_id, symbol, qty, Direction.SELL, price, datetime.now(), option_type)
                        self.trade_manager.add_trade(trade)
        else:
            logging.warning(
                f"Combined premium Rs.{combined_premium:.2f} outside range [{Config.MIN_COMBINED_PREMIUM}, {Config.MAX_COMBINED_PREMIUM}]")

    def check_trailing_stop(self, trade: Trade) -> bool:
        pnl_pct = trade.get_pnl_pct()
        if pnl_pct > 0:
            required_trailing_level = trade.highest_profit * (1 - Config.TRAILING_STOP_PCT)
            if trade.trailing_stop_price is None or required_trailing_level > trade.trailing_stop_price:
                trade.trailing_stop_price = required_trailing_level
        if trade.trailing_stop_price is not None:
            current_pnl = trade.get_pnl()
            if current_pnl < trade.trailing_stop_price:
                logging.info(f"TRAILING STOP HIT: {trade.symbol}")
                return True
        return False

    def check_profit_target(self, trade: Trade) -> bool:
        pnl_pct = trade.get_pnl_pct()
        if pnl_pct >= Config.PROFIT_TARGET_PCT * 100:
            logging.info(f"PROFIT TARGET REACHED: {trade.symbol} at {pnl_pct:.1f}%")
            return True
        return False

    def should_roll_position(self, trade: Trade) -> bool:
        pnl_pct = trade.get_pnl_pct()
        if pnl_pct <= -Config.ROLL_THRESHOLD_PCT * 100 and trade.rolled_from is None:
            logging.info(f"ROLL THRESHOLD REACHED: {trade.symbol} at {pnl_pct:.1f}%")
            return True
        return False

    def roll_position(self, trade: Trade, current_date: Optional[date] = None):
        current_strike = trade.strike_price
        roll_distance = 100
        if trade.option_type == "CE":
            new_strike = current_strike + roll_distance
        else:
            new_strike = current_strike - roll_distance

        expiry = (pd.to_datetime(current_date or datetime.now()) + pd.Timedelta(
            days=7 - (current_date or datetime.now()).weekday())).date()
        new_symbol = Utils.prepare_option_symbol(new_strike, trade.option_type, expiry)
        new_price = self.broker.get_quote(new_symbol)

        if new_price > 0:
            exit_price = self.broker.get_quote(trade.symbol)
            self.trade_manager.close_trade(trade.trade_id, exit_price)

            order_id = self.broker.place_order(new_symbol, trade.qty, Direction.SELL, new_price)
            if order_id:
                new_trade = Trade(order_id, new_symbol, trade.qty, Direction.SELL, new_price,
                                  datetime.now(), trade.option_type)
                new_trade.rolled_from = trade.symbol
                self.trade_manager.add_trade(new_trade)
                self.trade_manager.rolled_positions += 1
                logging.info(f"POSITION ROLLED: {trade.symbol} -> {new_symbol}")

    def manage_active_positions(self, backtest_timestamp: Optional[datetime] = None):
        for trade_id in list(self.trade_manager.active_trades.keys()):
            trade = self.trade_manager.active_trades[trade_id]
            current_price = self.broker.get_quote(trade.symbol)
            if current_price > 0:
                trade.update_price(current_price)

            if self.check_profit_target(trade):
                exit_price = self.broker.get_quote(trade.symbol)
                if exit_price > 0:
                    self.trade_manager.close_trade(trade_id, exit_price)
                continue

            if self.check_trailing_stop(trade):
                exit_price = self.broker.get_quote(trade.symbol)
                if exit_price > 0:
                    self.trade_manager.close_trade(trade_id, exit_price)
                continue

            if self.should_roll_position(trade):
                self.roll_position(trade, backtest_timestamp.date() if backtest_timestamp else None)
                continue

        for option_type in ["CE", "PE"]:
            if self.trade_manager.check_leg_stop_loss(option_type):
                logging.warning(f"{option_type} LEG STOP LOSS HIT - Exiting all positions")
                for trade_id in list(self.trade_manager.active_trades.keys()):
                    trade = self.trade_manager.active_trades[trade_id]
                    exit_price = self.broker.get_quote(trade.symbol)
                    if exit_price > 0:
                        self.trade_manager.close_trade(trade_id, exit_price)
                break

    def run_cycle(self, backtest_timestamp: Optional[datetime] = None):
        self.market_data = self.broker.get_market_data()
        self.market_data.iv_percentile = self.calculate_iv_percentile()

        if Config.PAPER_TRADING or self.broker.backtest_data is not None or Utils.is_market_hours(backtest_timestamp):
            self.manage_active_positions(backtest_timestamp)

            if Utils.is_entry_window(backtest_timestamp) and self.entry_allowed_today:
                should_enter, reason = self.should_enter_trade()
                self.entry_checks_today += 1

                # SMART LOGGING: Only log when decision or reason changes
                if should_enter != self.last_entry_decision or reason != self.last_entry_reason:
                    logging.info(f"ENTRY EVALUATION: {reason}")
                    self.last_entry_decision = should_enter
                    self.last_entry_reason = reason

                if should_enter:
                    ce_symbol, pe_symbol = self.select_strike(backtest_timestamp.date() if backtest_timestamp else None)
                    combined_premium = self.broker.get_quote(ce_symbol) + self.broker.get_quote(pe_symbol)
                    if combined_premium > 0:
                        qty = self.calculate_position_size(combined_premium)
                        self.execute_entry(ce_symbol, pe_symbol, qty)
                        self.entry_allowed_today = False

            if Utils.is_square_off_time(backtest_timestamp):
                if self.trade_manager.active_trades:
                    logging.info("SQUARE OFF TIME - Closing all positions")
                for trade_id in list(self.trade_manager.active_trades.keys()):
                    trade = self.trade_manager.active_trades[trade_id]
                    exit_price = self.broker.get_quote(trade.symbol)
                    if exit_price > 0:
                        self.trade_manager.close_trade(trade_id, exit_price)

    def reset_daily_state(self):
        """Reset daily state for new trading day"""
        self.entry_allowed_today = True
        self.last_entry_decision = None
        self.last_entry_reason = None
        self.entry_checks_today = 0
