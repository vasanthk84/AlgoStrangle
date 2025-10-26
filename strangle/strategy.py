"""
Enhanced Short Strangle Strategy with Delta-Based Selection and Entry Logging
FIXED: Uses centralized log file path from config.py
"""

import logging
import os
from datetime import datetime, date, time as dt_time
from typing import Optional, Tuple
import pandas as pd

from .config import Config
from .models import MarketData, Trade, Direction
from .broker import BrokerInterface
from .trade_manager import TradeManager
from .notifier import NotificationManager
from .utils import Utils
from .greeks_calculator import GreeksCalculator
from .entry_logger import EntryLogger
from .regime_detector import RegimeDetector, MarketRegime, StrategyType
from .spread_strategies import SpreadStrategies

# Setup logging
# This basicConfig will be (or should be) called in your run.py
# If it's not, your run.py should be setting this up using Config.LOG_FILE
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class ShortStrangleStrategy:
    """
    Implements a short strangle/spread strategy with adaptive regime detection.
    """
    def __init__(self, broker: BrokerInterface, trade_manager: TradeManager,
                 notifier: NotificationManager):
        self.broker = broker
        self.trade_manager = trade_manager
        self.notifier = notifier
        self.market_data = MarketData()
        self.vix_history = []
        self.entry_allowed_today = True
        self.last_entry_decision = None
        self.last_entry_reason = None
        self.entry_checks_today = 0
        self.greeks_calc = GreeksCalculator()

        # --- FIX: Use centralized log path from Config ---
        # The log directory and file path are now defined in config.py
        self.entry_logger = EntryLogger(Config.ENTRY_LOG_FILE)
        logging.info(f"Entry logger initialized. Saving to: {Config.ENTRY_LOG_FILE}")
        # --- End Fix ---

        self.regime_detector = RegimeDetector(lookback_days=Config.REGIME_LOOKBACK_DAYS)
        self.spread_strategies = SpreadStrategies(broker, trade_manager, self.greeks_calc)

    def calculate_iv_rank(self) -> float:
        """Calculate IV Rank (52-week range)"""
        if len(self.vix_history) < 30:
            self.vix_history.append(self.market_data.india_vix)
        else:
            self.vix_history = self.vix_history[1:] + [self.market_data.india_vix]

        if len(self.vix_history) < Config.REGIME_LOOKBACK_DAYS:
            return 0.0

        min_vix = min(self.vix_history)
        max_vix = max(self.vix_history)

        if max_vix == min_vix:
            return 0.0

        return ((self.market_data.india_vix - min_vix) / (max_vix - min_vix)) * 100

    def get_trend_bias(self, lookback_days: int) -> MarketRegime:
        """Wrapper for the RegimeDetector"""
        self.regime_detector.spot_history.append(self.market_data.nifty_spot)

        if len(self.regime_detector.spot_history) > lookback_days * 5:
             self.regime_detector.spot_history = self.regime_detector.spot_history[-lookback_days * 5:]

        regime, _ = self.regime_detector.detect_regime(
            self.market_data.nifty_spot,
            self.market_data.india_vix,
            self.market_data.nifty_open,
            self.market_data.nifty_high,
            self.market_data.nifty_low
        )
        return regime

    def get_weekly_expiry(self, entry_timestamp: datetime) -> date:
        """Find the nearest weekly expiry (Tuesday) that is at least MIN_DTE_TO_HOLD days away"""
        current = entry_timestamp.date()
        days_to_add = (Config.WEEKLY_EXPIRY_DAY - current.weekday()) % 7

        if days_to_add == 0 and entry_timestamp.time() >= dt_time.fromisoformat(Config.MARKET_END):
            days_to_add = 7

        # If the calculated expiry is too close, roll to the next week
        if days_to_add < Config.MIN_DTE_TO_HOLD:
            days_to_add += 7

        expiry = current + pd.Timedelta(days=days_to_add)
        return expiry


    def find_strangle_strikes(self, expiry: date, target_delta: float) -> Optional[Tuple[float, float, float, float]]:
        """
        Finds CE and PE strikes *closest* to the target_delta (e.g., 15) for a short strangle.
        """
        dte = self.greeks_calc.get_dte(expiry, self.market_data.timestamp.date())
        vix = self.market_data.india_vix

        if dte <= 0:
            logging.warning("DTE is 0. Cannot find strikes.")
            return None

        step = 50
        max_search_distance = 1500 # 1500 points OTM

        best_ce_strike = None
        min_ce_delta_diff = float('inf')
        best_ce_delta = 0.0

        best_pe_strike = None
        min_pe_delta_diff = float('inf')
        best_pe_delta = 0.0

        # Search for CE
        for i in range(0, max_search_distance, step):
            strike = Utils.round_strike(self.market_data.nifty_spot + i)
            greeks = self.greeks_calc.calculate_all_greeks(self.market_data.nifty_spot, strike, dte, vix, "CE")
            delta = greeks.delta # Positive value, e.g., 20.5

            diff = abs(delta - target_delta)

            if diff < min_ce_delta_diff:
                min_ce_delta_diff = diff
                best_ce_strike = strike
                best_ce_delta = delta

            if delta < (target_delta - 10):
                break

        # Search for PE
        for i in range(0, max_search_distance, step):
            strike = Utils.round_strike(self.market_data.nifty_spot - i)
            greeks = self.greeks_calc.calculate_all_greeks(self.market_data.nifty_spot, strike, dte, vix, "PE")
            delta = abs(greeks.delta)  # Absolute value, e.g., 20.5

            diff = abs(delta - target_delta)

            if diff < min_pe_delta_diff:
                min_pe_delta_diff = diff
                best_pe_strike = strike
                best_pe_delta = -delta # Store as negative

            if delta < (target_delta - 10):
                break

        if best_ce_strike and best_pe_strike:
            return best_ce_strike, best_pe_strike, best_ce_delta, best_pe_delta

        return None

    def calculate_position_size(self, combined_premium: float, dte: int) -> int:
        """Calculate position size based on max risk and premium"""
        lot_size = self.broker.get_lot_size("NIFTY")

        if combined_premium <= 0:
            logging.warning(f"Invalid combined premium: {combined_premium}")
            return 0

        max_risk = Config.CAPITAL * Config.MAX_RISK_PER_TRADE_PCT
        potential_loss = combined_premium * lot_size * Config.LEG_STOP_LOSS_MULTIPLIER

        if potential_loss <= 0:
             logging.warning(f"Invalid potential_loss: {potential_loss}. Premium: {combined_premium}")
             return 0

        max_lots = int(max_risk / potential_loss)

        logging.info(f"POSITION SIZING: max_risk={max_risk:.2f}, potential_loss={potential_loss:.2f}, max_lots={max_lots}")

        if self.market_data.india_vix > Config.VIX_THRESHOLD:
            max_lots = max(1, max_lots // 2)
            logging.info(f"VIX adjustment: reduced to {max_lots} lots")

        if dte < 7:
            max_lots = max(1, max_lots // 2)
            logging.info(f"DTE adjustment: reduced to {max_lots} lots")

        final_lots = max(1, min(max_lots, Config.BASE_LOTS))
        logging.info(f"FINAL POSITION SIZE: {final_lots} lots")

        return final_lots

    def run_entry_cycle(self):
        """Main method for determining and executing the entry strategy based on market regime."""
        self.entry_checks_today += 1

        if not self.entry_allowed_today:
            return

        current_time = self.market_data.timestamp.time()
        entry_start = dt_time.fromisoformat(Config.ENTRY_START)
        entry_stop = dt_time.fromisoformat(Config.ENTRY_STOP)

        if not (entry_start <= current_time <= entry_stop):
            return

        regime = self.get_trend_bias(Config.TREND_DETECTION_PERIOD)

        if self.market_data.india_vix < 11:
            target_delta = 8
        elif self.market_data.india_vix < 13:
            target_delta = 10
        elif self.market_data.india_vix < 16:
            target_delta = 12
        else:
            target_delta = 15

        expiry = self.get_weekly_expiry(self.market_data.timestamp)
        dte = self.greeks_calc.get_dte(expiry, self.market_data.timestamp.date())

        if dte < Config.MIN_DTE_TO_HOLD or dte > Config.MAX_DTE_TO_ENTER:
            self.entry_allowed_today = False
            self.last_entry_reason = f"DTE ({dte}) outside allowed range ({Config.MIN_DTE_TO_HOLD}-{Config.MAX_DTE_TO_ENTER}). Skipping."
            if self.entry_checks_today <= 1:
                logging.warning(f"Entry Skipped: {self.last_entry_reason}")
                self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)
            return

        strikes_result = None

        if regime in [MarketRegime.RANGE_BOUND, MarketRegime.LOW_VOLATILITY]:
            if self.market_data.india_vix < Config.VIX_LOW_THRESHOLD:
                self.last_entry_reason = f"Regime: {regime.value} but VIX too low {self.market_data.india_vix:.1f}. Skipping."
                if self.entry_checks_today <= 1:
                    logging.info(f"Entry Skipped: {self.last_entry_reason}")
                    self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)
                return

            self.last_entry_reason = f"Regime: {regime.value}. Target Delta: {target_delta}."
            strikes_result = self.find_strangle_strikes(expiry, target_delta)

            if strikes_result is None:
                self.last_entry_reason += " - Could not find suitable strikes."
                if self.entry_checks_today <= 1:
                    logging.warning(f"Entry Skipped: {self.last_entry_reason}")
                    self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)
                return

            strategy_to_run = StrategyType.SHORT_STRANGLE

        elif regime == MarketRegime.TRENDING_UP:
            self.last_entry_reason = f"Regime: {regime.value}. Strategy: SHORT_PUT_SPREAD."
            self.last_entry_reason += " - Spread strategy not yet fully integrated for execution logging."
            if self.entry_checks_today <= 1:
                logging.info(f"Entry Skipped: {self.last_entry_reason}")
                self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)
            return

        elif regime == MarketRegime.TRENDING_DOWN:
            self.last_entry_reason = f"Regime: {regime.value}. Strategy: SHORT_CALL_SPREAD."
            self.last_entry_reason += " - Spread strategy not yet fully integrated for execution logging."
            if self.entry_checks_today <= 1:
                logging.info(f"Entry Skipped: {self.last_entry_reason}")
                self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)
            return

        elif regime == MarketRegime.HIGH_VOLATILITY:
            self.entry_allowed_today = False
            self.last_entry_reason = f"Regime: HIGH_VOLATILITY (VIX: {self.market_data.india_vix:.2f}). Skipping entry for today."
            if self.entry_checks_today <= 1:
                logging.info(f"Entry Skipped: {self.last_entry_reason}")
                self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)
            return

        else:
            self.entry_allowed_today = False
            self.last_entry_reason = f"Unknown Regime: {regime.value}. Skipping."
            if self.entry_checks_today <= 1:
                logging.info(f"Entry Skipped: {self.last_entry_reason}")
                self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)
            return

        if strategy_to_run == StrategyType.SHORT_STRANGLE and strikes_result:
            ce_strike, pe_strike, ce_delta, pe_delta = strikes_result

            vix_perc = self.market_data.india_vix
            ce_price = self.greeks_calc.get_option_price(self.market_data.nifty_spot, ce_strike, dte, vix_perc, "CE")
            pe_price = self.greeks_calc.get_option_price(self.market_data.nifty_spot, pe_strike, dte, vix_perc, "PE")
            combined_premium = ce_price + pe_price

            qty_lots = self.calculate_position_size(combined_premium, dte)

            if qty_lots > 0:
                logging.info(f"EXECUTING STRANGLE: CE={ce_strike} (Price:{ce_price:.2f}), PE={pe_strike} (Price:{pe_price:.2f}), Lots:{qty_lots}")

                ce_symbol = Utils.generate_option_symbol("NIFTY", expiry, "CE", ce_strike)
                pe_symbol = Utils.generate_option_symbol("NIFTY", expiry, "PE", pe_strike)

                ce_order_id = self.broker.place_order(ce_symbol, qty_lots, Direction.SELL, ce_price)
                pe_order_id = self.broker.place_order(pe_symbol, qty_lots, Direction.SELL, pe_price)

                ce_trade = Trade(
                    trade_id=ce_order_id, symbol=ce_symbol, qty=qty_lots,
                    direction=Direction.SELL, price=ce_price,
                    timestamp=self.market_data.timestamp, option_type="CE",
                    strike_price=ce_strike, expiry=expiry,
                    spot_at_entry=self.market_data.nifty_spot
                )
                pe_trade = Trade(
                    trade_id=pe_order_id, symbol=pe_symbol, qty=qty_lots,
                    direction=Direction.SELL, price=pe_price,
                    timestamp=self.market_data.timestamp, option_type="PE",
                    strike_price=pe_strike, expiry=expiry,
                    spot_at_entry=self.market_data.nifty_spot
                )

                self.trade_manager.add_trade(ce_trade)
                self.trade_manager.add_trade(pe_trade)

                self.trade_manager.add_trade_pair(
                    ce_trade_id=ce_order_id,
                    pe_trade_id=pe_order_id,
                    entry_combined=combined_premium,
                    entry_time=self.market_data.timestamp,
                    lots=qty_lots
                )

                self.entry_allowed_today = False
                self.last_entry_reason = f"STRIKES: CE={ce_strike} (Δ{ce_delta:.1f}), PE={pe_strike} (Δ{pe_delta:.1f})"
                logging.info(f"Entry Approved: {self.last_entry_reason}")

                self.entry_logger.log_decision(
                    self.market_data,
                    approved='YES',
                    reason=self.last_entry_reason,
                    lots=qty_lots,
                    combined_premium=combined_premium
                )
                self.notifier.send_alert(f"ENTRY: Short Strangle @ {self.market_data.nifty_spot:.2f}. CE {ce_strike}, PE {pe_strike}. Premium: {combined_premium:.2f}", "SUCCESS")
                return
            else:
                self.last_entry_reason += " - Position size calculation resulted in 0 lots."

        if self.entry_checks_today <= 1:
            logging.info(f"Entry Skipped: {self.last_entry_reason}")
            self.entry_logger.log_decision(self.market_data, approved='NO', reason=self.last_entry_reason)


    def check_profit_target(self):
        """Checks if the overall position has hit the profit target."""
        if not self.trade_manager.active_pairs:
            return

        target_pnl_pct = Config.PROFIT_TARGET_PCT

        for pair_id in list(self.trade_manager.active_pairs.keys()):
            pnl_pct = self.trade_manager.get_combined_pnl_pct(pair_id)

            if pnl_pct is not None and pnl_pct >= target_pnl_pct:
                logging.info(f"GLOBAL EXIT: Profit Target Hit for pair {pair_id} ({pnl_pct:.1f}%). Squaring off.")
                self.trade_manager.close_pair(pair_id, self.market_data.timestamp, "PROFIT_TARGET")
                self.notifier.send_alert(f"EXIT: Profit Target Hit for pair {pair_id}. P&L: Rs.{self.trade_manager.daily_pnl:,.2f}", "SUCCESS")

    def check_time_square_off(self):
        """Checks if it's time to square off all open positions."""
        if not self.trade_manager.active_trades:
            return

        current_time = self.market_data.timestamp.time()
        square_off_time = dt_time.fromisoformat(Config.SQUARE_OFF_TIME)

        if current_time >= square_off_time:
            logging.info(f"GLOBAL EXIT: Time Square Off ({Config.SQUARE_OFF_TIME}). Squaring off all positions.")
            self.trade_manager.close_all_positions("TIME_SQUARE_OFF", self.market_data.timestamp)
            self.entry_allowed_today = False
            self.notifier.send_alert(f"EXIT: Time Square Off. P&L: Rs.{self.trade_manager.daily_pnl:,.2f}", "INFO")

    def reset_daily_state(self):
        """Resets the state for the start of a new trading day."""
        self.entry_allowed_today = True
        self.last_entry_decision = None
        self.last_entry_reason = None
        self.entry_checks_today = 0
        self.regime_detector.reset_daily()
        self.entry_logger.reset_daily()
        self.trade_manager.reset_daily_metrics()
        logging.info("DAILY STATE RESET for new trading day.")

    def run_cycle(self, current_time: datetime):
        """
        The main strategy cycle run on every tick.
        """
        self.market_data = self.broker.get_market_data()
        self.market_data.iv_rank = self.calculate_iv_rank()

        self.run_entry_cycle()

        if self.trade_manager.active_trades:
            self.trade_manager.update_active_trades(self.market_data)
            self.trade_manager.check_stop_loss(self.market_data)
            self.check_profit_target()
            self.check_time_square_off()