"""
Database management for the Short Strangle Trading System
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
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS trades
                       (
                           trade_id
                           TEXT
                           PRIMARY
                           KEY,
                           symbol
                           TEXT,
                           qty
                           INTEGER,
                           direction
                           TEXT,
                           entry_price
                           REAL,
                           exit_price
                           REAL,
                           entry_time
                           TEXT,
                           exit_time
                           TEXT,
                           option_type
                           TEXT,
                           pnl
                           REAL,
                           strike_price
                           REAL,
                           rolled_from
                           TEXT
                       )
                       ''')
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS daily_performance
                       (
                           date
                           TEXT
                           PRIMARY
                           KEY,
                           total_trades
                           INTEGER,
                           win_trades
                           INTEGER,
                           total_pnl
                           REAL,
                           ce_pnl
                           REAL,
                           pe_pnl
                           REAL,
                           max_drawdown
                           REAL,
                           profit_factor
                           REAL,
                           sharpe_ratio
                           REAL,
                           rolled_positions
                           INTEGER
                       )
                       ''')
        self.conn.commit()

    def save_trade(self, trade: Trade, exit_price: float = None, exit_time: datetime = None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO trades 
            (trade_id, symbol, qty, direction, entry_price, exit_price, entry_time, exit_time, 
             option_type, pnl, strike_price, rolled_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade.trade_id, trade.symbol, trade.qty, trade.direction.value,
            trade.entry_price, exit_price,
            trade.timestamp.isoformat(),
            exit_time.isoformat() if exit_time else None,
            trade.option_type,
            trade.get_pnl() if exit_price else None,
            trade.strike_price,
            trade.rolled_from
        ))
        self.conn.commit()

    def save_daily_performance(self, date_str: str, metrics: Any):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO daily_performance 
            (date, total_trades, win_trades, total_pnl, ce_pnl, pe_pnl, max_drawdown, 
             profit_factor, sharpe_ratio, rolled_positions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str, metrics.total_trades, metrics.win_trades, metrics.total_pnl,
            metrics.ce_pnl, metrics.pe_pnl, metrics.max_drawdown,
            metrics.profit_factor, metrics.sharpe_ratio, metrics.rolled_positions
        ))
        self.conn.commit()

    def get_performance_history(self, days: int = 30) -> pd.DataFrame:
        query = f"SELECT * FROM daily_performance ORDER BY date DESC LIMIT {days}"
        return pd.read_sql_query(query, self.conn)

    def get_all_trades(self) -> pd.DataFrame:
        query = "SELECT * FROM trades ORDER BY entry_time"
        return pd.read_sql_query(query, self.conn)

    def close(self):
        self.conn.close()
