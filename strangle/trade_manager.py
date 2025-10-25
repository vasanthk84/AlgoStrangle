"""
Trade management for the Short Strangle Trading System
"""

import logging
from typing import Dict, List, Any
from datetime import datetime
import numpy as np

from .config import Config
from .models import Trade, Direction
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

    def add_trade(self, trade: Trade):
        self.active_trades[trade.trade_id] = trade
        self.db.save_trade(trade)
        self.total_trades += 1
        if trade.option_type == "CE":
            self.ce_trades += 1
        else:
            self.pe_trades += 1
        logging.info(
            f"TRADE ENTERED: {trade.direction.value} {trade.qty} {trade.symbol} @ Rs.{trade.entry_price:.2f}"
        )
        self.notifier.send_alert(
            f"New Trade: {trade.direction.value} {trade.qty} {trade.symbol} @ Rs.{trade.entry_price:.2f}",
            "INFO"
        )

    def close_trade(self, trade_id: str, exit_price: float):
        if trade_id in self.active_trades:
            trade = self.active_trades[trade_id]
            trade.update_price(exit_price)
            pnl = trade.get_pnl()
            self.daily_pnl += pnl
            if trade.option_type == "CE":
                self.ce_pnl += pnl
            else:
                self.pe_pnl += pnl
            if pnl > 0:
                self.win_trades += 1
            self.db.save_trade(trade, exit_price, datetime.now())
            logging.info(f"TRADE CLOSED: {trade.symbol}, P&L: Rs.{pnl:,.2f}")
            self.notifier.send_alert(
                f"Closed Trade: {trade.symbol}, P&L: Rs.{pnl:,.2f}",
                "INFO" if pnl >= 0 else "WARNING"
            )
            del self.active_trades[trade_id]

    def get_leg_trades(self, option_type: str) -> List[Trade]:
        return [t for t in self.active_trades.values() if t.option_type == option_type]

    def get_leg_pnl(self, option_type: str) -> float:
        return sum(t.get_pnl() for t in self.get_leg_trades(option_type))

    def check_leg_stop_loss(self, option_type: str) -> bool:
        leg_trades = self.get_leg_trades(option_type)
        if not leg_trades:
            return False
        total_entry_premium = sum(t.entry_price * t.qty for t in leg_trades)
        if total_entry_premium == 0:
            return False
        leg_pnl = self.get_leg_pnl(option_type)
        loss_pct = abs(leg_pnl / total_entry_premium)
        return loss_pct >= Config.MAX_LOSS_ONE_LEG_PCT

    def reset_daily_metrics(self):
        """Reset metrics for new trading day"""
        self.daily_pnl_history.append(self.daily_pnl)
        self.daily_pnl = 0.0
        self.ce_pnl = 0.0
        self.pe_pnl = 0.0

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

        # Calculate drawdown
        if self.daily_pnl_history:
            cumulative = np.cumsum(self.daily_pnl_history)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = cumulative - running_max
            metrics.max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0.0
        else:
            metrics.max_drawdown = 0.0

        # Calculate profit factor
        if self.daily_pnl_history:
            profits = [p for p in self.daily_pnl_history if p > 0]
            losses = [abs(p) for p in self.daily_pnl_history if p < 0]
            total_profit = sum(profits) if profits else 0
            total_loss = sum(losses) if losses else 1
            metrics.profit_factor = total_profit / total_loss if total_loss > 0 else 0.0
        else:
            metrics.profit_factor = 0.0

        # Calculate Sharpe ratio
        if len(self.daily_pnl_history) > 1:
            returns = np.array(self.daily_pnl_history)
            metrics.sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        else:
            metrics.sharpe_ratio = 0.0

        return metrics
