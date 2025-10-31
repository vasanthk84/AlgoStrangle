# Backtest Guide - AlgoStrangle Risk Management

This guide explains how to backtest the portfolio risk management system with stress-test scenarios.

## Overview

The backtest system validates risk policies by replaying historical market data and measuring:
- VIX shock detections and responses
- Delta hedge placements
- Daily kill-switch activations
- P&L with and without risk controls

## Quick Start

### Basic Backtest Command

```bash
python run.py backtest --start YYYY-MM-DD --end YYYY-MM-DD
```

### Example Commands

```bash
# VIX spike period (June 2024)
python run.py backtest --start 2024-06-03 --end 2024-06-14

# Single trend day
python run.py backtest --start 2024-07-15 --end 2024-07-15

# Calm period (baseline)
python run.py backtest --start 2024-05-01 --end 2024-05-15
```

## Stress Test Scenarios

### Scenario 1: VIX Spike (June 2024)

**Purpose**: Test VIX shock detection and vega reduction.

**Setup**:
```bash
python run.py backtest --start 2024-06-03 --end 2024-06-14
```

**Market Conditions**:
- VIX opens at ~14-15 range
- Spikes to 20+ due to volatility event
- Tests absolute and ROC thresholds

**Expected Behavior**:
1. System detects VIX shock when:
   - VIX moves ≥4 pts (e.g., 15 → 19)
   - VIX changes ≥15% day-over-day
2. Actions taken:
   - Close ~40% of short positions
   - Add wings to remaining strangles
   - Pause entries for 15 minutes
3. Logs show:
   - VIX_SHOCK event with reason
   - Position reduction count
   - Wing additions (WING trades)
   - Cooldown activation

**Acceptance Criteria**:
- ✓ VIX shock logged when conditions met
- ✓ Short vega reduced by ~40%
- ✓ Wings added or partial positions closed
- ✓ Entries paused for cooldown period

### Scenario 2: Trend Day (High Delta)

**Purpose**: Test delta hedging with hysteresis.

**Setup**:
```bash
python run.py backtest --start 2024-07-15 --end 2024-07-15
```

**Market Conditions**:
- Strong directional move (>2%)
- Portfolio delta drifts outside bands
- Tests hedge placement and sizing

**Expected Behavior**:
1. Portfolio delta exceeds high band (e.g., ±15 deltas)
2. System places hedge:
   - Buys CE (if short delta) or PE (if long delta)
   - Sizes to bring delta within low band (±9)
3. Hysteresis prevents immediate re-hedge
4. Logs show:
   - DELTA_HEDGE event
   - Net delta before/after
   - Hedge instrument and sizing
   - Cooldown set

**Acceptance Criteria**:
- ✓ Hedge triggered when |delta| > high band
- ✓ Net delta reduced to within low band
- ✓ Cooldown prevents thrashing
- ✓ Hedge trades tagged as HEDGE type

### Scenario 3: Calm Period (Baseline)

**Purpose**: Establish baseline performance without risk events.

**Setup**:
```bash
python run.py backtest --start 2024-05-01 --end 2024-05-15
```

**Market Conditions**:
- VIX stable (12-16 range)
- No major directional moves
- Normal theta decay

**Expected Behavior**:
1. No VIX shocks detected
2. Minimal delta hedges (if any)
3. No daily stops triggered
4. Positions run to profit target or expiry

**Acceptance Criteria**:
- ✓ No risk events logged
- ✓ Normal entry/exit flow
- ✓ Positive theta decay captured
- ✓ Win rate within expected range

## Interpreting Backtest Output

### Console Summary

At backtest completion, the system prints:

