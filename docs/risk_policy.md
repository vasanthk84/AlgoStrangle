# Portfolio Risk Policy

This document explains the risk management features of the AlgoStrangle trading system.

## Overview

The Portfolio Risk Manager (`strangle/risk_policy.py`) provides multiple layers of protection:

1. **VIX Shock Detection** - Reduces exposure during volatility spikes
2. **Delta Band Monitoring** - Maintains portfolio delta neutrality via hedges
3. **Daily Kill-Switch** - Stops trading when daily loss limit breached
4. **Regime-Aware Adjustments** - Scales parameters based on market conditions

## Configuration Parameters

### Daily Loss Limit
```python
DAILY_MAX_LOSS_PCT = 0.015  # 1.5% of capital
```
If daily P&L (realized + unrealized) drops below -1.5% of capital:
- All positions are closed immediately
- New entries blocked for remainder of trading day
- Notifications sent via Telegram

**Example**: With ₹3,00,000 capital, stop triggers at -₹4,500 loss.

### Delta Bands

Delta bands control portfolio directional exposure. The system uses **hysteresis** to prevent excessive hedging:

```python
DELTA_BAND_BASE = 15.0  # Base band (±15 deltas)

# VIX-scaled bands (tighter in high VIX)
DELTA_BAND_TIGHT_VIX = {
    15.0: 15.0,  # VIX < 15: ±15 deltas
    20.0: 12.0,  # VIX < 20: ±12 deltas  
    30.0: 10.0,  # VIX < 30: ±10 deltas
    999.0: 8.0   # VIX >= 30: ±8 deltas
}
```

**Hysteresis mechanism**:
- **High band**: Hedge trigger (e.g., ±15 deltas)
- **Low band**: Hedge target (60% of high = ±9 deltas)

When |net delta| > high band → hedge is placed to bring delta within low band.  
This prevents thrashing (repeated hedges when delta oscillates near threshold).

**Example**: 
- VIX = 12, portfolio delta = +18 (exceeds +15 high band)
- System buys PE options to reduce delta to +9 (within low band)
- No further hedging until delta exceeds ±15 again

### VIX Shock Thresholds

VIX shocks trigger defensive actions:

```python
VIX_SHOCK_ABS = 4.0          # Absolute VIX move (points)
VIX_SHOCK_ROC_PCT = 15.0     # VIX rate of change (%)
SHORT_VEGA_REDUCTION_PCT = 0.4  # Reduce short vega by 40%
```

**Shock detection**:
- Absolute: VIX moves ≥4 pts (e.g., 15 → 19)
- Day-over-day: VIX changes ≥15% from previous close
- Intraday: VIX changes ≥15% from market open

**Actions on shock**:
1. **Reduce size**: Close ~40% of short positions (reduces short vega)
2. **Add wings**: Convert remaining naked strangles to defined-risk spreads
3. **Pause entries**: Block new positions for cooldown period (15 min)

**Example**:
- VIX opens at 15.0
- During day, VIX spikes to 20.0 (+33% ROC, +5 pts abs)
- System detects shock, closes 40% of short strangles
- Adds protective wings to remaining positions
- Pauses entries for 15 minutes

### Adjustment Cooldown

```python
ADJUSTMENT_COOLDOWN_SEC = 900  # 15 minutes
```

After any risk adjustment (VIX shock response, delta hedge), the system enters a cooldown to prevent excessive trading. During cooldown:
- No new hedges placed
- No new entries allowed
- Existing positions continue to be monitored

### Hedge Preferences

```python
HEDGE_PREFERRED = "OPTIONS"      # "OPTIONS" or "FUT"
HEDGE_DELTA_OFFSET = 35.0        # Target ~35 delta options
```

For delta hedging:
- **OPTIONS mode**: Buys CE or PE with ~35 delta (responsive, visible decay)
- **FUT mode**: Uses futures (if available, more efficient)

Option selection:
- Portfolio long delta → buy PEs
- Portfolio short delta → buy CEs
- Size: Calculated to bring net delta within low band

### Wings for Defined Risk

```python
WING_SPREAD_WIDTH = 200.0          # Points away from short strike
WING_MAX_COST_PER_LOT = 1000.0     # Max ₹1,000 per lot
```

