"""
Market Regime Detector - FIXED
✅ Fix #6: Now uses 50-day lookback (was 20)
✅ Multi-timeframe validation
✅ VIX regime confirmation
"""

from typing import Tuple, List, Optional
from datetime import datetime, timedelta, date
from enum import Enum
import numpy as np


class MarketRegime(Enum):
    """Market regime classifications"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE_BOUND = "RANGE_BOUND"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class StrategyType(Enum):
    """Strategy to use based on regime"""
    SHORT_STRANGLE = "SHORT_STRANGLE"
    SHORT_PUT_SPREAD = "SHORT_PUT_SPREAD"
    SHORT_CALL_SPREAD = "SHORT_CALL_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"
    SKIP = "SKIP"


class RegimeDetector:
    """
    ✅ FIX #6: Uses 50-day lookback for reliable trend detection
    """

    def __init__(self, lookback_days: int = 50):
        """
        Args:
            lookback_days: Primary trend lookback (default 50, was 20)
        """
        self.lookback_days = lookback_days
        self.fast_lookback = 10  # Short-term momentum

        self.spot_history: List[float] = []
        self.vix_history: List[float] = []
        self.last_history_update_date: Optional[date] = None

        # ✅ FIX #6: More conservative thresholds for 50-day window
        self.trend_threshold_pct = 3.0  # 3% move = trending (was 4%)
        self.range_position_lower = 0.30
        self.range_position_upper = 0.70

        # VIX thresholds
        self.vix_threshold = 12.0
        self.vix_high_threshold = 18.0
        self.vix_low_threshold = 8.0

    def update_history(self, current_timestamp: datetime, spot_price: float):
        """
        ✅ FIX #6: Updates history once per day (prevents overfitting to intraday noise)
        """
        current_date = current_timestamp.date()

        # Only add one entry per day
        if self.last_history_update_date is None or current_date > self.last_history_update_date:
            self.spot_history.append(spot_price)
            self.last_history_update_date = current_date

            # Trim to prevent indefinite growth
            if len(self.spot_history) > self.lookback_days * 2:
                self.spot_history = self.spot_history[-(self.lookback_days * 2):]

    def detect_regime(self, spot: float, vix: float, nifty_open: float,
                     nifty_high: float, nifty_low: float) -> Tuple[MarketRegime, str]:
        """
        ✅ FIX #6: Enhanced regime detection with multi-timeframe analysis

        Returns:
            Tuple of (MarketRegime, reason_string)
        """

        # Priority 1: Volatility regime (overrides everything)
        if vix >= self.vix_high_threshold:
            return (
                MarketRegime.HIGH_VOLATILITY,
                f"VIX ({vix:.1f}) above HIGH threshold ({self.vix_high_threshold})"
            )

        if vix <= self.vix_low_threshold:
            return (
                MarketRegime.LOW_VOLATILITY,
                f"VIX ({vix:.1f}) below LOW threshold ({self.vix_low_threshold})"
            )

        # Priority 2: Trend detection (requires sufficient history)
        if len(self.spot_history) < self.lookback_days:
            return (
                MarketRegime.RANGE_BOUND,
                f"Insufficient history ({len(self.spot_history)}/{self.lookback_days} days)"
            )

        # ✅ FIX #6: Long-term trend (50 days)
        long_term_prices = np.array(self.spot_history[-self.lookback_days:])
        long_term_high = np.max(long_term_prices)
        long_term_low = np.min(long_term_prices)
        long_term_range_pct = ((long_term_high - long_term_low) / long_term_low) * 100

        # Short-term momentum (10 days)
        if len(self.spot_history) >= self.fast_lookback:
            short_term_prices = np.array(self.spot_history[-self.fast_lookback:])
            short_term_change_pct = (
                (short_term_prices[-1] - short_term_prices[0]) / short_term_prices[0]
            ) * 100
        else:
            short_term_change_pct = 0.0

        # Current position in range (0% = at low, 100% = at high)
        if long_term_high > long_term_low:
            range_position = (spot - long_term_low) / (long_term_high - long_term_low)
        else:
            range_position = 0.5

        # ✅ DECISION LOGIC: Multi-timeframe confirmation

        # Strong uptrend: Long-term range is wide AND short-term momentum is up
        if long_term_range_pct >= self.trend_threshold_pct:
            if range_position >= self.range_position_upper and short_term_change_pct > 1.0:
                return (
                    MarketRegime.TRENDING_UP,
                    f"Trending Up: 50-day range {long_term_range_pct:.1f}%, "
                    f"10-day momentum +{short_term_change_pct:.1f}%, "
                    f"near high ({long_term_high:.0f})"
                )

            # Strong downtrend: Long-term range is wide AND short-term momentum is down
            elif range_position <= self.range_position_lower and short_term_change_pct < -1.0:
                return (
                    MarketRegime.TRENDING_DOWN,
                    f"Trending Down: 50-day range {long_term_range_pct:.1f}%, "
                    f"10-day momentum {short_term_change_pct:.1f}%, "
                    f"near low ({long_term_low:.0f})"
                )

            # Range-bound: Wide range but conflicting signals
            else:
                return (
                    MarketRegime.RANGE_BOUND,
                    f"Range-bound: Wide 50-day range ({long_term_range_pct:.1f}%) "
                    f"but mid-range position or mixed momentum"
                )

        # Tight range = range-bound
        return (
            MarketRegime.RANGE_BOUND,
            f"Range-bound: Tight 50-day range ({long_term_range_pct:.1f}%), "
            f"VIX medium ({vix:.1f})"
        )

    def is_regime_valid(self, regime: MarketRegime, vix: float) -> bool:
        """
        ✅ FIX #6: Validate regime consistency with VIX

        Prevents false signals (e.g., "Range Bound" when VIX is spiking)
        """
        # High VIX + "Range Bound" = contradiction
        if vix > 20 and regime == MarketRegime.RANGE_BOUND:
            return False

        # Low VIX + "Trending" = probably false breakout
        if vix < 12 and regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            return False

        return True

    def get_regime_confidence(self) -> float:
        """
        ✅ FIX #6: Calculate confidence score (0-100%)

        Returns higher confidence with more history
        """
        if len(self.spot_history) < self.fast_lookback:
            return 0.0
        elif len(self.spot_history) < self.lookback_days:
            return 50.0
        else:
            # Full confidence with 50+ days of data
            return min(100.0, (len(self.spot_history) / self.lookback_days) * 100)

    def recommend_strategy(self, regime: MarketRegime, vix: float,
                          iv_rank: float) -> Tuple[StrategyType, str]:
        """
        Recommend strategy based on regime and VIX
        """
        # Validate regime first
        if not self.is_regime_valid(regime, vix):
            return (
                StrategyType.SKIP,
                f"Regime {regime.value} conflicts with VIX {vix:.1f}"
            )

        # Range-bound: Short strangle
        if regime == MarketRegime.RANGE_BOUND:
            if vix < self.vix_low_threshold:
                return (
                    StrategyType.SKIP,
                    "Range-bound but VIX too low (premium not worth risk)"
                )
            return (
                StrategyType.SHORT_STRANGLE,
                "Range-bound market: Use short strangle for theta decay"
            )

        # Low volatility: Iron condor (defined risk)
        if regime == MarketRegime.LOW_VOLATILITY:
            if iv_rank < 20:
                return (
                    StrategyType.SKIP,
                    "Low volatility + low IV rank: Skip entry"
                )
            return (
                StrategyType.IRON_CONDOR,
                "Low volatility: Use iron condor (defined risk)"
            )

        # High volatility: Skip (too risky)
        if regime == MarketRegime.HIGH_VOLATILITY:
            return (
                StrategyType.SKIP,
                f"High volatility (VIX {vix:.1f}): Too risky to enter"
            )

        # Trending up: Bullish put spread
        if regime == MarketRegime.TRENDING_UP:
            return (
                StrategyType.SHORT_PUT_SPREAD,
                "Trending up: Use short put spread (bullish income)"
            )

        # Trending down: Bearish call spread
        if regime == MarketRegime.TRENDING_DOWN:
            return (
                StrategyType.SHORT_CALL_SPREAD,
                "Trending down: Use short call spread (bearish income)"
            )

        return (StrategyType.SKIP, "Unknown regime")

    def reset_daily(self):
        """
        Reset daily state
        ✅ FIX #6: Preserves spot history (don't truncate daily data!)
        """
        # Only truncate VIX history to prevent indefinite growth
        if len(self.vix_history) > self.lookback_days * 2:
            self.vix_history = self.vix_history[-self.lookback_days * 2:]

    def get_statistics(self) -> dict:
        """
        ✅ FIX #6: Return regime detection statistics
        """
        if len(self.spot_history) < 2:
            return {
                'days_of_data': 0,
                'confidence': 0.0,
                'trend_range_pct': 0.0,
                'current_position': 0.0
            }

        long_term_prices = np.array(self.spot_history[-self.lookback_days:]) \
            if len(self.spot_history) >= self.lookback_days \
            else np.array(self.spot_history)

        long_term_high = np.max(long_term_prices)
        long_term_low = np.min(long_term_prices)
        current_spot = self.spot_history[-1]

        trend_range_pct = ((long_term_high - long_term_low) / long_term_low) * 100
        current_position = (current_spot - long_term_low) / (long_term_high - long_term_low) \
            if long_term_high > long_term_low else 0.5

        return {
            'days_of_data': len(self.spot_history),
            'confidence': self.get_regime_confidence(),
            'trend_range_pct': trend_range_pct,
            'current_position': current_position * 100,
            'range_high': long_term_high,
            'range_low': long_term_low
        }