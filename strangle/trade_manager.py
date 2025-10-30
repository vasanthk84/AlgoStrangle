"""
Trade Manager - FINAL FIXED VERSION
✅ P&L tracking fixed (realized + unrealized)
✅ Daily Summary now shows correct CE/PE P&L
✅ Integrated with dynamic Greeks system
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd

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

        # ═══════════════════════════════════════════════════════════════
        # FIX: Enhanced P&L tracking (realized + unrealized)
        # ═══════════════════════════════════════════════════════════════
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.win_trades = 0

        # Separate tracking for realized vs unrealized
        self.ce_pnl = 0.0  # Total CE P&L (for display)
        self.pe_pnl = 0.0  # Total PE P&L (for display)

        self.realized_ce_pnl = 0.0  # Closed positions
        self.realized_pe_pnl = 0.0  # Closed positions

        self.unrealized_ce_pnl = 0.0  # Active positions
        self.unrealized_pe_pnl = 0.0  # Active positions

        self.ce_trades = 0
        self.pe_trades = 0
        self.rolled_positions = 0
        self.daily_pnl_history = []
        self.active_pairs: Dict[str, Dict] = {}

        self.exit_reasons = {
            'profit_target': 0,
            'stop_loss': 0,
            'leg_stop_delta': 0,
            'leg_stop_price': 0,
            'time_square_off': 0,
            'manual': 0
        }

        self.last_entry_timestamp: Optional[datetime] = None
        self.entry_grace_period_minutes = 5
        self._grace_logged = False

    def add_trade(self, trade: Trade):
        """Add a new trade"""
        self.active_trades[trade.trade_id] = trade
        self.total_trades += 1
        self.last_entry_timestamp = trade.timestamp
        logging.info(f"Entry timestamp recorded: {self.last_entry_timestamp}")

        if trade.option_type == "CE":
            self.ce_trades += 1
        else:
            self.pe_trades += 1

        greeks_str = f" {trade.greeks}" if trade.greeks else ""
        logging.info(
            f"TRADE ADDED: {trade.direction.value} {trade.qty}lots {trade.symbol} "
            f"@ Rs.{trade.entry_price:.2f}{greeks_str}"
        )

    def update_active_trades(self, market_data: MarketData):
        """
        ✅ FIXED: Updates prices AND calculates unrealized P&L for display
        """
        if not self.active_trades:
            return

        spot = market_data.nifty_spot
        vix = market_data.india_vix

        if vix <= 0 or pd.isna(vix):
            logging.warning(f"Invalid VIX ({vix}). Skipping updates.")
            return

        if spot <= 0 or pd.isna(spot):
            logging.warning(f"Invalid Spot ({spot}). Skipping updates.")
            return

        # ═══════════════════════════════════════════════════════════════
        # FIX: Reset unrealized P&L before recalculating
        # ═══════════════════════════════════════════════════════════════
        self.unrealized_ce_pnl = 0.0
        self.unrealized_pe_pnl = 0.0

        for trade in self.active_trades.values():
            current_price = 0.0
            greeks = None

            try:
                # BACKTEST MODE
                if self.broker.backtest_data is not None:
                    current_price = self.broker.get_quote(trade.symbol)

                    if current_price > 5000:
                        logging.error(f"UNREALISTIC PRICE for {trade.symbol}: {current_price:.2f}")
                        current_price = trade.entry_price

                    if current_price < 0:
                        current_price = 0.0

                    if 0 < current_price < 5000:
                        if isinstance(trade.expiry, date):
                            dte = self.broker.greeks_calc.get_dte(trade.expiry, market_data.timestamp.date())
                            if dte >= 0:
                                greeks = self.broker.greeks_calc.calculate_all_greeks(
                                    spot, trade.strike_price, dte, vix, trade.option_type
                                )

                # LIVE/DRY-RUN MODE - Get price AND greeks
                else:
                    current_price, greeks = self.broker.get_quote_with_greeks(
                        symbol=trade.symbol,
                        strike=trade.strike_price,
                        option_type=trade.option_type,
                        expiry=trade.expiry,
                        spot=spot,
                        vix=vix,
                        current_date=market_data.timestamp.date()
                    )

                    if current_price > 5000:
                        logging.error(f"UNREALISTIC PRICE: {current_price:.2f}")
                        current_price = trade.entry_price
                        greeks = None

                    if current_price < 0:
                        current_price = 0.0
                        greeks = None

            except Exception as e:
                logging.error(f"Error updating {trade.symbol}: {e}", exc_info=True)
                current_price = trade.entry_price
                greeks = None

            if current_price >= 0:
                trade.update_price(current_price, greeks)

                # ═══════════════════════════════════════════════════════════
                # FIX: Calculate and accumulate unrealized P&L
                # ═══════════════════════════════════════════════════════════
                current_pnl = trade.get_pnl()

                if trade.option_type == "CE":
                    self.unrealized_ce_pnl += current_pnl
                else:
                    self.unrealized_pe_pnl += current_pnl

        # ═══════════════════════════════════════════════════════════════
        # FIX: Update total P&L for display (realized + unrealized)
        # ═══════════════════════════════════════════════════════════════
        self.ce_pnl = self.realized_ce_pnl + self.unrealized_ce_pnl
        self.pe_pnl = self.realized_pe_pnl + self.unrealized_pe_pnl
        self.daily_pnl = self.ce_pnl + self.pe_pnl

    def check_stop_loss(self, market_data: MarketData):
        """Check stop-loss with grace period"""
        if self.last_entry_timestamp:
            time_since_entry = (market_data.timestamp - self.last_entry_timestamp).total_seconds() / 60

            if time_since_entry < self.entry_grace_period_minutes:
                if not self._grace_logged:
                    logging.info(f"⏱️ Grace period: {time_since_entry:.1f}/{self.entry_grace_period_minutes} min")
                    self._grace_logged = True
                return
            else:
                if self._grace_logged:
                    logging.info(f"✅ Grace period expired. Enabling stop-loss.")
                    self._grace_logged = False

        for trade_id in list(self.active_trades.keys()):
            trade = self.active_trades[trade_id]

            if trade.current_price <= 0:
                continue

            if abs(trade.current_price - trade.entry_price) < 1.0:
                continue

            # Price Stop-Loss
            loss_multiple = trade.get_loss_multiple()
            if loss_multiple >= Config.LEG_STOP_LOSS_MULTIPLIER:
                reason = f"LEG STOP (Price): {loss_multiple:.1f}x"
                self.notifier.notify_stop_loss_triggered(
                    trade.symbol, trade.current_price, trade.entry_price, "Price Multiple"
                )
                self.close_single_leg(trade_id, market_data.timestamp, reason)
                continue

            # Delta Stop-Loss
            if trade.greeks:
                current_delta = abs(trade.greeks.delta)
                if current_delta >= Config.ROLL_TRIGGER_DELTA:
                    reason = f"LEG STOP (Delta): {current_delta:.1f}"
                    self.notifier.notify_stop_loss_triggered(
                        trade.symbol, trade.current_price, trade.entry_price, "Delta", current_delta
                    )
                    self.close_single_leg(trade_id, market_data.timestamp, reason)
                    continue

    def close_single_leg(self, trade_id: str, exit_timestamp: Optional[datetime] = None, reason: str = "Unknown"):
        """
        ✅ FIXED: Properly updates realized P&L when closing positions
        """
        if trade_id not in self.active_trades:
            return

        trade = self.active_trades[trade_id]
        exit_price = trade.current_price

        if exit_price > 5000 or exit_price < 0:
            exit_price = 0.0

        temp_trade = Trade(
            trade_id=trade.trade_id, symbol=trade.symbol, qty=trade.qty,
            direction=trade.direction, price=trade.entry_price,
            timestamp=trade.timestamp, option_type=trade.option_type,
            lot_size=trade.lot_size, strike_price=trade.strike_price,
            expiry=trade.expiry, spot_at_entry=trade.spot_at_entry
        )
        temp_trade.update_price(exit_price)

        pnl = temp_trade.get_pnl()
        pnl_pct = temp_trade.get_pnl_pct()

        # ═══════════════════════════════════════════════════════════════
        # FIX: Add to REALIZED P&L (this was missing before!)
        # ═══════════════════════════════════════════════════════════════
        if trade.option_type == "CE":
            self.realized_ce_pnl += pnl
        else:
            self.realized_pe_pnl += pnl

        if pnl > 0:
            self.win_trades += 1

        ts = exit_timestamp or datetime.now()

        if 'Delta' in reason:
            self.exit_reasons['leg_stop_delta'] += 1
        elif 'Price' in reason:
            self.exit_reasons['leg_stop_price'] += 1

        self.db.save_trade(trade, exit_price, ts, reason)

        holding_duration = ts - trade.timestamp
        holding_time = str(holding_duration).split('.')[0]

        self.notifier.notify_exit(reason, trade.symbol, trade.entry_price, exit_price, pnl, pnl_pct, holding_time)

        logging.warning(f"LEG CLOSED: {trade.symbol} | P&L=Rs.{pnl:+,.2f} | {reason}")

        # Remove from active trades
        del self.active_trades[trade_id]

        # Recalculate total P&L (will happen on next update_active_trades)
        # For immediate update:
        self.ce_pnl = self.realized_ce_pnl + self.unrealized_ce_pnl
        self.pe_pnl = self.realized_pe_pnl + self.unrealized_pe_pnl
        self.daily_pnl = self.ce_pnl + self.pe_pnl

        for pair_id in list(self.active_pairs.keys()):
            meta = self.active_pairs[pair_id]
            if trade_id in [meta['ce_id'], meta['pe_id']]:
                self.remove_trade_pair(pair_id)

    def add_trade_pair(self, ce_trade_id: str, pe_trade_id: str, entry_combined: float,
                       entry_time: datetime, lots: int, profit_target: float = None, stop_loss: float = None):
        pair_id = f"{ce_trade_id}|{pe_trade_id}"
        self.active_pairs[pair_id] = {
            'ce_id': ce_trade_id,
            'pe_id': pe_trade_id,
            'entry_combined': entry_combined,
            'entry_time': entry_time,
            'lots': lots,
            'profit_target_points': profit_target or entry_combined * (Config.PROFIT_TARGET_PCT / 100.0),
            'stop_loss_points': stop_loss or entry_combined * Config.PAIR_STOP_LOSS_MULTIPLIER
        }

    def remove_trade_pair(self, pair_id: str):
        if pair_id in self.active_pairs:
            del self.active_pairs[pair_id]

    def get_pair_current_combined(self, pair_id: str) -> Optional[float]:
        meta = self.active_pairs.get(pair_id)
        if not meta:
            return None
        ce = self.active_trades.get(meta['ce_id'])
        pe = self.active_trades.get(meta['pe_id'])
        if not ce or not pe:
            return None
        return ce.current_price + pe.current_price

    def close_pair(self, pair_id: str, exit_timestamp: Optional[datetime] = None, reason: str = "Unknown"):
        meta = self.active_pairs.get(pair_id)
        if not meta:
            return

        if 'PROFIT TARGET' in reason:
            self.exit_reasons['profit_target'] += 1
        elif 'STOP' in reason:
            self.exit_reasons['stop_loss'] += 1
        elif 'TIME' in reason or 'SQUARE' in reason:
            self.exit_reasons['time_square_off'] += 1

        ce_id = meta['ce_id']
        pe_id = meta['pe_id']

        if ce_id in self.active_trades:
            self.close_single_leg(ce_id, exit_timestamp, reason)
        if pe_id in self.active_trades:
            self.close_single_leg(pe_id, exit_timestamp, reason)

        self.remove_trade_pair(pair_id)

    def close_all_positions(self, reason: str, exit_timestamp: Optional[datetime] = None):
        for pair_id in list(self.active_pairs.keys()):
            self.close_pair(pair_id, exit_timestamp, reason)
        for trade_id in list(self.active_trades.keys()):
            self.close_single_leg(trade_id, exit_timestamp, reason)

    def get_combined_pnl_pct(self, pair_id: str) -> Optional[float]:
        meta = self.active_pairs.get(pair_id)
        if not meta or meta['entry_combined'] == 0:
            return None
        current = self.get_pair_current_combined(pair_id)
        if current is None:
            return None
        return ((meta['entry_combined'] - current) / meta['entry_combined']) * 100

    def get_leg_trades(self, option_type: str) -> List[Trade]:
        return [t for t in self.active_trades.values() if t.option_type == option_type]

    def get_leg_pnl(self, option_type: str) -> float:
        return sum(t.get_pnl() for t in self.get_leg_trades(option_type))

    def reset_daily_metrics(self):
        """Reset daily metrics (keep realized P&L until reset)"""
        if self.daily_pnl != 0 or len(self.active_trades) > 0:
            self.daily_pnl_history.append(self.daily_pnl)

        # Reset daily totals
        self.daily_pnl = 0.0
        self.ce_pnl = 0.0
        self.pe_pnl = 0.0

        # Reset realized P&L for new day
        self.realized_ce_pnl = 0.0
        self.realized_pe_pnl = 0.0
        self.unrealized_ce_pnl = 0.0
        self.unrealized_pe_pnl = 0.0

        self.total_trades = 0
        self.win_trades = 0
        self.ce_trades = 0
        self.pe_trades = 0
        self.rolled_positions = 0
        self.exit_reasons = {k: 0 for k in self.exit_reasons}
        self.last_entry_timestamp = None
        self._grace_logged = False

    def get_performance_metrics(self) -> Any:
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

        history = self.daily_pnl_history + [self.daily_pnl]
        if history:
            cumulative = np.cumsum(history)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = cumulative - running_max
            metrics.max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0.0

            profits = [p for p in history if p > 0]
            losses = [abs(p) for p in history if p < 0]
            total_profit = sum(profits) if profits else 0
            total_loss = sum(losses) if losses else 0
            metrics.profit_factor = total_profit / total_loss if total_loss > 0 else 999.0

            returns = np.array(history)
            metrics.sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        else:
            metrics.max_drawdown = 0.0
            metrics.profit_factor = 0.0
            metrics.sharpe_ratio = 0.0

        return metrics

    def print_exit_summary(self):
        total = sum(self.exit_reasons.values())
        if total == 0:
            return
        print(f"\n{'-' * 60}")
        print("EXIT REASON BREAKDOWN:")
        print(f"{'-' * 60}")
        for reason, count in self.exit_reasons.items():
            pct = (count / total) * 100
            print(f"  {reason.replace('_', ' ').title()}: {count} ({pct:.1f}%)")
        print(f"{'-' * 60}\n")