When converting naked strangles to defined-risk:
- Short 24000 CE → Buy 24200 CE (wing)
- Short 23800 PE → Buy 23600 PE (wing)

Wings cap maximum loss per strangle at spread width × lot size.

## Risk Manager Workflow

### Initialization
```python
from strangle.risk_policy import PortfolioRiskManager, RiskThresholds
from strangle.config import Config

thresholds = RiskThresholds(
    daily_max_loss_pct=Config.DAILY_MAX_LOSS_PCT,
    delta_band_base=Config.DELTA_BAND_BASE,
    vix_shock_abs=Config.VIX_SHOCK_ABS,
    # ... other params
)

risk_manager = PortfolioRiskManager(
    capital=Config.CAPITAL,
    thresholds=thresholds
)
```

### Update Cycle

On each market update:

```python
# 1. Update portfolio state (Greeks + P&L)
state = risk_manager.update_state(market_data, active_trades)

# 2. Check daily stop
is_stop, reason = risk_manager.check_daily_stop(realized_pnl)
if is_stop:
    # Close all, block entries
    trade_manager.close_all_positions("DAILY_STOP")
    notifier.notify_daily_stop(state.daily_pnl, threshold)

# 3. Check VIX shock
is_shock, actions, reason = risk_manager.check_vix_shock(market_data.india_vix)
if is_shock and not risk_manager.is_in_cooldown():
    # Reduce size, add wings, pause entries
    reduce_short_vega_positions(actions)
    risk_manager.set_adjustment_cooldown()

# 4. Check delta bands
needs_hedge, action, target, reason = risk_manager.check_delta_bands(market_data.india_vix)
if needs_hedge and not risk_manager.is_in_cooldown():
    # Place hedge
    place_delta_hedge(target)
    risk_manager.set_adjustment_cooldown()

# 5. Regime adjustments (for entries)
if not risk_manager.daily_stop_triggered and not risk_manager.is_in_cooldown():
    adjustments = risk_manager.regime_adjustments(vix, iv_rank)
    # Scale position size, strikes, stops
```

## Examples

### Example 1: VIX Spike

**Scenario**: Calm market suddenly spikes due to news event.

```
09:30 - VIX opens at 14.5
10:00 - Market drops 1%, VIX at 16.0 (normal range)
11:30 - News breaks, market down 2.5%, VIX jumps to 19.5

Portfolio state:
- 2 short strangles (4 legs)
- Net delta: +8 (acceptable)
- Short vega: -3,000
- P&L: -₹2,800 (unrealized)

Risk manager detects:
✓ VIX shock: 14.5 → 19.5 = +5 pts (+34% ROC)

Actions taken:
1. Close 40% of short positions (1 strangle)
   → Reduces short vega to -1,800
2. Add wings to remaining strangle
   → Converts to iron condor (defined risk)
3. Pause entries for 15 minutes
4. Send notification

Result:
- Max risk now capped at ₹15,000 per remaining spread
- Short vega reduced by 40%
- Exposure reduced, but not fully exited
```

### Example 2: Delta Drift

**Scenario**: Market trends up, portfolio delta increases.

```
Portfolio: 2 short strangles
- CE strikes: 24200 (delta -25 each)
- PE strikes: 23800 (delta +12 each)

Market rallies from 24000 → 24150 over 2 hours

Updated Greeks:
- CE delta: -35 each → net CE delta = -70 * 2 lots * 75 = -10,500
- PE delta: +5 each → net PE delta = +5 * 2 lots * 75 = +750
- Net portfolio delta: -9,750 + 750 = -9,000 / 75 = -120 deltas

VIX = 16 → delta high band = 15
|−120| >> 15 → HEDGE NEEDED

Risk manager calculates:
- Target delta: -9 (low band)
- Delta to hedge: -120 − (−9) = -111
- Buy CEs with delta +35
- Contracts needed: 111 / 35 = 3.2 → 3 contracts (4 lots × 75 = 300, use 3)
  
Actually: 111/35 ~ 3.2 contracts, round to ~4-5 contracts (or 1 lot of NIFTY)

Actions:
1. Buy 1 lot of 24200 CE (~35 delta options)
2. Net delta: -120 + (35 * 75) = -120 + 2,625... 
   (Correct calculation per contract basis)
   
Simplified: Buy enough CE to offset ~111 delta
```

