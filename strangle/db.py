"""
Database management with exit reason tracking
"""

import sqlite3
from datetime import datetime
from typing import Any
import pandas as pd

from .models import Trade


class DatabaseManager:
    def __init__(self, db_file: str):
        self.conn = sqlite3.connect(db_file)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()

        # Enhanced trades table with exit_reason column
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT,
                qty INTEGER,
                direction TEXT,
                entry_price REAL,
                exit_price REAL,
                entry_time TEXT,
                exit_time TEXT,
                option_type TEXT,
                pnl REAL,
                pnl_pct REAL,
                strike_price REAL,
                rolled_from TEXT,
                exit_reason TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_performance (
                date TEXT PRIMARY KEY,
                total_trades INTEGER,
                win_trades INTEGER,
                total_pnl REAL,
                ce_pnl REAL,
                pe_pnl REAL,
                max_drawdown REAL,
                profit_factor REAL,
                sharpe_ratio REAL,
                rolled_positions INTEGER,
                profit_target_exits INTEGER,
                stop_loss_exits INTEGER,
                time_exits INTEGER
            )
        ''')

        self.conn.commit()

    def save_trade(self, trade: Trade, exit_price: float = None,
                   exit_time: datetime = None, exit_reason: str = None):
        cursor = self.conn.cursor()

        pnl = None
        pnl_pct = None
        if exit_price:
            trade.update_price(exit_price)
            pnl = trade.get_pnl()
            pnl_pct = trade.get_pnl_pct()

        cursor.execute('''
            INSERT OR REPLACE INTO trades 
            (trade_id, symbol, qty, direction, entry_price, exit_price, entry_time, exit_time, 
             option_type, pnl, pnl_pct, strike_price, rolled_from, exit_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade.trade_id, trade.symbol, trade.qty, trade.direction.value,
            trade.entry_price, exit_price,
            trade.timestamp.isoformat(),
            exit_time.isoformat() if exit_time else None,
            trade.option_type,
            pnl, pnl_pct,
            trade.strike_price,
            trade.rolled_from,
            exit_reason
        ))
        self.conn.commit()

    def save_daily_performance(self, date_str: str, metrics: Any):
        cursor = self.conn.cursor()

        exit_reasons = metrics.exit_reasons if hasattr(metrics, 'exit_reasons') else {}

        cursor.execute('''
            INSERT OR REPLACE INTO daily_performance 
            (date, total_trades, win_trades, total_pnl, ce_pnl, pe_pnl, max_drawdown, 
             profit_factor, sharpe_ratio, rolled_positions, profit_target_exits, 
             stop_loss_exits, time_exits)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str, metrics.total_trades, metrics.win_trades, metrics.total_pnl,
            metrics.ce_pnl, metrics.pe_pnl, metrics.max_drawdown,
            metrics.profit_factor, metrics.sharpe_ratio, metrics.rolled_positions,
            exit_reasons.get('profit_target', 0),
            exit_reasons.get('stop_loss', 0),
            exit_reasons.get('time_square_off', 0)
        ))
        self.conn.commit()

    def get_performance_history(self, days: int = 30) -> pd.DataFrame:
        query = f"SELECT * FROM daily_performance ORDER BY date DESC LIMIT {days}"
        return pd.read_sql_query(query, self.conn)

    def get_all_trades(self) -> pd.DataFrame:
        query = "SELECT * FROM trades ORDER BY entry_time"
        return pd.read_sql_query(query, self.conn)

    def get_exit_reason_stats(self) -> pd.DataFrame:
        """Get statistics on exit reasons"""
        query = """
            SELECT 
                exit_reason,
                COUNT(*) as count,
                AVG(pnl) as avg_pnl,
                SUM(pnl) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct
            FROM trades
            WHERE exit_reason IS NOT NULL
            GROUP BY exit_reason
            ORDER BY count DESC
        """
        return pd.read_sql_query(query, self.conn)

    def close(self):
        self.conn.close()