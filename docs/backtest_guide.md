# Backtest Guide with Risk Scenarios

## Overview

This guide covers running backtests with the enhanced risk management system, including stress-testing specific risk scenarios like VIX spikes, trending markets, and daily loss limits.

## Quick Start

### Basic Backtest

```bash
python run.py

# Select mode: 3 (Backtest)
# Enter start date: 2024-06-01
# Enter end date: 2024-06-30
# Force refresh: no (unless you want fresh data)
```

The system will:
1. Download/load historical data
2. Simulate trading with risk management active
3. Generate performance reports and CSVs
4. Show risk events in logs

## Risk Scenario Backtests

### Scenario 1: VIX Spike (Volatility Shock)

Test the system's response to sudden volatility increases.

**Recommended Date Ranges:**
- **June 2024 Spike:** 2024-06-03 to 2024-06-14 (VIX: 12 → 18)
- **August 2024 Spike:** 2024-08-02 to 2024-08-09 (VIX: 14 → 23)

**Expected Behavior:**
- VIX shock detected when VIX jumps ≥4 pts or ≥15% intraday
- System closes ~40% of short positions to reduce vega
- Cooldown activated for 15 minutes
- New entries paused during cooldown

**What to Look For in Logs:**
```
WARNING: VIX shock detected: abs change +4.50 pts (>= 4.0)
WARNING: Closing NIFTY24000CE to reduce vega (vega=10.00)
INFO: VIX shock handled. 2 positions closed.
INFO: Cooldown set until 10:45:00
```

**Output Files:**
- Check `logs/trades/backtest_trades_*.csv` for "VIX_SHOCK_REDUCTION" exits
- Check `logs/data/backtest_data_*.csv` for VIX values

### Scenario 2: Trending Market (Delta Stress)

Test delta hedging in strong directional moves.

**Recommended Date Ranges:**
- **March 2024 Rally:** 2024-03-15 to 2024-03-22 (NIFTY: +5% move)
- **May 2024 Correction:** 2024-05-20 to 2024-05-31 (NIFTY: -4% move)

**Expected Behavior:**
- Portfolio net delta breaches bands (e.g., |delta| > 15)
- System buys options to hedge (CEs if too short delta, PEs if too long delta)
- Delta returns within acceptable range
- Cooldown activated

**What to Look For in Logs:**
```
WARNING: Portfolio net delta 300 > 15 (long bias)
INFO: Delta hedge placed: BUY 4 lots PE 24035 @ ₹45.00
INFO: Cooldown set until 11:00:00
```

**Output Files:**
- Look for trades with trade_type="HEDGE" in CSV
- Check net delta values in portfolio state logs

### Scenario 3: Daily Loss Limit (Kill-Switch)

Test the daily stop-loss mechanism.

**Recommended Date Ranges:**
- **High Volatility Period:** 2024-08-05 to 2024-08-06 (severe market drop)
- **Expiry Week Whipsaw:** Any weekly expiry (Tuesdays)

**Expected Behavior:**
- Daily P&L reaches -1.5% of capital (default: -₹4,500 on ₹300,000 capital)
- System immediately closes all positions
- System locked for rest of day (no new entries)

**What to Look For in Logs:**
```
CRITICAL: Daily loss kill-switch triggered: P&L ₹-5,000 <= -₹4,500
INFO: Closing all positions...
CRITICAL: System locked - no new entries allowed today
```

**Output Files:**
- All positions closed with reason "DAILY_STOP"
- No new entries after lock

### Scenario 4: Calm Period (Normal Operations)

Baseline test in low-volatility, range-bound market.

**Recommended Date Ranges:**
- **April 2024:** 2024-04-01 to 2024-04-15
- **July 2024:** 2024-07-15 to 2024-07-26

**Expected Behavior:**
- No VIX shocks
- Minimal delta hedging
- Normal profit targets and stop losses
- No daily kill-switch triggers

**What to Look For in Logs:**
```
INFO: Portfolio state: ΣΔ=5, ΣΓ=0.12, ΣΘ=-45, Σν=-320
INFO: Risk Status: OK (all systems normal)
```

## Interpreting Backtest Results

### Console Output

At the end of each backtest:
```
============================================================
FINAL BACKTEST SUMMARY - 2024-06-01 to 2024-06-30
============================================================

Total Trades: 45
Win Rate: 67.5%
Total P&L: ₹12,345
Max Drawdown: ₹3,456

Risk Actions Summary:
  VIX Shocks: 3
  Delta Hedges: 5
  Daily Stops: 0
  Cooldown Periods: 8

Exit Reasons:
  Profit Target: 15 (33%)
  Stop Loss: 8 (18%)
  VIX Shock: 6 (13%)
  Time Square Off: 12 (27%)
  Roll: 4 (9%)
```

### CSV Files

**1. Trades CSV** (`logs/trades/backtest_trades_*.csv`)
```csv
trade_id,symbol,entry_price,exit_price,pnl,exit_reason,trade_type
T001,NIFTY24000CE,100,80,3000,PROFIT_TARGET,BASE
T002,NIFTY24000PE,100,95,750,VIX_SHOCK_REDUCTION,BASE
T003,NIFTY24100PE,45,40,-750,TIME_SQUARE_OFF,HEDGE
```

**Key Columns:**
- `exit_reason`: Shows why position was closed
- `trade_type`: BASE (normal), HEDGE (delta hedge), WING (protection)
- `pnl`: Net P&L after transaction costs