### Example 3: Daily Stop

**Scenario**: Bad trend day, losses accumulate.

```
Capital: ₹3,00,000
Daily stop threshold: -1.5% = -₹4,500

Timeline:
09:45 - Enter 2 strangles, premium collected ₹8,000
10:30 - Market drops 1%, unrealized P&L: -₹2,000
11:00 - Volatility spikes, positions against us
11:30 - One strangle hits hard stop, closed for -₹3,500
        Realized P&L: -₹3,500
        Unrealized P&L: -₹1,500
        Total: -₹5,000
        
Risk manager:
✓ Daily stop triggered: -₹5,000 < -₹4,500

Actions:
1. Close all remaining positions (remaining strangle)
2. Set daily_stop_triggered = True
3. Block new entries for rest of day
4. Send critical notification

Result:
- Final daily P&L: ~-₹5,500 (including exit costs)
- System locked until next trading day
- No further losses possible today
```

## Regime-Based Scaling

The risk manager scales trading parameters based on VIX regime:

| VIX Range | Regime | Position Size | Strike Distance | Stop Tightness | Roll Trigger |
|-----------|--------|---------------|-----------------|----------------|--------------|
| < 15      | Normal | 100%          | 1.0x            | Normal         | Normal       |
| 15-20     | Elevated | 75%         | 1.1x            | 90% (tighter)  | Normal       |
| 20-30     | High   | 50%           | 1.2x            | 80%            | 85% (earlier)|
| > 30      | Crisis | 25%           | 1.4x            | 70%            | 70%          |

**Applied in strategy.py**:
```python
adjustments = risk_manager.regime_adjustments(vix=22, iv_rank=75)
# Returns: {'position_size_multiplier': 0.5, 'stop_loss_multiplier': 0.8, ...}

base_lots = 2
actual_lots = int(base_lots * adjustments['position_size_multiplier'])
# → 2 * 0.5 = 1 lot in high VIX
```

## Backtest Stress Testing

The system includes backtest scenarios to validate risk policies:

```bash
# VIX spike period (June 2024)
python run.py backtest --start 2024-06-03 --end 2024-06-14

# Trend day (2% move)
python run.py backtest --start 2024-07-15 --end 2024-07-15

# Calm period
python run.py backtest --start 2024-05-01 --end 2024-05-15
```

Output includes:
- Number of VIX shocks detected
- Number of delta hedges placed
- Daily stops triggered (count)
- Cooldown activations
- Final P&L with/without risk controls

## Notifications

All risk events trigger Telegram notifications:

- **VIX Shock**: ⚡ Shows VIX change, actions taken
- **Delta Hedge**: 🛡️ Shows delta before/after, instruments
- **Daily Stop**: 🛑 Shows P&L, threshold, positions closed

## Best Practices

1. **Monitor thresholds**: Tune `DAILY_MAX_LOSS_PCT`, `VIX_SHOCK_ABS` based on capital and risk tolerance
2. **Backtest first**: Run historical scenarios before live trading
3. **Review logs**: Check `logs/` for adjustment history
4. **Adjust for margin**: Ensure sufficient margin for hedges and wings
5. **Test notifications**: Verify Telegram alerts working before going live

## Troubleshooting

**Q: Hedges placed too frequently?**  
A: Increase `DELTA_BAND_BASE` or reduce `ADJUSTMENT_COOLDOWN_SEC` for more time between hedges.

**Q: Daily stop too tight?**  
A: Increase `DAILY_MAX_LOSS_PCT` (e.g., 0.02 for 2% limit).

**Q: VIX shocks not detected?**  
A: Lower `VIX_SHOCK_ABS` or `VIX_SHOCK_ROC_PCT` thresholds.

**Q: System in permanent cooldown?**  
A: Check `last_adjustment_time` in logs, ensure cooldown expiring properly.

## Related Files

- `strangle/risk_policy.py` - Core risk manager implementation
- `strangle/config.py` - Risk parameter configuration
- `strangle/trade_manager.py` - Risk manager integration
- `tests/test_risk_policy.py` - Unit tests
- `docs/backtest_readme.md` - Backtest documentation