```
════════════════════════════════════════════════════════════
BACKTEST SUMMARY: 2024-06-03 to 2024-06-14
════════════════════════════════════════════════════════════
Total Trades: 45
Win Rate: 62.2%
Total P&L: ₹12,500 (+4.2%)

Risk Management Statistics:
  • VIX Shocks Detected: 2
  • Delta Hedges Placed: 5
  • Daily Stops Triggered: 0
  • Cooldown Activations: 7
  
Position Breakdown:
  • BASE trades: 38
  • HEDGE trades: 5
  • WING trades: 2
  
Exit Reasons:
  • Profit Target: 18 (40.0%)
  • Stop Loss: 12 (26.7%)
  • Roll: 8 (17.8%)
  • Time Square Off: 7 (15.6%)
════════════════════════════════════════════════════════════
```

### Key Metrics

#### Risk Event Counts
- **VIX Shocks**: Number of times VIX threshold breached
- **Delta Hedges**: Number of hedge placements
- **Daily Stops**: Number of days stopped out (should be 0-1)
- **Cooldowns**: Total cooldown activations

#### Trade Breakdown
- **BASE**: Primary strangle legs
- **HEDGE**: Delta hedge positions
- **WING**: Protective wings for defined risk

#### P&L Analysis
Compare P&L with/without risk management:
- Baseline (no risk controls)
- With VIX protection
- With delta hedging
- With daily stop

### Log Files

Detailed logs in `logs/` directory:

#### Main Log
`logs/main_logs/strangle_trading_YYYYMMDD_HHMMSS.log`

Look for:
```
⚠️ VIX SHOCK DETECTED: Current=19.50, Prev=15.20, Open=15.00 | VIX moved +4.3 pts
⚠️ DELTA HEDGE NEEDED: Net delta 18.5 exceeds band ±15.0 (VIX=16.5), target=9.0
🛑 DAILY STOP TRIGGERED: Daily P&L ₹-5,200 breached limit ₹-4,500
```

#### CSV Output
`logs/csv/backtest_trades_YYYYMMDD.csv`

Columns include:
- `trade_id`, `symbol`, `entry_price`, `exit_price`
- `pnl`, `pnl_pct`, `holding_time`
- `exit_reason`, `trade_type` (BASE/HEDGE/WING)

#### Adjustment Summary
`logs/summary/adjustments_YYYYMMDD.json`

```json
{
  "vix_shocks": [
    {
      "timestamp": "2024-06-05 11:23:00",
      "prev_vix": 15.2,
      "current_vix": 19.5,
      "reason": "VIX moved +4.3 pts | VIX changed +28.3% from prev",
      "actions": ["REDUCE_SIZE", "ADD_WINGS", "PAUSE_ENTRIES"],
      "positions_closed": 2,
      "wings_added": 1
    }
  ],
  "delta_hedges": [
    {
      "timestamp": "2024-06-07 14:15:00",
      "net_delta_before": 18.5,
      "net_delta_after": 8.2,
      "hedge_instrument": "NIFTY24200CE",
      "hedge_qty": 1,
      "reason": "Net delta exceeded band"
    }
  ],
  "daily_stops": []
}
```

## Customizing Backtest Parameters

### Modify Risk Thresholds

Edit `strangle/config.py` before backtest:

```python
# Test tighter stop
DAILY_MAX_LOSS_PCT = 0.01  # 1% instead of 1.5%

# Test more sensitive VIX shock
VIX_SHOCK_ABS = 3.0  # 3 pts instead of 4

# Test wider delta bands
DELTA_BAND_BASE = 20.0  # ±20 deltas instead of ±15
```

### Compare Scenarios

Run same backtest with different configs:

```bash
# Baseline (no risk controls)
# Temporarily disable in trade_manager.py
python run.py backtest --start 2024-06-03 --end 2024-06-14 > baseline.log

# With VIX protection only
# Enable VIX shock, disable delta hedge
python run.py backtest --start 2024-06-03 --end 2024-06-14 > vix_only.log

# With all risk controls
# Enable all features
python run.py backtest --start 2024-06-03 --end 2024-06-14 > full_risk.log
```

