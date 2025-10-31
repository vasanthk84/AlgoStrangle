"""
Unit tests for Portfolio Risk Manager
"""

import pytest
from datetime import datetime, timedelta
from strangle.risk_policy import (
    PortfolioRiskManager,
    RiskThresholds,
    RiskAction,
    PortfolioState
)
from strangle.models import Trade, Direction, Greeks, MarketData


class TestVixShockDetection:
    """Tests for VIX shock detection"""
    
    def test_vix_shock_absolute_threshold(self):
        """Test VIX shock when absolute threshold breached"""
        thresholds = RiskThresholds(vix_shock_abs=4.0, vix_shock_roc_pct=15.0)
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Initialize VIX
        manager.prev_vix = 15.0
        manager.vix_open = 15.0
        
        # Simulate VIX spike of 5 points
        is_shock, actions, reason = manager.check_vix_shock(20.0)
        
        assert is_shock is True
        assert RiskAction.REDUCE_SIZE in actions
        assert RiskAction.ADD_WINGS in actions
        assert RiskAction.PAUSE_ENTRIES in actions
        assert "5.0 pts" in reason
    
    def test_vix_shock_roc_threshold(self):
        """Test VIX shock when rate of change threshold breached"""
        thresholds = RiskThresholds(vix_shock_abs=4.0, vix_shock_roc_pct=15.0)
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Initialize VIX
        manager.prev_vix = 15.0
        manager.vix_open = 15.0
        
        # Simulate VIX jump of 20% (15 -> 18)
        is_shock, actions, reason = manager.check_vix_shock(18.0)
        
        assert is_shock is True
        assert "20.0%" in reason
    
    def test_no_vix_shock_below_threshold(self):
        """Test no shock when VIX change is below threshold"""
        thresholds = RiskThresholds(vix_shock_abs=4.0, vix_shock_roc_pct=15.0)
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Initialize VIX
        manager.prev_vix = 15.0
        manager.vix_open = 15.0
        
        # Small VIX change (2 pts, ~13%)
        is_shock, actions, reason = manager.check_vix_shock(17.0)
        
        assert is_shock is False
        assert len(actions) == 0


class TestDeltaBands:
    """Tests for delta band monitoring with hysteresis"""
    
    def test_delta_outside_high_band(self):
        """Test hedge trigger when delta exceeds high band"""
        thresholds = RiskThresholds(delta_band_base=15.0)
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Set portfolio state with high delta
        manager.state.net_delta = 20.0
        
        # VIX = 12 -> band = 15
        needs_hedge, action, target_delta, reason = manager.check_delta_bands(vix=12.0)
        
        assert needs_hedge is True
        assert action == RiskAction.HEDGE_DELTA
        assert target_delta == pytest.approx(9.0, rel=0.1)  # 60% of 15 = 9
        assert "20.0" in reason
    
    def test_delta_within_band(self):
        """Test no hedge when delta within band"""
        thresholds = RiskThresholds(delta_band_base=15.0)
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Set portfolio state with acceptable delta
        manager.state.net_delta = 10.0
        
        needs_hedge, action, target_delta, reason = manager.check_delta_bands(vix=12.0)
        
        assert needs_hedge is False
        assert action == RiskAction.NONE
    
    def test_delta_bands_tighter_in_high_vix(self):
        """Test delta bands tighten in high VIX"""
        thresholds = RiskThresholds()
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Same delta, but higher VIX
        manager.state.net_delta = 12.0
        
        # Low VIX: band = 15, so 12 is OK
        needs_hedge_low, _, _, _ = manager.check_delta_bands(vix=12.0)
        assert needs_hedge_low is False
        
        # High VIX: band = 10, so 12 exceeds
        needs_hedge_high, _, _, _ = manager.check_delta_bands(vix=25.0)
        assert needs_hedge_high is True


class TestDailyKillSwitch:
    """Tests for daily loss kill-switch"""
    
    def test_daily_stop_triggered(self):
        """Test stop triggered when loss exceeds threshold"""
        thresholds = RiskThresholds(daily_max_loss_pct=0.015)  # 1.5%
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Simulate loss of -5000 (1.67% of 300k)
        manager.state.unrealized_pnl = -5000
        
        is_stop, reason = manager.check_daily_stop(realized_pnl=0)
        
        assert is_stop is True
        assert "-5,000" in reason or "-5000" in reason
        assert manager.daily_stop_triggered is True
    
    def test_daily_stop_not_triggered_below_threshold(self):
        """Test no stop when loss below threshold"""
        thresholds = RiskThresholds(daily_max_loss_pct=0.015)  # 1.5%
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Simulate loss of -3000 (1% of 300k)
        manager.state.unrealized_pnl = -3000
        
        is_stop, reason = manager.check_daily_stop(realized_pnl=0)
        
        assert is_stop is False
        assert manager.daily_stop_triggered is False
    
    def test_daily_stop_with_combined_pnl(self):
        """Test stop with both realized and unrealized P&L"""
        thresholds = RiskThresholds(daily_max_loss_pct=0.015)  # 1.5%
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        # Combined loss exceeds threshold
        manager.state.unrealized_pnl = -3000
        realized_pnl = -2500
        
        is_stop, reason = manager.check_daily_stop(realized_pnl=realized_pnl)
        
        assert is_stop is True


