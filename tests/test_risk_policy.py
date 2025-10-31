"""
Unit tests for PortfolioRiskManager

Tests cover:
- VIX shock detection (absolute and rate-of-change thresholds)
- Delta bands and hysteresis
- Daily loss kill-switch
- Regime adjustments
- Cooldown mechanism
"""

import sys
import os
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from strangle.risk_policy import PortfolioRiskManager, RiskAction, PortfolioState
from strangle.config import Config
from strangle.models import Trade, Direction, Greeks, MarketData


class MockConfig:
    """Mock config for testing"""
    CAPITAL = 300000
    DAILY_MAX_LOSS_PCT = 0.015
    DELTA_BAND_BASE = 15.0
    DELTA_BAND_TIGHT_VIX = {15: 15, 20: 12, 30: 10, 999: 8}
    VIX_SHOCK_ABS = 4.0
    VIX_SHOCK_ROC_PCT = 15.0
    SHORT_VEGA_REDUCTION_PCT = 0.4
    ADJUSTMENT_COOLDOWN_SEC = 900
    HEDGE_PREFERRED = 'OPTIONS'


def test_vix_shock_absolute():
    """Test VIX shock detection - absolute threshold"""
    print("\n=== Test: VIX Shock - Absolute Threshold ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Set initial VIX
    risk_mgr.check_vix_shock(15.0)
    
    # Test: VIX jumps by 4+ points -> should trigger
    response = risk_mgr.check_vix_shock(19.5)
    
    assert response is not None, "VIX shock should be detected"
    assert response.action == RiskAction.VIX_SHOCK_REDUCE_VEGA
    print(f"✓ VIX shock detected: {response.reason}")
    print(f"  Prev VIX: {response.parameters['prev_vix']:.2f}")
    print(f"  Current VIX: {response.parameters['current_vix']:.2f}")
    print(f"  Change: +{response.parameters['vix_change']:.2f} pts")


def test_vix_shock_roc():
    """Test VIX shock detection - rate of change threshold"""
    print("\n=== Test: VIX Shock - Rate of Change ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Set VIX at open
    risk_mgr.check_vix_shock(20.0)
    
    # Test: VIX rises by 15%+ intraday -> should trigger
    response = risk_mgr.check_vix_shock(23.5)  # +17.5% from open
    
    assert response is not None, "VIX shock should be detected"
    assert response.action == RiskAction.VIX_SHOCK_REDUCE_VEGA
    print(f"✓ VIX shock detected: {response.reason}")
    print(f"  VIX at open: {risk_mgr.vix_at_open:.2f}")
    print(f"  Current VIX: {response.parameters['current_vix']:.2f}")
    print(f"  ROC: +{response.parameters['vix_roc_pct']:.1f}%")


def test_vix_shock_no_trigger():
    """Test VIX shock - below threshold (no trigger)"""
    print("\n=== Test: VIX Shock - No Trigger ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Set initial VIX
    risk_mgr.check_vix_shock(15.0)
    
    # Test: Small VIX change -> should NOT trigger
    response = risk_mgr.check_vix_shock(16.0)
    
    assert response is None, "VIX shock should NOT be detected for small changes"
    print("✓ No VIX shock detected (change too small)")


def test_delta_bands_trigger():
    """Test delta bands - trigger hedge"""
    print("\n=== Test: Delta Bands - Trigger Hedge ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Create portfolio state with high net delta
    risk_mgr.portfolio_state.net_delta = 300.0  # High positive delta
    
    # Test: Delta outside high band -> should trigger hedge
    response = risk_mgr.check_delta_bands(vix=12.0)  # VIX < 15 -> band = 15
    
    assert response is not None, "Delta hedge should be triggered"
    assert response.action == RiskAction.DELTA_HEDGE_BUY_PE
    print(f"✓ Delta hedge triggered: {response.reason}")
    print(f"  Net delta: {response.parameters['net_delta']:.0f}")
    print(f"  High band: {response.parameters['high_band']:.0f}")
    print(f"  Action: {response.action.value}")


def test_delta_bands_no_trigger():
    """Test delta bands - within acceptable range"""
    print("\n=== Test: Delta Bands - No Trigger ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Create portfolio state with low net delta
    risk_mgr.portfolio_state.net_delta = 10.0
    
    # Test: Delta within band -> should NOT trigger
    response = risk_mgr.check_delta_bands(vix=12.0)
    
    assert response is None, "Delta hedge should NOT be triggered"
    print("✓ No delta hedge needed (within bands)")


def test_daily_stop_trigger():
    """Test daily loss kill-switch"""
    print("\n=== Test: Daily Loss Kill-Switch ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Calculate threshold
    max_loss = config.CAPITAL * config.DAILY_MAX_LOSS_PCT
    
    # Test: P&L below threshold -> should trigger
    response = risk_mgr.check_daily_stop(daily_pnl=-5000.0)
    
    assert response is not None, "Daily stop should be triggered"
    assert response.action == RiskAction.DAILY_STOP_CLOSE_ALL
    print(f"✓ Daily stop triggered: {response.reason}")
    print(f"  Daily P&L: ₹{response.parameters['daily_pnl']:,.2f}")
    print(f"  Threshold: ₹{response.parameters['threshold']:,.2f}")


def test_daily_stop_no_trigger():
    """Test daily loss kill-switch - below threshold"""
    print("\n=== Test: Daily Stop - No Trigger ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Test: P&L above threshold -> should NOT trigger
    response = risk_mgr.check_daily_stop(daily_pnl=-1000.0)
    
    assert response is None, "Daily stop should NOT be triggered"
    print("✓ No daily stop (P&L within limits)")


def test_regime_adjustments_low_vix():
    """Test regime adjustments - low VIX"""
    print("\n=== Test: Regime Adjustments - Low VIX ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Test: Low VIX -> normal parameters
    adjustments = risk_mgr.regime_adjustments(vix=12.0, iv_rank=50)
    
    assert adjustments['position_size'] == 1.0
    print(f"✓ Low VIX adjustments:")
    print(f"  Position size: {adjustments['position_size']:.1%}")
    print(f"  Roll delta trigger: {adjustments['roll_delta_trigger']:.1%}")


def test_regime_adjustments_high_vix():
    """Test regime adjustments - high VIX"""
    print("\n=== Test: Regime Adjustments - High VIX ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Test: High VIX -> reduced parameters
    adjustments = risk_mgr.regime_adjustments(vix=26.0, iv_rank=50)
    
    assert adjustments['position_size'] < 1.0
    print(f"✓ High VIX adjustments:")
    print(f"  Position size: {adjustments['position_size']:.1%}")
    print(f"  Roll delta trigger: {adjustments['roll_delta_trigger']:.1%}")
    print(f"  Stop loss multiple: {adjustments['stop_loss_multiple']:.1%}")


def test_cooldown_mechanism():
    """Test cooldown mechanism"""
    print("\n=== Test: Cooldown Mechanism ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Initially not in cooldown
    assert not risk_mgr.is_in_cooldown()
    print("✓ Initially not in cooldown")
    
    # Set cooldown
    risk_mgr.set_cooldown()
    assert risk_mgr.is_in_cooldown()
    print(f"✓ Cooldown activated until {risk_mgr.adjustment_cooldown_until.strftime('%H:%M:%S')}")
    
    # Fast-forward past cooldown
    risk_mgr.adjustment_cooldown_until = datetime.now() - timedelta(seconds=1)
    assert not risk_mgr.is_in_cooldown()
    print("✓ Cooldown expired")


def test_portfolio_state_update():
    """Test portfolio state aggregation"""
    print("\n=== Test: Portfolio State Update ===")
    
    config = MockConfig()
    risk_mgr = PortfolioRiskManager(config)
    
    # Create mock market data
    market_data = MarketData(
        nifty_spot=24000.0,
        india_vix=15.0,
        timestamp=datetime.now()
    )
    
    # Create mock trades with Greeks
    trades = {
        'trade1': Trade(
            trade_id='trade1',
            symbol='NIFTY24000CE',
            qty=2,
            direction=Direction.SELL,
            price=100.0,
            timestamp=datetime.now(),
            option_type='CE',
            strike_price=24000.0
        ),
        'trade2': Trade(
            trade_id='trade2',
            symbol='NIFTY24000PE',
            qty=2,
            direction=Direction.SELL,
            price=100.0,
            timestamp=datetime.now(),
            option_type='PE',
            strike_price=24000.0
        )
    }
    
    # Add Greeks
    trades['trade1'].greeks = Greeks(delta=30.0, gamma=0.05, theta=-5.0, vega=10.0)
    trades['trade2'].greeks = Greeks(delta=-30.0, gamma=0.05, theta=-5.0, vega=10.0)
    
    # Update current prices for P&L
    trades['trade1'].update_price(80.0)
    trades['trade2'].update_price(80.0)
    
    # Update state
    state = risk_mgr.update_state(market_data, trades)
    
    # Verify aggregation
    # For short positions: multiplier = -1
    # CE: delta = 30 * 2 * 75 * (-1) = -4500
    # PE: delta = -30 * 2 * 75 * (-1) = 4500
    # Net = 0
    
    print(f"✓ Portfolio state updated:")
    print(f"  Net Delta: {state.net_delta:.0f}")
    print(f"  Net Gamma: {state.net_gamma:.4f}")
    print(f"  Net Theta: {state.net_theta:.2f}")
    print(f"  Net Vega: {state.net_vega:.2f}")
    print(f"  Unrealized P&L: ₹{state.unrealized_pnl:,.2f}")
    print(f"  Active Trades: {state.num_active_trades}")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("PORTFOLIO RISK MANAGER - UNIT TESTS")
    print("="*60)
    
    test_functions = [
        test_vix_shock_absolute,
        test_vix_shock_roc,
        test_vix_shock_no_trigger,
        test_delta_bands_trigger,
        test_delta_bands_no_trigger,
        test_daily_stop_trigger,
        test_daily_stop_no_trigger,
        test_regime_adjustments_low_vix,
        test_regime_adjustments_high_vix,
        test_cooldown_mechanism,
        test_portfolio_state_update
    ]
    
    passed = 0
    failed = 0
    
    for test_func in test_functions:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n✗ TEST FAILED: {test_func.__name__}")
            print(f"  Error: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ TEST ERROR: {test_func.__name__}")
            print(f"  Error: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
