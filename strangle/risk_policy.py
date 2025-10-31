"""
Portfolio-Level Risk Manager for Short Strangle System

Monitors and controls portfolio-wide risk through:
- VIX spike detection and response
- Portfolio delta monitoring and hedging
- Daily loss kill-switch
- Regime-aware parameter adjustments
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

# Import Direction at module level to avoid repeated imports
from .models import Direction


@dataclass
class PortfolioState:
    """Portfolio state snapshot"""
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    daily_pnl: float = 0.0
    num_active_trades: int = 0
    timestamp: Optional[datetime] = None


class RiskAction(Enum):
    """Risk management actions"""
    NONE = "NONE"
    VIX_SHOCK_REDUCE_VEGA = "VIX_SHOCK_REDUCE_VEGA"
    VIX_SHOCK_ADD_WINGS = "VIX_SHOCK_ADD_WINGS"
    VIX_SHOCK_PAUSE_ENTRIES = "VIX_SHOCK_PAUSE_ENTRIES"
    DELTA_HEDGE_BUY_CE = "DELTA_HEDGE_BUY_CE"
    DELTA_HEDGE_BUY_PE = "DELTA_HEDGE_BUY_PE"
    DAILY_STOP_CLOSE_ALL = "DAILY_STOP_CLOSE_ALL"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"


@dataclass
class RiskResponse:
    """Response from risk checks"""
    action: RiskAction
    reason: str
    parameters: Dict[str, Any]
    timestamp: datetime


class PortfolioRiskManager:
    """
    Manages portfolio-level risk for the short strangle system
    """

    def __init__(self, config):
        self.config = config
        self.portfolio_state = PortfolioState()
        self.last_adjustment_time: Optional[datetime] = None
        self.daily_stop_triggered = False
        self.vix_shock_detected = False
        self.last_vix: Optional[float] = None
        self.vix_at_open: Optional[float] = None
        self.adjustment_cooldown_until: Optional[datetime] = None

        # Configuration parameters (with defaults)
        self.daily_max_loss_pct = getattr(config, 'DAILY_MAX_LOSS_PCT', 0.015)
        self.delta_band_base = getattr(config, 'DELTA_BAND_BASE', 15.0)
        self.vix_shock_abs = getattr(config, 'VIX_SHOCK_ABS', 4.0)
        self.vix_shock_roc_pct = getattr(config, 'VIX_SHOCK_ROC_PCT', 15.0)
        self.short_vega_reduction_pct = getattr(config, 'SHORT_VEGA_REDUCTION_PCT', 0.4)
        self.adjustment_cooldown_sec = getattr(config, 'ADJUSTMENT_COOLDOWN_SEC', 900)
        self.hedge_preferred = getattr(config, 'HEDGE_PREFERRED', 'OPTIONS')
        self.capital = getattr(config, 'CAPITAL', 300000)

        # Delta band configuration
        self.delta_band_tight_vix = getattr(config, 'DELTA_BAND_TIGHT_VIX', {
            15: 15,
            20: 12,
            30: 10,
            999: 8
        })

        logging.info(
            f"PortfolioRiskManager initialized: "
            f"Daily max loss: {self.daily_max_loss_pct:.1%}, "
            f"VIX shock: {self.vix_shock_abs} pts / {self.vix_shock_roc_pct}%, "
            f"Cooldown: {self.adjustment_cooldown_sec}s"
        )

    def update_state(self, market_data, active_trades: Dict) -> PortfolioState:
        """
        Update portfolio state from market data and active trades
        
        Args:
            market_data: Current market data (MarketData object)
            active_trades: Dict of trade_id -> Trade objects
            
        Returns:
            Updated PortfolioState
        """
        # Reset state
        self.portfolio_state.net_delta = 0.0
        self.portfolio_state.net_gamma = 0.0
        self.portfolio_state.net_theta = 0.0
        self.portfolio_state.net_vega = 0.0
        self.portfolio_state.unrealized_pnl = 0.0
        self.portfolio_state.num_active_trades = len(active_trades)
        self.portfolio_state.timestamp = market_data.timestamp

        # Aggregate Greeks and P&L from all active trades
        for trade in active_trades.values():
            contracts = trade.qty * trade.lot_size

            # Handle missing Greeks - compute on the fly if needed
            if trade.greeks is None:
                logging.warning(
                    f"Missing Greeks for {trade.symbol}, computing..."
                )
                # Greeks will be computed by trade manager, skip for now
                continue

            # Aggregate Greeks (account for direction)
            multiplier = -1 if trade.direction == Direction.SELL else 1

            self.portfolio_state.net_delta += trade.greeks.delta * contracts * multiplier
            self.portfolio_state.net_gamma += trade.greeks.gamma * contracts * multiplier
            self.portfolio_state.net_theta += trade.greeks.theta * contracts * multiplier
            self.portfolio_state.net_vega += trade.greeks.vega * contracts * multiplier

            # Aggregate P&L
            self.portfolio_state.unrealized_pnl += trade.get_pnl()

        logging.debug(
            f"Portfolio state: ΣΔ={self.portfolio_state.net_delta:.0f}, "
            f"ΣΓ={self.portfolio_state.net_gamma:.4f}, "
            f"ΣΘ={self.portfolio_state.net_theta:.2f}, "
            f"Σν={self.portfolio_state.net_vega:.2f}, "
            f"Unrealized P&L=₹{self.portfolio_state.unrealized_pnl:,.2f}"
        )

        return self.portfolio_state

    def check_vix_shock(self, current_vix: float) -> Optional[RiskResponse]:
        """
        Check for VIX shock conditions
        
        Args:
            current_vix: Current VIX value
            
        Returns:
            RiskResponse if shock detected, None otherwise
        """
        if current_vix <= 0:
            return None

        # Store VIX at open (for intraday ROC check)
        if self.vix_at_open is None:
            self.vix_at_open = current_vix
            logging.info(f"VIX at open: {self.vix_at_open:.2f}")

        # Check absolute VIX spike from previous tick
        if self.last_vix is not None:
            vix_change = current_vix - self.last_vix
            vix_roc_pct = (vix_change / self.last_vix) * 100 if self.last_vix > 0 else 0

            # Check intraday ROC from open
            vix_roc_from_open = (
                ((current_vix - self.vix_at_open) / self.vix_at_open) * 100
                if self.vix_at_open > 0 else 0
            )

            # Detect shock
            abs_shock = vix_change >= self.vix_shock_abs
            roc_shock = vix_roc_from_open >= self.vix_shock_roc_pct

            if (abs_shock or roc_shock) and not self.vix_shock_detected:
                self.vix_shock_detected = True
                
                reason = f"VIX shock detected: "
                if abs_shock:
                    reason += f"abs change +{vix_change:.2f} pts (>= {self.vix_shock_abs})"
                if roc_shock:
                    reason += f" / intraday ROC +{vix_roc_from_open:.1f}% (>= {self.vix_shock_roc_pct}%)"

                logging.warning(reason)

                return RiskResponse(
                    action=RiskAction.VIX_SHOCK_REDUCE_VEGA,
                    reason=reason,
                    parameters={
                        'prev_vix': self.last_vix,
                        'current_vix': current_vix,
                        'vix_change': vix_change,
                        'vix_roc_pct': vix_roc_from_open,
                        'reduction_pct': self.short_vega_reduction_pct
                    },
                    timestamp=datetime.now()
                )

        self.last_vix = current_vix
        return None

    def check_delta_bands(self, vix: float) -> Optional[RiskResponse]:
        """
        Check if portfolio net delta is outside acceptable bands
        
        Args:
            vix: Current VIX for regime-aware bands
            
        Returns:
            RiskResponse if hedge needed, None otherwise
        """
        if self.portfolio_state.net_delta == 0:
            return None

        # Get VIX-adjusted delta bands
        high_band = self._get_delta_band_for_vix(vix)
        low_band = high_band * 0.6  # Hysteresis: exit at 60% of trigger

        net_delta = self.portfolio_state.net_delta
        abs_net_delta = abs(net_delta)

        # Check if outside high band (trigger hedge)
        if abs_net_delta > high_band:
            # Determine hedge direction
            if net_delta > 0:
                # Portfolio too long delta -> buy puts
                action = RiskAction.DELTA_HEDGE_BUY_PE
                reason = f"Portfolio net delta {net_delta:.0f} > {high_band:.0f} (long bias)"
            else:
                # Portfolio too short delta -> buy calls
                action = RiskAction.DELTA_HEDGE_BUY_CE
                reason = f"Portfolio net delta {net_delta:.0f} < -{high_band:.0f} (short bias)"

            logging.warning(reason)

            return RiskResponse(
                action=action,
                reason=reason,
                parameters={
                    'net_delta': net_delta,
                    'high_band': high_band,
                    'low_band': low_band,
                    'target_delta': net_delta * 0.4  # Reduce by 60%
                },
                timestamp=datetime.now()
            )

        return None

    def check_daily_stop(self, daily_pnl: float) -> Optional[RiskResponse]:
        """
        Check if daily loss threshold breached
        
        Args:
            daily_pnl: Current daily P&L (realized + unrealized)
            
        Returns:
            RiskResponse if stop triggered, None otherwise
        """
        if self.daily_stop_triggered:
            return None

        max_loss = self.capital * self.daily_max_loss_pct
        
        if daily_pnl <= -max_loss:
            self.daily_stop_triggered = True
            
            reason = (
                f"Daily loss kill-switch triggered: "
                f"P&L ₹{daily_pnl:,.2f} <= -₹{max_loss:,.2f} "
                f"({self.daily_max_loss_pct:.1%} of capital)"
            )
            
            logging.critical(reason)
            
            return RiskResponse(
                action=RiskAction.DAILY_STOP_CLOSE_ALL,
                reason=reason,
                parameters={
                    'daily_pnl': daily_pnl,
                    'threshold': -max_loss,
                    'capital': self.capital
                },
                timestamp=datetime.now()
            )

        return None

    def regime_adjustments(self, vix: float, iv_rank: float) -> Dict[str, float]:
        """
        Return parameter multipliers based on VIX regime
        
        Args:
            vix: Current VIX
            iv_rank: IV rank (0-100)
            
        Returns:
            Dict with multipliers for various parameters
        """
        adjustments = {
            'position_size': 1.0,
            'roll_delta_trigger': 1.0,
            'stop_loss_multiple': 1.0,
            'otm_distance': 1.0
        }

        # VIX-based regime adjustments
        if vix < 15:
            # Low VIX - normal parameters
            adjustments['position_size'] = 1.0
            adjustments['roll_delta_trigger'] = 1.0
            adjustments['stop_loss_multiple'] = 1.0
            adjustments['otm_distance'] = 1.0
        elif vix < 20:
            # Elevated VIX - slight caution
            adjustments['position_size'] = 0.8
            adjustments['roll_delta_trigger'] = 0.9  # Roll earlier
            adjustments['stop_loss_multiple'] = 0.9  # Tighter stops
            adjustments['otm_distance'] = 1.1  # Further OTM
        elif vix < 25:
            # High VIX - reduce exposure
            adjustments['position_size'] = 0.6
            adjustments['roll_delta_trigger'] = 0.8
            adjustments['stop_loss_multiple'] = 0.8
            adjustments['otm_distance'] = 1.2
        else:
            # Very high VIX - minimal exposure
            adjustments['position_size'] = 0.3
            adjustments['roll_delta_trigger'] = 0.7
            adjustments['stop_loss_multiple'] = 0.7
            adjustments['otm_distance'] = 1.3

        # IV rank adjustments (favor higher IV)
        if iv_rank > 70:
            adjustments['position_size'] *= 1.1  # Favorable conditions
        elif iv_rank < 30:
            adjustments['position_size'] *= 0.8  # Less favorable

        logging.debug(
            f"Regime adjustments for VIX={vix:.1f}, IVR={iv_rank:.0f}: {adjustments}"
        )

        return adjustments

    def is_in_cooldown(self) -> bool:
        """Check if risk manager is in cooldown period"""
        if self.adjustment_cooldown_until is None:
            return False
        
        now = datetime.now()
        if now < self.adjustment_cooldown_until:
            remaining = (self.adjustment_cooldown_until - now).total_seconds()
            logging.debug(f"In cooldown: {remaining:.0f}s remaining")
            return True
        
        return False

    def set_cooldown(self):
        """Set cooldown period after adjustment"""
        self.adjustment_cooldown_until = (
            datetime.now() + timedelta(seconds=self.adjustment_cooldown_sec)
        )
        logging.info(
            f"Cooldown set until {self.adjustment_cooldown_until.strftime('%H:%M:%S')}"
        )

    def reset_daily(self):
        """Reset daily state"""
        self.daily_stop_triggered = False
        self.vix_shock_detected = False
        self.last_vix = None
        self.vix_at_open = None
        self.adjustment_cooldown_until = None
        self.last_adjustment_time = None
        logging.info("Risk manager daily state reset")

    def _get_delta_band_for_vix(self, vix: float) -> float:
        """Get delta band threshold based on current VIX"""
        # Find appropriate band from config
        for vix_threshold in sorted(self.delta_band_tight_vix.keys()):
            if vix < vix_threshold:
                band = self.delta_band_tight_vix[vix_threshold]
                logging.debug(f"Delta band for VIX {vix:.1f}: {band}")
                return band
        
        # Default to base band
        return self.delta_band_base

    def get_vega_reduction_target(self, current_net_vega: float) -> float:
        """
        Calculate target net vega after reduction
        
        Args:
            current_net_vega: Current portfolio net vega
            
        Returns:
            Target net vega (more positive = less short vega)
        """
        # If net vega is negative (short vega), reduce it by the configured percentage
        if current_net_vega < 0:
            reduction = abs(current_net_vega) * self.short_vega_reduction_pct
            target = current_net_vega + reduction  # Makes it less negative
            logging.info(
                f"Vega reduction: current={current_net_vega:.2f}, "
                f"target={target:.2f} (reduction={reduction:.2f})"
            )
            return target
        
        return current_net_vega

    def get_status_summary(self) -> str:
        """Get human-readable status summary"""
        status_lines = [
            f"Portfolio State:",
            f"  Net Delta: {self.portfolio_state.net_delta:.0f}",
            f"  Net Vega: {self.portfolio_state.net_vega:.2f}",
            f"  Daily P&L: ₹{self.portfolio_state.daily_pnl:,.2f}",
            f"  Active Trades: {self.portfolio_state.num_active_trades}",
            f"",
            f"Risk Status:",
            f"  Daily Stop: {'TRIGGERED' if self.daily_stop_triggered else 'OK'}",
            f"  VIX Shock: {'DETECTED' if self.vix_shock_detected else 'OK'}",
            f"  Cooldown: {'YES' if self.is_in_cooldown() else 'NO'}",
        ]
        return "\n".join(status_lines)