class TestRegimeAdjustments:
    """Tests for regime-based parameter adjustments"""
    
    def test_low_vix_regime(self):
        """Test adjustments in low VIX regime"""
        manager = PortfolioRiskManager(capital=300000)
        
        adjustments = manager.regime_adjustments(vix=12.0, iv_rank=50.0)
        
        assert adjustments['position_size_multiplier'] == 1.0
        assert adjustments['strike_distance_multiplier'] == 1.0
    
    def test_high_vix_regime(self):
        """Test adjustments in high VIX regime"""
        manager = PortfolioRiskManager(capital=300000)
        
        adjustments = manager.regime_adjustments(vix=25.0, iv_rank=80.0)
        
        assert adjustments['position_size_multiplier'] == 0.5
        assert adjustments['strike_distance_multiplier'] > 1.0
        assert adjustments['stop_loss_multiplier'] < 1.0
    
    def test_crisis_vix_regime(self):
        """Test adjustments in crisis VIX regime"""
        manager = PortfolioRiskManager(capital=300000)
        
        adjustments = manager.regime_adjustments(vix=35.0, iv_rank=95.0)
        
        assert adjustments['position_size_multiplier'] == 0.25
        assert adjustments['roll_trigger_multiplier'] < 1.0


class TestCooldownMechanism:
    """Tests for adjustment cooldown"""
    
    def test_cooldown_active_after_adjustment(self):
        """Test cooldown is active after setting"""
        manager = PortfolioRiskManager(capital=300000)
        
        manager.set_adjustment_cooldown()
        
        assert manager.is_in_cooldown() is True
        assert manager.in_cooldown is True
    
    def test_cooldown_expires(self):
        """Test cooldown expires after duration"""
        thresholds = RiskThresholds(adjustment_cooldown_sec=1)  # 1 second
        manager = PortfolioRiskManager(capital=300000, thresholds=thresholds)
        
        manager.set_adjustment_cooldown()
        assert manager.is_in_cooldown() is True
        
        # Wait for cooldown to expire
        import time
        time.sleep(1.1)
        
        assert manager.is_in_cooldown() is False


class TestPortfolioStateUpdate:
    """Tests for portfolio state calculation"""
    
    def test_update_state_with_trades(self):
        """Test portfolio state aggregates Greeks and P&L"""
        manager = PortfolioRiskManager(capital=300000)
        
        market_data = MarketData(
            nifty_spot=24000,
            india_vix=15.0,
            timestamp=datetime.now()
        )
        
        # Create two short trades
        trade1 = Trade(
            trade_id="t1",
            symbol="NIFTY24000CE",
            qty=1,
            direction=Direction.SELL,
            price=100,
            timestamp=datetime.now(),
            option_type="CE",
            strike_price=24000
        )
        trade1.current_price = 80
        trade1.greeks = Greeks(delta=30, gamma=0.05, theta=-10, vega=20)
        
        trade2 = Trade(
            trade_id="t2",
            symbol="NIFTY24000PE",
            qty=1,
            direction=Direction.SELL,
            price=100,
            timestamp=datetime.now(),
            option_type="PE",
            strike_price=24000
        )
        trade2.current_price = 90
        trade2.greeks = Greeks(delta=-30, gamma=0.05, theta=-10, vega=20)
        
        trades = {"t1": trade1, "t2": trade2}
        
        state = manager.update_state(market_data, trades)
        
        # Short positions negate Greeks
        assert state.net_delta == pytest.approx(0.0, abs=5)  # ~0 (balanced strangle)
        assert state.net_vega < 0  # Short vega
        assert state.unrealized_pnl > 0  # Profit (prices dropped)
        assert state.num_positions == 2
    
    def test_update_state_empty_trades(self):
        """Test portfolio state with no trades"""
        manager = PortfolioRiskManager(capital=300000)
        
        market_data = MarketData(
            nifty_spot=24000,
            india_vix=15.0,
            timestamp=datetime.now()
        )
        
        state = manager.update_state(market_data, {})
        
        assert state.net_delta == 0.0
        assert state.net_vega == 0.0
        assert state.daily_pnl == 0.0
        assert state.num_positions == 0


class TestHedgeSizing:
    """Tests for hedge sizing calculations"""
    
    def test_hedge_sizing_long_delta(self):
        """Test hedge sizing when portfolio is long delta"""
        manager = PortfolioRiskManager(capital=300000)
        
        # Portfolio is long delta, need to buy puts
        option_type, num_lots, target_delta = manager.get_hedge_sizing(
            current_delta=50.0,
            target_delta=10.0
        )
        
        assert option_type == "PE"
        assert num_lots >= 1
        assert target_delta < 0  # Puts have negative delta
    
    def test_hedge_sizing_short_delta(self):
        """Test hedge sizing when portfolio is short delta"""
        manager = PortfolioRiskManager(capital=300000)
        
        # Portfolio is short delta, need to buy calls
        option_type, num_lots, target_delta = manager.get_hedge_sizing(
            current_delta=-50.0,
            target_delta=-10.0
        )
        
        assert option_type == "CE"
        assert num_lots >= 1
        assert target_delta > 0  # Calls have positive delta


class TestWingStrikes:
    """Tests for wing strike calculations"""
    
    def test_wing_strike_for_call(self):
        """Test wing strike calculation for call"""
        manager = PortfolioRiskManager(capital=300000)
        
        wing_strike = manager.calculate_wing_strikes(
            base_strike=24000,
            option_type="CE",
            spread_width=200
        )
        
        assert wing_strike == 24200
    
    def test_wing_strike_for_put(self):
        """Test wing strike calculation for put"""
        manager = PortfolioRiskManager(capital=300000)
        
        wing_strike = manager.calculate_wing_strikes(
            base_strike=24000,
            option_type="PE",
            spread_width=200
        )
        
        assert wing_strike == 23800


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
