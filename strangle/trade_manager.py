"""
Enhanced Trade Manager with Individual Leg Stop-Loss Support
FIXED: Added missing methods:
- update_active_trades
- check_stop_loss
- get_combined_pnl_pct
- close_all_positions
- reset_daily_metrics (partial)
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import numpy as np

from .config import Config
from .models import MarketData, Trade, Direction
from .broker import BrokerInterface
from .db import DatabaseManager
from .notifier import NotificationManager


class TradeManager:
    def __init__(self, broker: BrokerInterface, db: DatabaseManager, notifier: NotificationManager):
        self.broker = broker
        self.db = db
        self.notifier = notifier
        self.active_trades: Dict[str, Trade] = {}
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.win_trades = 0
        self.ce_pnl = 0.0
        self.pe_pnl = 0.0
        self.ce_trades = 0
        self.pe_trades = 0
        self.rolled_positions = 0
        self.daily_pnl_history = []
        self.active_pairs: Dict[str, Dict] = {}

        # Exit reason tracking
        self.exit_reasons = {
            'profit_target': 0,
            'stop_loss': 0,
            'leg_stop_delta': 0,
            'leg_stop_price': 0,
            'time_square_off': 0,
            'manual': 0
        }

    def add_trade(self, trade: Trade):
        """Add a new trade"""
        self.active_trades[trade.trade_id] = trade
        # Do not save to DB on entry, only on exit
        # self.db.save_trade(trade)
        self.total_trades += 1

        if trade.option_type == "CE":
            self.ce_trades += 1
        else:
            self.pe_trades += 1

        greeks_str = f" {trade.greeks}" if trade.greeks else ""
        logging.info(
            f"TRADE ADDED: {trade.direction.value} {trade.qty}lots {trade.symbol} "
            f"@ Rs.{trade.entry_price:.2f}{greeks_str}"
        )
        self.notifier.send_alert(
            f"New: {trade.direction.value} {trade.qty}lots {trade.symbol} @ Rs.{trade.entry_price:.2f}",
            "INFO"
        )

    def add_trade_pair(self, ce_trade_id: str, pe_trade_id: str, entry_combined: float,
                       entry_time: datetime, lots: int, profit_target: float = None,
                       stop_loss: float = None):
        """Register a strangle pair"""
        pair_id = f"{ce_trade_id}|{pe_trade_id}"

        if profit_target is None:
            # Use profit target from config
            profit_target_points = entry_combined * (Config.PROFIT_TARGET_PCT / 100.0)
        else:
            profit_target_points = profit_target

        if stop_loss is None:
            # --- FIX: Use PAIR_STOP_LOSS_MULTIPLIER from config ---
            stop_loss_points = entry_combined * Config.PAIR_STOP_LOSS_MULTIPLIER
        else:
            stop_loss_points = stop_loss

        self.active_pairs[pair_id] = {
            'ce_id': ce_trade_id,
            'pe_id': pe_trade_id,
            'entry_combined': entry_combined,
            'entry_time': entry_time,
            'lots': lots,
            'profit_target_points': profit_target_points,
            'stop_loss_points': stop_loss_points
        }

        logging.info(
            f"PAIR REGISTERED: Entry={entry_combined:.2f} | "
            f"Target PNL Pts={profit_target_points:.2f} | "
            f"Stop PNL Pts={-stop_loss_points:.2f}"
        )

    def remove_trade_pair(self, pair_id: str):
        """Remove a pair"""
        if pair_id in self.active_pairs:
            del self.active_pairs[pair_id]

    def get_pair_current_combined(self, pair_id: str) -> Optional[float]:
        """Get current combined premium for a pair"""
        meta = self.active_pairs.get(pair_id)
        if not meta:
            return None

        ce = self.active_trades.get(meta['ce_id'])
        pe = self.active_trades.get(meta['pe_id'])

        if not ce or not pe:
            return None

        return ce.current_price + pe.current_price

    def close_single_leg(self, trade_id: str, exit_timestamp: Optional[datetime] = None,
                        reason: str = "Unknown"):
        """
        Close individual leg (CRITICAL for directional risk management)
        """
        if trade_id not in self.active_trades:
            return

        trade = self.active_trades[trade_id]
        exit_price = self.broker.get_quote(trade.symbol)

        if exit_price <= 0:
            logging.error(f"Invalid exit price for {trade.symbol}")
            return

        trade.update_price(exit_price)
        pnl = trade.get_pnl()
        pnl_pct = trade.get_pnl_pct()

        self.daily_pnl += pnl
        if trade.option_type == "CE":
            self.ce_pnl += pnl
        else:
            self.pe_pnl += pnl

        if pnl > 0:
            self.win_trades += 1

        ts = exit_timestamp or datetime.now()

        # Track exit reason
        if 'LEG STOP (Delta)' in reason:
            self.exit_reasons['leg_stop_delta'] += 1
        elif 'LEG STOP (Price)' in reason:
            self.exit_reasons['leg_stop_price'] += 1

        self.db.save_trade(trade, exit_price, ts, reason)

        greeks_str = f" Δ={trade.greeks.delta:.1f}" if trade.greeks else ""
        logging.warning(
            f"LEG CLOSED: {trade.symbol}{greeks_str} | "
            f"Entry={trade.entry_price:.2f} Exit={exit_price:.2f} | "
            f"P&L=Rs.{pnl:+,.2f} ({pnl_pct:+.1f}%) | {reason}"
        )

        self.notifier.send_alert(
            f"Leg Closed: {trade.symbol}, P&L: Rs.{pnl:,.2f}, {reason}",
            "WARNING"
        )

        # Remove from active trades
        del self.active_trades[trade_id]

        # Check if this breaks a pair
        for pair_id in list(self.active_pairs.keys()):
            meta = self.active_pairs[pair_id]
            if trade_id in [meta['ce_id'], meta['pe_id']]:
                logging.warning(f"PAIR BROKEN: {pair_id} - Naked position now!")
                # Remove the broken pair to prevent errors
                self.remove_trade_pair(pair_id)

    def close_pair(self, pair_id: str, exit_timestamp: Optional[datetime] = None,
                   reason: str = "Unknown"):
        """Close both legs of a pair"""
        meta = self.active_pairs.get(pair_id)
        if not meta:
            logging.warning(f"Attempted to close non-existent pair: {pair_id}")
            return

        ce_id = meta['ce_id']
        pe_id = meta['pe_id']
        entry_combined = meta['entry_combined']
        current_combined = self.get_pair_current_combined(pair_id)

        if current_combined:
            pnl_points = entry_combined - current_combined
            pnl_pct = (pnl_points / entry_combined) * 100 if entry_combined > 0 else 0

            logging.info(
                f"PAIR CLOSING: {pair_id} | "
                f"Entry={entry_combined:.2f} Current={current_combined:.2f} | "
                f"P&L={pnl_points:+.2f} pts ({pnl_pct:+.1f}%) | {reason}"
            )

            # Track exit reason
            if 'PROFIT TARGET' in reason:
                self.exit_reasons['profit_target'] += 1
            elif 'PAIR STOP' in reason:
                self.exit_reasons['stop_loss'] += 1
            elif 'TIME EXIT' in reason or 'SQUARE OFF' in reason:
                self.exit_reasons['time_square_off'] += 1
            else:
                self.exit_reasons['manual'] += 1

        # Close both legs
        if ce_id in self.active_trades:
            ce_trade = self.active_trades[ce_id]
            exit_price = self.broker.get_quote(ce_trade.symbol)
            if exit_price > 0:
                self.close_trade(ce_id, exit_price, exit_timestamp, reason)

        if pe_id in self.active_trades:
            pe_trade = self.active_trades[pe_id]
            exit_price = self.broker.get_quote(pe_trade.symbol)
            if exit_price > 0:
                self.close_trade(pe_id, exit_price, exit_timestamp, reason)

        self.remove_trade_pair(pair_id)

    def close_trade(self, trade_id: str, exit_price: float,
                    exit_timestamp: Optional[datetime] = None, reason: str = "Unknown"):
        """Close a trade (internal method)"""
        if trade_id not in self.active_trades:
            return

        trade = self.active_trades[trade_id]
        trade.update_price(exit_price)
        pnl = trade.get_pnl()
        pnl_pct = trade.get_pnl_pct()

        self.daily_pnl += pnl
        if trade.option_type == "CE":
            self.ce_pnl += pnl
        else:
            self.pe_pnl += pnl

        if pnl > 0:
            self.win_trades += 1

        ts = exit_timestamp or datetime.now()
        self.db.save_trade(trade, exit_price, ts, reason)

        greeks_str = f" {trade.greeks}" if trade.greeks else ""
        logging.info(
            f"TRADE CLOSED: {trade.symbol}{greeks_str} | "
            f"P&L=Rs.{pnl:+,.2f} ({pnl_pct:+.1f}%)"
        )

        del self.active_trades[trade_id]

    # --- NEW: Method to close all open positions ---
    def close_all_positions(self, reason: str, exit_timestamp: Optional[datetime] = None):
        """Closes all active pairs and any remaining single legs."""

        # Close all registered pairs first
        for pair_id in list(self.active_pairs.keys()):
            self.close_pair(pair_id, exit_timestamp, reason)

        # Close any remaining individual legs
        for trade_id in list(self.active_trades.keys()):
            self.close_single_leg(trade_id, exit_timestamp, reason)

    # --- NEW: Method to update all active trades ---
    def update_active_trades(self, market_data: MarketData):
        """
        Updates current_price and greeks for all active trades.
        This is crucial for P&L and stop-loss checks.
        """
        if not self.active_trades:
            return

        spot = market_data.nifty_spot
        vix = market_data.india_vix # VIX as percentage

        for trade in self.active_trades.values():
            # Get the current price from the broker
            current_price = self.broker.get_quote(trade.symbol)

            # Calculate current greeks
            dte = self.broker.greeks_calc.get_dte(trade.expiry, market_data.timestamp.date())
            greeks = self.broker.greeks_calc.calculate_all_greeks(
                spot, trade.strike_price, dte, vix, trade.option_type
            )

            # Update the trade object
            trade.update_price(current_price, greeks)

    # --- NEW: Method to check stop losses ---
    def check_stop_loss(self, market_data: MarketData):
        """
        Checks individual leg stop-losses based on price and delta.
        """
        # Iterate over a copy of keys to allow deletion
        for trade_id in list(self.active_trades.keys()):
            trade = self.active_trades[trade_id]

            # 1. Price Stop-Loss (e.g., premium doubled)
            loss_multiple = trade.get_loss_multiple()
            if loss_multiple >= Config.LEG_STOP_LOSS_MULTIPLIER:
                reason = f"LEG STOP (Price): {loss_multiple:.1f}x >= {Config.LEG_STOP_LOSS_MULTIPLIER}x"
                logging.warning(reason)
                self.close_single_leg(trade_id, market_data.timestamp, reason)
                continue # Move to next trade

            # 2. Delta Stop-Loss (e.g., delta breached 40)
            if trade.greeks:
                current_delta = abs(trade.greeks.delta)
                if current_delta >= Config.ROLL_TRIGGER_DELTA:
                    reason = f"LEG STOP (Delta): {current_delta:.1f} >= {Config.ROLL_TRIGGER_DELTA}"
                    logging.warning(reason)
                    self.close_single_leg(trade_id, market_data.timestamp, reason)
                    continue # Move to next trade

    # --- NEW: Method to get combined P&L % ---
    def get_combined_pnl_pct(self, pair_id: str) -> Optional[float]:
        """
        Calculates the P&L percentage for a given pair based on entry premium.
        """
        meta = self.active_pairs.get(pair_id)
        if not meta:
            return None

        entry_combined = meta['entry_combined']
        if entry_combined == 0:
            return None

        current_combined = self.get_pair_current_combined(pair_id)
        if current_combined is None:
            return None

        # P&L = Entry Premium - Current Premium
        pnl_points = entry_combined - current_combined
        pnl_pct = (pnl_points / entry_combined) * 100

        return pnl_pct

    def get_leg_trades(self, option_type: str) -> List[Trade]:
        """Get all trades of a specific type"""
        return [t for t in self.active_trades.values() if t.option_type == option_type]

    def get_leg_pnl(self, option_type: str) -> float:
        """Get P&L for a specific leg type"""
        return sum(t.get_pnl() for t in self.get_leg_trades(option_type))

    def reset_daily_metrics(self):
        """Reset metrics for new day"""
        if self.daily_pnl != 0 or len(self.active_trades) > 0:
             self.daily_pnl_history.append(self.daily_pnl)

        self.daily_pnl = 0.0
        self.ce_pnl = 0.0
        self.pe_pnl = 0.0
        self.total_trades = 0
        self.win_trades = 0
        self.ce_trades = 0
        self.pe_trades = 0
        self.rolled_positions = 0
        self.exit_reasons = {k: 0 for k in self.exit_reasons}


    def get_performance_metrics(self) -> Any:
        """Get performance metrics"""
        class Metrics:
            pass

        metrics = Metrics()
        metrics.total_trades = self.total_trades
        metrics.win_trades = self.win_trades
        metrics.win_rate = (self.win_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        metrics.total_pnl = self.daily_pnl
        metrics.ce_pnl = self.ce_pnl
        metrics.pe_pnl = self.pe_pnl
        metrics.rolled_positions = self.rolled_positions
        metrics.exit_reasons = self.exit_reasons.copy()

        # Calculate drawdown
        history = self.daily_pnl_history + [self.daily_pnl] # Include current day
        if history:
            cumulative = np.cumsum(history)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = cumulative - running_max
            metrics.max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0.0
        else:
            metrics.max_drawdown = 0.0

        # Calculate profit factor
        if history:
            profits = [p for p in history if p > 0]
            losses = [abs(p) for p in history if p < 0]
            total_profit = sum(profits) if profits else 0
            total_loss = sum(losses) if losses else 0
            metrics.profit_factor = total_profit / total_loss if total_loss > 0 else 999.0 # High if no losses
        else:
            metrics.profit_factor = 0.0

        # Calculate Sharpe ratio
        if len(history) > 1:
            returns = np.array(history)
            metrics.sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        else:
            metrics.sharpe_ratio = 0.0

        return metrics

    def print_exit_summary(self):
        """Print exit reason breakdown"""
        total_exits = sum(self.exit_reasons.values())
        if total_exits == 0:
            return

        print(f"\n{'-' * 60}")
        print("EXIT REASON BREAKDOWN:")
        print(f"{'-' * 60}")
        for reason, count in self.exit_reasons.items():
            pct = (count / total_exits) * 100
            print(f"  {reason.replace('_', ' ').title()}: {count} ({pct:.1f}%)")
        print(f"{'-' * 60}\n")