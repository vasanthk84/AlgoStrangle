"""
Market Regime Detector for Adaptive Options Strategy
Save as: strangle/regime_detector.py
"""

from typing import Tuple, List, Optional
from datetime import datetime, timedelta
from enum import Enum
import numpy as np

# Note: Config is not imported here to keep the module self-contained,
# lookback days and thresholds are passed or set internally.


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
    SHORT_PUT_SPREAD = "SHORT_PUT_SPREAD"  # Bullish income
    SHORT_CALL_SPREAD = "SHORT_CALL_SPREAD"  # Bearish income
    IRON_CONDOR = "IRON_CONDOR"
    SKIP = "SKIP"


class RegimeDetector:
    """
    Detects market regime and recommends appropriate strategy
    """

    def __init__(self, lookback_days: int = 20):
        self.lookback_days = lookback_days
        self.spot_history: List[float] = []
        self.vix_history: List[float] = []

        # Configurable thresholds (defaults used if Config is not available)
        self.trend_threshold_pct = 4.0  # 4% move in lookback = trending
        self.range_position_lower = 0.30  # Bottom 30% of range
        self.range_position_upper = 0.70  # Top 70% of range
        self.vix_threshold = 12.0
        self.vix_high_threshold = 18.0
        self.vix_low_threshold = 8.0

    def detect_regime(self, spot: float, vix: float, nifty_open: float, nifty_high: float, nifty_low: float) -> Tuple[MarketRegime, str]:
        """
        Detects the current market regime based on VIX and spot price movement.

        Args:
            spot: Current Nifty spot price.
            vix: Current India VIX level.
            nifty_open: Nifty daily open.
            nifty_high: Nifty daily high.
            nifty_low: Nifty daily low.

        Returns:
            A tuple of (MarketRegime, reason_string).
        """

        # 1. Volatility Regime Check
        if vix >= self.vix_high_threshold:
            return MarketRegime.HIGH_VOLATILITY, f"VIX ({vix:.1f}) is above HIGH threshold ({self.vix_high_threshold})."

        if vix <= self.vix_low_threshold:
            return MarketRegime.LOW_VOLATILITY, f"VIX ({vix:.1f}) is below LOW threshold ({self.vix_low_threshold})."

        # 2. Trend Regime Check (Requires sufficient history)
        if len(self.spot_history) < self.lookback_days:
            return MarketRegime.RANGE_BOUND, "Insufficient spot history for trend detection."

        lookback_prices = np.array(self.spot_history[-self.lookback_days:])
        highest = np.max(lookback_prices)
        lowest = np.min(lookback_prices)

        # Trend check: 4% move from min to max in lookback period
        trend_range_pct = ((highest - lowest) / lowest) * 100

        # Current price position within the range (0% at low, 100% at high)
        if highest > lowest:
            range_position = (spot - lowest) / (highest - lowest)
        else:
            range_position = 0.5 # Default to middle if no movement

        if trend_range_pct >= self.trend_threshold_pct:
            # Trending regime check
            if range_position >= self.range_position_upper:
                return MarketRegime.TRENDING_UP, f"Trending Up: Spot near high of {self.lookback_days}-day range ({highest:.0f}). Range: {trend_range_pct:.1f}%."
            elif range_position <= self.range_position_lower:
                return MarketRegime.TRENDING_DOWN, f"Trending Down: Spot near low of {self.lookback_days}-day range ({lowest:.0f}). Range: {trend_range_pct:.1f}%."
            else:
                # If trending but spot is in the middle of the range, call it range bound for safety
                return MarketRegime.RANGE_BOUND, f"Range-bound: Trend range is high ({trend_range_pct:.1f}%) but spot is mid-range."

        # 3. Default Regime
        return MarketRegime.RANGE_BOUND, f"Range-bound: Trend range is low ({trend_range_pct:.1f}%) and VIX is medium."

    def recommend_strategy(self, regime: MarketRegime, vix: float, iv_rank: float) -> Tuple[StrategyType, str]:
        """
        Recommends the strategy based on the detected market regime.
        (This method is not used in the current strategy.py logic but is included for completeness.)
        """
        if regime == MarketRegime.RANGE_BOUND:
            return StrategyType.SHORT_STRANGLE, "Range-bound: Use Short Strangle for theta decay."

        if regime == MarketRegime.LOW_VOLATILITY:
            # Low VIX suggests low premium, high risk of sudden spike. Skip or use Iron Condor.
            if iv_rank < 20: # Example low rank threshold
                return StrategyType.SKIP, "Low Volatility/Low IV Rank: Skipping entry."
            return StrategyType.IRON_CONDOR, "Low Volatility/Medium IV Rank: Use Iron Condor (defined risk)."

        if regime == MarketRegime.HIGH_VOLATILITY:
            # High VIX suggests high premium, but high risk. Skip or use Iron Condor.
            return StrategyType.SKIP, "High Volatility: Skipping entry due to high risk."

        if regime == MarketRegime.TRENDING_UP:
            # Bullish trend: Sell OTM Put Spread
            return StrategyType.SHORT_PUT_SPREAD, "Trending Up: Use Short Put Spread (Bullish income)."

        if regime == MarketRegime.TRENDING_DOWN:
            # Bearish trend: Sell OTM Call Spread
            return StrategyType.SHORT_CALL_SPREAD, "Trending Down: Use Short Call Spread (Bearish income)."

        return StrategyType.SKIP, "Unknown regime. Skipping."

    def reset_daily(self):
        """
        Resets any daily state, ensuring spot/vix history is limited to the lookback period.
        This fixes the AttributeError.
        """
        # Truncate history to prevent indefinite growth in backtest
        if len(self.spot_history) > self.lookback_days * 2: # Keep more than necessary to avoid errors, but limit size
            self.spot_history = self.spot_history[-self.lookback_days * 2:]

        if len(self.vix_history) > self.lookback_days * 2:
            self.vix_history = self.vix_history[-self.lookback_days * 2:]