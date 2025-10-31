"""
Portfolio Risk Manager for Short Strangle System
Manages portfolio-level risk through VIX shock detection, delta hedging, and daily loss limits.
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from .models import MarketData, Trade, Greeks


class RiskAction(Enum):
    """Risk management actions"""
    NONE = "NONE"
    REDUCE_SIZE = "REDUCE_SIZE"
    ADD_WINGS = "ADD_WINGS"
    PAUSE_ENTRIES = "PAUSE_ENTRIES"
    HEDGE_DELTA = "HEDGE_DELTA"
    DAILY_STOP = "DAILY_STOP"


@dataclass
class PortfolioState:
    """Portfolio risk state"""
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    daily_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    num_positions: int = 0
    short_vega_exposure: float = 0.0
    timestamp: Optional[datetime] = None


@dataclass
class RiskThresholds:
    """Risk management thresholds from config"""
    daily_max_loss_pct: float = 0.015  # 1.5% of capital
    delta_band_base: float = 15.0  # Base delta band
    vix_shock_abs: float = 4.0  # Absolute VIX move threshold
    vix_shock_roc_pct: float = 15.0  # VIX rate of change %
    short_vega_reduction_pct: float = 0.4  # 40% reduction on shock
    adjustment_cooldown_sec: float = 900  # 15 minutes
    hedge_preferred: str = "OPTIONS"  # OPTIONS or FUT
    hedge_delta_offset: float = 35.0  # Target delta for hedge options
    
    # VIX-scaled delta bands (tighter in higher VIX)
    delta_band_vix_map: Dict[float, float] = None
    
    def __post_init__(self):
        if self.delta_band_vix_map is None:
            self.delta_band_vix_map = {
                15.0: 15.0,
                20.0: 12.0,
                30.0: 10.0,
                999.0: 8.0  # High VIX
            }
    
    def get_delta_band(self, vix: float) -> float:
        """Get delta band based on VIX level"""
        for vix_threshold, band in sorted(self.delta_band_vix_map.items()):
            if vix < vix_threshold:
                return band
        return self.delta_band_base


class PortfolioRiskManager:
    """
    Portfolio-level risk manager for short strangle system.
    Manages VIX shocks, delta hedging, and daily loss limits.
    """
    
    def __init__(self, capital: float, thresholds: Optional[RiskThresholds] = None):
        self.capital = capital
        self.thresholds = thresholds or RiskThresholds()
        self.state = PortfolioState()
        
        # State tracking
        self.prev_vix: Optional[float] = None
        self.vix_open: Optional[float] = None  # VIX at market open
        self.last_adjustment_time: Optional[datetime] = None
        self.daily_stop_triggered: bool = False
        self.in_cooldown: bool = False
        
        # Delta hedging hysteresis
        self.last_hedge_time: Optional[datetime] = None
        self.hedge_position_count: int = 0
        
        logging.info(
            f"Portfolio Risk Manager initialized with capital=₹{capital:,.0f}, "
            f"daily_max_loss={self.thresholds.daily_max_loss_pct*100:.1f}%"
        )
    
    def update_state(self, market_data: MarketData, active_trades: Dict[str, Trade]) -> PortfolioState:
        """
        Update portfolio state with current market data and trades.
        Computes portfolio Greeks and P&L aggregates.
        """
        # Reset state
        self.state = PortfolioState(timestamp=market_data.timestamp)
        
        if not active_trades:
            return self.state
        
        # Aggregate Greeks and P&L
        for trade in active_trades.values():
            # Skip if no valid price
            if trade.current_price <= 0:
                continue
            
            # Aggregate Greeks
            if trade.greeks:
                # For short positions, negate the Greeks
                multiplier = -1.0 if trade.direction.value == "SELL" else 1.0
                contracts = trade.qty * trade.lot_size
                
                self.state.net_delta += trade.greeks.delta * multiplier * contracts
                self.state.net_gamma += trade.greeks.gamma * multiplier * contracts
                self.state.net_theta += trade.greeks.theta * multiplier * contracts
                self.state.net_vega += trade.greeks.vega * multiplier * contracts
                
                # Track short vega exposure separately
                if trade.direction.value == "SELL":
                    self.state.short_vega_exposure += abs(trade.greeks.vega * contracts)
            
            # Aggregate P&L
            pnl = trade.get_pnl()
            self.state.unrealized_pnl += pnl
            
            self.state.num_positions += 1
        
        # Set daily P&L (unrealized for now, realized will be added by trade manager)
        self.state.daily_pnl = self.state.unrealized_pnl
        
        # Track VIX for shock detection
        if self.vix_open is None:
            self.vix_open = market_data.india_vix
        if self.prev_vix is None:
            self.prev_vix = market_data.india_vix
        
        logging.debug(
            f"Portfolio state: Δ={self.state.net_delta:.1f}, "
            f"Γ={self.state.net_gamma:.4f}, Θ={self.state.net_theta:.2f}, "
            f"ν={self.state.net_vega:.2f}, P&L=₹{self.state.daily_pnl:,.0f}"
        )
        
        return self.state
    
    def check_vix_shock(self, current_vix: float) -> Tuple[bool, List[RiskAction], str]:
        """
        Check for VIX shock conditions.
        Returns: (is_shock, actions, reason)
        """
        if self.prev_vix is None or self.vix_open is None:
            self.prev_vix = current_vix
            return False, [], ""
        
        # Calculate VIX changes
        vix_change_abs = current_vix - self.prev_vix
        vix_change_pct = (vix_change_abs / self.prev_vix) * 100 if self.prev_vix > 0 else 0
        vix_change_from_open = current_vix - self.vix_open
        vix_change_from_open_pct = (vix_change_from_open / self.vix_open) * 100 if self.vix_open > 0 else 0
        
        # Check thresholds
        is_abs_shock = abs(vix_change_abs) >= self.thresholds.vix_shock_abs
        is_roc_shock = abs(vix_change_pct) >= self.thresholds.vix_shock_roc_pct
        is_intraday_shock = abs(vix_change_from_open_pct) >= self.thresholds.vix_shock_roc_pct
        
        actions = []
        reasons = []
        
        if is_abs_shock or is_roc_shock or is_intraday_shock:
            # VIX shock detected
            actions.append(RiskAction.REDUCE_SIZE)
            actions.append(RiskAction.ADD_WINGS)
            actions.append(RiskAction.PAUSE_ENTRIES)
            
            if is_abs_shock:
                reasons.append(f"VIX moved {vix_change_abs:+.1f} pts")
            if is_roc_shock:
                reasons.append(f"VIX changed {vix_change_pct:+.1f}% from prev")
            if is_intraday_shock:
                reasons.append(f"VIX changed {vix_change_from_open_pct:+.1f}% from open")
            
            reason = " | ".join(reasons)
            logging.warning(
                f"⚠️ VIX SHOCK DETECTED: Current={current_vix:.2f}, "
                f"Prev={self.prev_vix:.2f}, Open={self.vix_open:.2f} | {reason}"
            )
            
            # Update prev_vix
            self.prev_vix = current_vix
            
            return True, actions, reason
        
        # Update prev_vix
        self.prev_vix = current_vix
        
        return False, [], ""
    
    def check_delta_bands(self, vix: float) -> Tuple[bool, RiskAction, float, str]:
        """
        Check if net delta is outside hysteresis bands.
        Returns: (needs_hedge, action, target_delta, reason)
        """
        net_delta = self.state.net_delta
        
        # Get VIX-adjusted delta bands
        delta_band_high = self.thresholds.get_delta_band(vix)
        delta_band_low = delta_band_high * 0.6  # Hysteresis: 60% of high band
        
        # Check if outside high band (need to hedge)
        if abs(net_delta) > delta_band_high:
            # Target is to return within low band
            target_delta = delta_band_low if net_delta > 0 else -delta_band_low
            
            reason = (
                f"Net delta {net_delta:.1f} exceeds band ±{delta_band_high:.1f} "
                f"(VIX={vix:.1f}), target={target_delta:.1f}"
            )
            
            logging.warning(f"⚠️ DELTA HEDGE NEEDED: {reason}")
            
            return True, RiskAction.HEDGE_DELTA, target_delta, reason
        
        return False, RiskAction.NONE, 0.0, ""
    
    def check_daily_stop(self, realized_pnl: float = 0.0) -> Tuple[bool, str]:
        """
        Check if daily loss limit breached.
        Returns: (is_stop, reason)
        """
        # Combine realized and unrealized P&L
        total_daily_pnl = realized_pnl + self.state.unrealized_pnl
        
        # Calculate loss threshold
        loss_threshold = -self.capital * self.thresholds.daily_max_loss_pct
        
        if total_daily_pnl <= loss_threshold:
            reason = (
                f"Daily P&L ₹{total_daily_pnl:,.0f} breached limit "
                f"₹{loss_threshold:,.0f} ({self.thresholds.daily_max_loss_pct*100:.1f}% of capital)"
            )
            
            logging.critical(f"🛑 DAILY STOP TRIGGERED: {reason}")
            
            self.daily_stop_triggered = True
            return True, reason
        
        return False, ""
    
    def regime_adjustments(self, vix: float, iv_rank: float) -> Dict[str, float]:
        """
        Return parameter multipliers for roll/stop triggers based on regime.
        High VIX = stricter stops, wider strikes, smaller size.
        """
        adjustments = {
            'position_size_multiplier': 1.0,
            'strike_distance_multiplier': 1.0,
            'stop_loss_multiplier': 1.0,
            'roll_trigger_multiplier': 1.0,
        }
        
        # VIX-based regime
        if vix < 15:
            # Low VIX: normal
            adjustments['position_size_multiplier'] = 1.0
            adjustments['strike_distance_multiplier'] = 1.0
        elif vix < 20:
            # Elevated VIX: slightly defensive
            adjustments['position_size_multiplier'] = 0.75
            adjustments['strike_distance_multiplier'] = 1.1
            adjustments['stop_loss_multiplier'] = 0.9  # Tighter stops
        elif vix < 30:
            # High VIX: defensive
            adjustments['position_size_multiplier'] = 0.5
            adjustments['strike_distance_multiplier'] = 1.2
            adjustments['stop_loss_multiplier'] = 0.8
            adjustments['roll_trigger_multiplier'] = 0.85  # Roll earlier
        else:
            # Crisis VIX: very defensive
            adjustments['position_size_multiplier'] = 0.25
            adjustments['strike_distance_multiplier'] = 1.4
            adjustments['stop_loss_multiplier'] = 0.7
            adjustments['roll_trigger_multiplier'] = 0.7
        
        # IV rank adjustment
        if iv_rank < 20:
            # Low IV rank: reduce size
            adjustments['position_size_multiplier'] *= 0.75
        
        logging.debug(
            f"Regime adjustments: VIX={vix:.1f}, IV_rank={iv_rank:.1f} -> "
            f"size={adjustments['position_size_multiplier']:.2f}x, "
            f"stop={adjustments['stop_loss_multiplier']:.2f}x"
        )
        
        return adjustments
    
    def is_in_cooldown(self) -> bool:
        """Check if in adjustment cooldown period"""
        if self.last_adjustment_time is None:
            return False
        
        time_since_adjustment = (
            datetime.now() - self.last_adjustment_time
        ).total_seconds()
        
        if time_since_adjustment < self.thresholds.adjustment_cooldown_sec:
            self.in_cooldown = True
            return True
        
        self.in_cooldown = False
        return False
    
    def set_adjustment_cooldown(self):
        """Set cooldown after making adjustment"""
        self.last_adjustment_time = datetime.now()
        self.in_cooldown = True
        logging.info(
            f"Adjustment cooldown set for {self.thresholds.adjustment_cooldown_sec}s"
        )
    
    def reset_daily(self):
        """Reset daily state at start of new day"""
        self.vix_open = None
        self.prev_vix = None
        self.daily_stop_triggered = False
        self.in_cooldown = False
        self.last_adjustment_time = None
        self.state = PortfolioState()
        logging.info("Risk manager daily state reset")
    
    def get_hedge_sizing(self, current_delta: float, target_delta: float) -> Tuple[str, int, float]:
        """
        Calculate hedge sizing to move delta from current to target.
        Returns: (option_type, num_lots, target_option_delta)
        """
        delta_to_hedge = current_delta - target_delta
        
        # Determine option type
        if delta_to_hedge > 0:
            # Portfolio is long delta, buy puts to hedge
            option_type = "PE"
            target_option_delta = -self.thresholds.hedge_delta_offset
        else:
            # Portfolio is short delta, buy calls to hedge
            option_type = "CE"
            target_option_delta = self.thresholds.hedge_delta_offset
        
        # Calculate number of contracts needed
        # delta_to_hedge = num_contracts * target_option_delta
        num_contracts_needed = abs(delta_to_hedge / target_option_delta)
        
        # Convert to lots (NIFTY lot size = 75)
        num_lots = max(1, int(num_contracts_needed / 75))
        
        logging.debug(
            f"Hedge sizing: current_Δ={current_delta:.1f}, target_Δ={target_delta:.1f}, "
            f"hedge_Δ={delta_to_hedge:.1f} -> {num_lots} lots of {option_type} "
            f"(option_Δ={target_option_delta:.1f})"
        )
        
        return option_type, num_lots, target_option_delta
    
    def calculate_wing_strikes(self, base_strike: float, option_type: str, 
                              spread_width: float = 200.0) -> float:
        """
        Calculate wing strike for converting to defined risk.
        Returns: wing_strike
        """
        if option_type == "CE":
            # Buy CE at higher strike
            wing_strike = base_strike + spread_width
        else:
            # Buy PE at lower strike
            wing_strike = base_strike - spread_width
        
        # Round to nearest 50
        wing_strike = round(wing_strike / 50) * 50
        
        return wing_strike