Compare P&L, max drawdown, and Sharpe ratio across scenarios.

## Reproducibility

### Fix Random Seed

In `run.py`, set:
```python
import random
import numpy as np

random.seed(42)
np.random.seed(42)
```

### Cache Historical Data

First run downloads and caches data:
```bash
python run.py backtest --start 2024-06-03 --end 2024-06-14
# Data cached to /backtest_cache/
```

Subsequent runs use cached data for consistent results.

### Version Control

Record backtest parameters:
```bash
git log -1 --oneline > logs/summary/git_version.txt
cat strangle/config.py > logs/summary/config_snapshot.py
```

## Advanced: Custom Scenarios

### Create Custom Date Ranges

Known volatile periods:
- **Election volatility**: May 2024
- **Fed announcements**: March 2024
- **Earnings season**: Jan/Apr/Jul/Oct 2024

### Synthetic Shock Testing

Modify `historical_data_manager.py` to inject synthetic shocks:

```python
# Inject VIX spike on specific date
if current_date == datetime(2024, 6, 5).date():
    market_data.india_vix *= 1.3  # +30% VIX jump
```

### Parameter Sweep

Test multiple parameter combinations:

```bash
# Script: test_params.sh
for vix_shock in 3.0 4.0 5.0; do
  for delta_band in 10.0 15.0 20.0; do
    echo "Testing VIX_SHOCK=$vix_shock, DELTA_BAND=$delta_band"
    # Modify config.py
    # Run backtest
    # Save results
  done
done
```

## Validation Checklist

Before deploying risk management:

- [ ] VIX spike scenario shows shock detection
- [ ] Vega reduction ~40% on shock
- [ ] Wings added or positions closed
- [ ] Delta hedge placed when bands breached
- [ ] Net delta returns to low band after hedge
- [ ] Cooldown prevents repeated adjustments
- [ ] Daily stop triggers and closes all positions
- [ ] Entries blocked after daily stop
- [ ] Logs clearly show all risk events
- [ ] Notifications sent for each event
- [ ] P&L includes hedge costs
- [ ] No exceptions or crashes in backtest

## Troubleshooting

### No VIX Shocks Detected
- Check VIX data availability in backtest period
- Lower `VIX_SHOCK_ABS` or `VIX_SHOCK_ROC_PCT` thresholds
- Verify `prev_vix` and `vix_open` are being tracked

### Delta Hedges Not Placed
- Check portfolio delta calculation (sum of trade Greeks)
- Verify `update_state()` called before `check_delta_bands()`
- Ensure cooldown not blocking hedges
- Check `active_trades` has Greeks populated

### Daily Stop Not Triggering
- Verify `realized_pnl` + `unrealized_pnl` calculation
- Check threshold: `-capital * DAILY_MAX_LOSS_PCT`
- Ensure `check_daily_stop()` called each update

### Backtest Crashes
- Check date range validity (weekdays only)
- Ensure historical data complete for period
- Verify no None values in Greeks or prices
- Check logs for exceptions before crash

## Performance Benchmarks

Expected runtime on standard hardware:

| Scenario | Duration | Runtime | Trades |
|----------|----------|---------|--------|
| Calm period | 10 days | ~30 sec | 20-30 |
| VIX spike | 8 days | ~25 sec | 15-25 |
| Trend day | 1 day | ~5 sec | 2-5 |

Large backtests (>30 days) may take several minutes due to data loading and Greeks calculation.

## Next Steps

After successful backtesting:

1. Review adjustment logs and tune parameters
2. Run paper trading with same config
3. Monitor live risk events in paper mode
4. Gradually deploy to live trading
5. Continue monitoring and iterating

## Related Documentation

- `docs/risk_policy.md` - Detailed risk parameter explanations
- `README.md` - General setup and usage
- `strangle/risk_policy.py` - Implementation details

---

**Remember**: Backtest results don't guarantee future performance. Always paper trade before live deployment.
