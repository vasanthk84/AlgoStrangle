"""
Utility functions for the Short Strangle Trading System
"""

from datetime import datetime, date, time as dt_time
from typing import Optional
import numpy as np

from .config import Config


class Utils:
    @staticmethod
    def get_now(backtest_timestamp: Optional[datetime] = None) -> datetime:
        return backtest_timestamp if backtest_timestamp is not None else datetime.now()

    @staticmethod
    def is_market_hours(backtest_timestamp: Optional[datetime] = None) -> bool:
        now = Utils.get_now(backtest_timestamp).time()
        start = dt_time.fromisoformat(Config.MARKET_START)
        end = dt_time.fromisoformat(Config.MARKET_END)
        return start <= now <= end

    @staticmethod
    def is_entry_window(backtest_timestamp: Optional[datetime] = None) -> bool:
        now = Utils.get_now(backtest_timestamp).time()
        start = dt_time.fromisoformat(Config.ENTRY_START)
        stop = dt_time.fromisoformat(Config.ENTRY_STOP)
        return start <= now <= stop

    @staticmethod
    def is_square_off_time(backtest_timestamp: Optional[datetime] = None) -> bool:
        now = Utils.get_now(backtest_timestamp).time()
        square_off = dt_time.fromisoformat(Config.SQUARE_OFF)
        return now >= square_off

    @staticmethod
    def is_holiday(backtest_date: Optional[date] = None) -> bool:
        if backtest_date:
            return backtest_date.weekday() in [5, 6]
        today = datetime.now().date()
        return today.weekday() in [5, 6]

    @staticmethod
    def generate_id() -> str:
        return str(np.random.randint(100000, 999999))

    @staticmethod
    def prepare_option_symbol(strike: float, option_type: str, expiry: date) -> str:
        expiry_str = expiry.strftime("%y%b").upper()
        strike_str = str(int(strike))
        return f"NIFTY{expiry_str}{strike_str}{option_type}"
