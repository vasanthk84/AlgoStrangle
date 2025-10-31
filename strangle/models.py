"""
Enhanced Data Models with Greeks Support
"""

from enum import Enum
from datetime import datetime
from typing import Optional


class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"


class Greeks:
    """Option Greeks container"""
    def __init__(self, delta: float = 0.0, gamma: float = 0.0,
                 theta: float = 0.0, vega: float = 0.0):
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega

    def __str__(self):
        return f"Δ={self.delta:.1f} Γ={self.gamma:.4f} Θ={self.theta:.2f} ν={self.vega:.2f}"


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
        self.iv_rank = kwargs.get('iv_rank', 50.0)
        self.atm_iv = kwargs.get('atm_iv', 0.0)
        self.ce_symbol = kwargs.get('ce_symbol', '')
        self.pe_symbol = kwargs.get('pe_symbol', '')


class Trade:
    def __init__(self, trade_id: str, symbol: str, qty: int, direction: Direction,
                 price: float, timestamp: datetime, option_type: str,
                 lot_size: int = 75, strike_price: float = None,
                 expiry: datetime = None, spot_at_entry: float = 0.0,
                 trade_type: str = "BASE"):
        self.trade_id = trade_id
        self.symbol = symbol
        self.qty = qty  # Number of lots
        self.lot_size = lot_size  # NIFTY = 75
        self.direction = direction
        self.entry_price = price
        self.current_price = price
        self.timestamp = timestamp
        self.option_type = option_type
        self.slippage = 0.0
        self.greeks: Optional[Greeks] = None
        self.highest_profit = 0.0
        self.trailing_stop_price = None
        self.strike_price = strike_price or self._extract_strike_from_symbol(symbol)
        self.expiry = expiry
        self.spot_at_entry = spot_at_entry
        self.rolled_from = None
        self.hedge_protection: Optional[str] = None
        self.trade_type = trade_type  # "BASE", "HEDGE", or "WING"

    def _extract_strike_from_symbol(self, symbol: str) -> float:
        """Extract strike from symbol"""
        try:
            import re
            match = re.search(r'(\d{5,})(CE|PE)$', symbol)
            if match:
                return float(match.group(1))
        except:
            pass
        return 0.0

    def update_price(self, price: float, greeks: Optional[Greeks] = None):
        """Update price and greeks"""
        self.current_price = price
        if greeks:
            self.greeks = greeks

        self.slippage = abs(self.current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0.0
        current_pnl = self.get_pnl()
        if current_pnl > self.highest_profit:
            self.highest_profit = current_pnl

    def get_pnl(self) -> float:
        """Calculate P&L in Rupees"""
        premium_diff = self.entry_price - self.current_price
        total_contracts = self.qty * self.lot_size

        if self.direction == Direction.SELL:
            pnl = premium_diff * total_contracts
        else:
            pnl = -premium_diff * total_contracts

        return pnl

    def get_pnl_pct(self) -> float:
        """Get P&L as percentage"""
        if self.entry_price == 0:
            return 0.0

        premium_diff = self.entry_price - self.current_price

        if self.direction == Direction.SELL:
            return (premium_diff / self.entry_price) * 100
        else:
            return (-premium_diff / self.entry_price) * 100

    def get_entry_value(self) -> float:
        """Total value at entry"""
        return self.entry_price * self.qty * self.lot_size

    def get_current_value(self) -> float:
        """Current total value"""
        return self.current_price * self.qty * self.lot_size

    def get_loss_multiple(self) -> float:
        """Get loss as multiple of entry premium (for stop-loss)"""
        if self.entry_price == 0:
            return 0.0

        if self.direction == Direction.SELL:
            # Short: loss when price increases
            loss = max(0, self.current_price - self.entry_price)
            return loss / self.entry_price
        else:
            # Long: loss when price decreases
            loss = max(0, self.entry_price - self.current_price)
            return loss / self.entry_price

    def is_near_atm(self, current_spot: float, threshold_points: int = 100) -> bool:
        """Check if near ATM"""
        if self.strike_price == 0:
            return False
        return abs(self.strike_price - current_spot) <= threshold_points