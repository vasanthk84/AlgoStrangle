"""
Utility functions for the Short Strangle Trading System
FIXED: Removed duplicate function definitions.
"""

from datetime import datetime, date, time as dt_time
from typing import Optional, Tuple
import numpy as np
import re
import uuid

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
        # Use the new SQUARE_OFF_TIME from config
        square_off = dt_time.fromisoformat(Config.SQUARE_OFF_TIME)
        return now >= square_off

    @staticmethod
    def is_holiday(backtest_date: Optional[date] = None) -> bool:
        if backtest_date:
            return backtest_date.weekday() in [5, 6]
        today = datetime.now().date()
        return today.weekday() in [5, 6]

    @staticmethod
    def generate_id(length: int = 6) -> str:
        """Generate a short unique ID"""
        return str(uuid.uuid4().hex)[:length]

    @staticmethod
    def round_strike(price: float, step: int = 50) -> float:
        """Rounds price to the nearest strike step"""
        return round(price / step) * step

    @staticmethod
    def generate_option_symbol(instrument: str, expiry: date,
                               option_type: str, strike: float) -> str:
        """
        Generates an option symbol.
        Example: NIFTY25OCT21C18000
        """
        # Format expiry: YYMMM (e.g., 25OCT)
        expiry_str = expiry.strftime('%y%b').upper()
        # Format strike: 5-digit string
        strike_str = str(int(strike))

        # Simplified format for backtesting:
        return f"{instrument}{expiry_str}{strike_str}{option_type.upper()}"

    @staticmethod
    def parse_option_symbol(symbol: str) -> Optional[Tuple[str, float, str]]:
        """
        Parses a simplified symbol to get (Instrument, Strike, Type)
        Example: NIFTY25OCT2118000CE
        """
        # Regex to find the strike and type at the end
        match = re.match(r'^(.*?)(\d{5,})(CE|PE)$', symbol, re.IGNORECASE)
        if match:
            instrument_part = match.group(1)
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            return instrument_part, strike, option_type

        # Try another common format (NIFTY 21OCT25 18000 CE)
        match = re.match(r'^(.*?) \d{2}[A-Z]{3}\d{2} (\d{5,}) (CE|PE)$', symbol, re.IGNORECASE)
        if match:
            instrument_part = match.group(1)
            strike = float(match.group(2))
            option_type = match.group(3).upper()
            return instrument_part, strike, option_type

        return None

    @staticmethod
    def prepare_option_symbol(strike: float, option_type: str, expiry: date) -> str:
        """
        Helper function to quickly generate a symbol.
        (Assumes NIFTY as base instrument)
        """
        return Utils.generate_option_symbol("NIFTY", expiry, option_type, strike)