**2. Daily Performance CSV** (`logs/performance/backtest_daily_performance_*.csv`)
```csv
date,trades,win_rate,pnl,max_drawdown,risk_events
2024-06-03,3,66.7,1500,500,0
2024-06-04,2,50.0,-2000,2000,VIX_SHOCK
2024-06-05,0,0,0,2000,COOLDOWN
```

**3. Backtest Data CSV** (`logs/data/backtest_data_*.csv`)
- Contains market data used in backtest
- Check VIX column for spike dates
- Check spot prices for trend direction

### Log Files

**Main Log** (`logs/main_logs/strangle_trading_*.log`)

Contains detailed execution logs. Search for:
```bash
# VIX shock events
grep -i "vix shock" logs/main_logs/strangle_trading_*.log

# Delta hedges
grep -i "delta hedge" logs/main_logs/strangle_trading_*.log

# Daily stops
grep -i "daily stop" logs/main_logs/strangle_trading_*.log

# Risk manager state
grep -i "portfolio state" logs/main_logs/strangle_trading_*.log
```

## Configuration for Stress Testing

### Increase Sensitivity (More Risk Actions)

Edit `strangle/config.py`:
```python
# Tighter risk controls
DAILY_MAX_LOSS_PCT = 0.01  # 1% instead of 1.5%
VIX_SHOCK_ABS = 3.0  # Lower threshold
VIX_SHOCK_ROC_PCT = 10.0  # Lower threshold
DELTA_BAND_BASE = 10.0  # Tighter bands
ADJUSTMENT_COOLDOWN_SEC = 300  # 5 min instead of 15
```

### Decrease Sensitivity (Fewer Actions)

```python
# Looser risk controls
DAILY_MAX_LOSS_PCT = 0.02  # 2% instead of 1.5%
VIX_SHOCK_ABS = 6.0  # Higher threshold
VIX_SHOCK_ROC_PCT = 20.0  # Higher threshold
DELTA_BAND_BASE = 25.0  # Wider bands
ADJUSTMENT_COOLDOWN_SEC = 1800  # 30 min instead of 15
```

## Comparison Backtests

### With vs. Without Risk Management

**Test 1: WITH risk management (current code)**
```bash
python run.py
# Mode: 3, Dates: 2024-06-01 to 2024-06-30
# Note results
```

**Test 2: WITHOUT risk management**
Temporarily disable in code:
```python
# In strangle/trade_manager.py, comment out risk check
def update_active_trades(self, market_data):
    # ...existing code...
    # self._check_portfolio_risk(market_data)  # DISABLED FOR TEST
```

Re-run same backtest, compare:
- Max drawdown (should be higher without RM)
- Win rate (may be lower without RM)
- Total P&L (trade-off: RM costs money but limits losses)

### Parameter Sensitivity

Test different risk parameters:
```bash
# Test 1: Base settings (DAILY_MAX_LOSS_PCT = 0.015)
# Test 2: Tight settings (DAILY_MAX_LOSS_PCT = 0.01)
# Test 3: Loose settings (DAILY_MAX_LOSS_PCT = 0.02)
```

Compare:
- Number of daily stops triggered
- Average trade duration
- Total transaction costs

## Common Issues

### No Risk Events in Backtest

**Possible Causes:**
1. Date range doesn't include volatile period
2. Thresholds are too high
3. Capital setting is incorrect

**Solutions:**
- Use recommended date ranges above
- Lower thresholds temporarily
- Verify Config.CAPITAL matches test capital

### Too Many Risk Actions

**Possible Causes:**
1. Thresholds too sensitive
2. Cooldown period too short
3. Volatility in selected period is extreme

**Solutions:**
- Increase thresholds
- Increase cooldown period
- Choose different date range

### Backtest Crashes

**Check:**
1. Missing data for date range
2. Invalid symbols in data
3. Memory issues with large date ranges

**Solutions:**
```bash
# Force refresh data
python run.py
# Mode: 3
# Force refresh: yes

# Or clear cache manually
rm -rf back_test_cache/*
```

## Performance Metrics

### Key Metrics to Track

1. **Sharpe Ratio** - Risk-adjusted returns (higher is better)
2. **Max Drawdown** - Largest peak-to-trough decline (lower is better)
3. **Profit Factor** - Gross profit / Gross loss (>1.5 is good)
4. **Win Rate** - % of profitable trades (target: >60%)

### Risk-Specific Metrics

Track these in your backtest results:
- **VIX Shock Events**: Number of times VIX shock triggered
- **Vega Reduction**: Total vega reduced by shock response
- **Delta Hedges**: Number of delta hedges placed
- **Daily Stops**: Number of days system was locked
- **Cooldown Days**: Number of days with adjustments

### Expected Results

**Good Backtest (Effective Risk Management):**
- Max drawdown: <5% of capital
- Daily stops: 0-2 per month
- VIX shock responses: 1-3 per volatile month
- Win rate: 60-70%
- Sharpe ratio: >1.0

**Needs Tuning:**
- Max drawdown: >8% of capital → Tighten stops
- Daily stops: >3 per month → Increase threshold or reduce position size
- No risk events in volatile period → Lower thresholds
- Win rate: <55% → Review entry criteria

## Next Steps

After backtesting:
1. Review results and adjust parameters
2. Run paper trading for 1-2 weeks
3. Start live trading with small position sizes
4. Monitor risk events closely
5. Iterate based on real-world performance

## Support

For backtest issues:
1. Check logs in `logs/main_logs/`
2. Review CSV outputs in `logs/trades/` and `logs/performance/`
3. Compare results with expected behavior above
4. Open GitHub issue with error details if needed
