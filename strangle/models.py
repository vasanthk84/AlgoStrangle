"""
Data models for the Short Strangle Trading System
"""

from enum import Enum
from datetime import datetime


class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"


class MarketData:
    def __init__(self, **kwargs):
        self.nifty_spot = kwargs.get('nifty_spot', 0.0)
        self.nifty_future = kwargs.get('nifty_future', 0.0)
        self.nifty_open = kwargs.get('nifty_open', 0.0)
        self.nifty_high = kwargs.get('nifty_high', 0.0)
        self.nifty_low = kwargs.get('nifty_low', 0.0)
        self.india_vix = kwargs.get('india_vix', 0.0)
        self.vix_30day_avg = kwargs.get('vix_30day_avg', 0.0)
        self.banknifty_spot = kwargs.get('banknifty_spot', 0.0)
        self.banknifty_open = kwargs.get('banknifty_open', 0.0)
        self.banknifty_high = kwargs.get('banknifty_high', 0.0)
        self.banknifty_low = kwargs.get('banknifty_low', 0.0)
        self.sensex_spot = kwargs.get('sensex_spot', 0.0)
        self.advance_decline_ratio = kwargs.get('advance_decline_ratio', 0.0)
        self.timestamp = kwargs.get('timestamp', datetime.now())
        self.iv_percentile = kwargs.get('iv_percentile', 50.0)
        self.atm_iv = kwargs.get('atm_iv', 0.0)
        self.iv_rank = kwargs.get('iv_rank', 50.0)


class Trade:
    def __init__(self, trade_id: str, symbol: str, qty: int, direction: Direction, price: float,
                 timestamp: datetime, option_type: str):
        self.trade_id = trade_id
        self.symbol = symbol
        self.qty = qty
        self.direction = direction
        self.entry_price = price
        self.current_price = price
        self.timestamp = timestamp
        self.option_type = option_type
        self.slippage = 0.0
        self.greeks = None
        self.highest_profit = 0.0
        self.trailing_stop_price = None
        self.strike_price = self._extract_strike_from_symbol(symbol)
        self.rolled_from = None

    def _extract_strike_from_symbol(self, symbol: str) -> float:
        """Extract strike price from option symbol"""
        try:
            import re
            match = re.search(r'(\d{5,})(CE|PE)$', symbol)
            if match:
                return float(match.group(1))
        except:
            pass
        return 0.0

    def update_price(self, price: float):
        self.current_price = price
        self.slippage = abs(self.current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0.0
        current_pnl = self.get_pnl()
        if current_pnl > self.highest_profit:
            self.highest_profit = current_pnl

    def get_pnl(self) -> float:
        return (self.entry_price - self.current_price) * self.qty * (1 if self.direction == Direction.SELL else -1)

    def get_pnl_pct(self) -> float:
        """Get P&L as percentage of entry premium"""
        if self.entry_price == 0:
            return 0.0
        return (self.get_pnl() / (self.entry_price * self.qty)) * 100
