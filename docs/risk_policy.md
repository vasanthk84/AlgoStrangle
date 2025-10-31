# Portfolio Risk Policy

## Overview

The Portfolio Risk Manager provides automated risk control for the short-strangle trading system. It monitors portfolio-level metrics and takes automatic actions to limit losses during adverse market conditions.

## Key Features

### 1. VIX Shock Detection

Monitors VIX for sudden spikes that indicate market stress.

**Thresholds:**
- Absolute change: ≥4 points in one tick
- Rate of change: ≥15% intraday (from market open)

**Actions on VIX shock:**
- Reduce short vega exposure by 40% (close fraction of short positions)
- Convert remaining positions to defined-risk (add wings) - optional
- Pause new entries
- Set 15-minute cooldown

**Example:**
```
VIX: 15.0 → 19.5 (+4.5 pts)
Action: Close 2 out of 5 short positions
Result: Net vega reduced from -500 to -300
```

### 2. Delta Band Monitoring

Maintains portfolio delta within acceptable bands to avoid directional risk.

**Delta Bands (VIX-adjusted):**
| VIX Range | Delta Band |
|-----------|------------|
| < 15      | ±15 deltas |
| 15-20     | ±12 deltas |
| 20-30     | ±10 deltas |
| > 30      | ±8 deltas  |

**Hysteresis:**
- Trigger hedge at high band (e.g., ±15)
- Exit hedge at low band (60% of high band = ±9)
- Prevents oscillation

**Actions when delta breaches band:**
- If net delta > +15: Buy PUTs to neutralize
- If net delta < -15: Buy CALLs to neutralize
- Hedge size calculated to bring delta within low band

**Example:**
```
Portfolio net delta: +300 (too long)
Band: ±15
Action: Buy 4 lots of 35-delta PUTs
Result: Net delta reduced to +8
```

### 3. Daily Loss Kill-Switch

Hard stop on daily losses to prevent catastrophic drawdown.

**Threshold:** 1.5% of capital (configurable)

**Actions when breached:**
- Close ALL active positions immediately
- Lock system for the day (no new entries)
- Send critical alert notification

**Example:**
```
Capital: ₹300,000
Threshold: ₹4,500 (1.5%)
Daily P&L: -₹5,000
Action: Close all 6 positions, lock system
```

### 4. Regime-Aware Parameter Adjustments

Dynamically adjusts trading parameters based on VIX regime.

**Adjustments by VIX level:**

| VIX Range | Position Size | Roll Delta | Stop Loss | OTM Distance |
|-----------|--------------|------------|-----------|--------------|
| < 15      | 100%         | 1.0x       | 1.0x      | 1.0x         |
| 15-20     | 80%          | 0.9x       | 0.9x      | 1.1x         |
| 20-25     | 60%          | 0.8x       | 0.8x      | 1.2x         |
| > 25      | 30%          | 0.7x       | 0.7x      | 1.3x         |

**Example:**
```
VIX: 22 (high)
Base position size: 5 lots
Adjusted: 3 lots (60% of base)
Roll trigger: Delta 24 (vs. base 30 * 0.8)
Stop loss: 24% (vs. base 30% * 0.8)
```

### 5. Cooldown Mechanism

Prevents rapid-fire adjustments that could increase transaction costs.

**Cooldown period:** 15 minutes (900 seconds)

After any risk action (VIX shock response, delta hedge, etc.), the system enters cooldown. During cooldown:
- No new risk actions taken
- Normal trade management continues (stops, rolls, exits)
- New entries blocked

## Configuration Parameters

All parameters are configurable in `strangle/config.py`:

```python
# Daily loss kill-switch
DAILY_MAX_LOSS_PCT = 0.015  # 1.5% of capital

# Delta bands
DELTA_BAND_BASE = 15.0
DELTA_BAND_TIGHT_VIX = {
    15: 15,   # VIX < 15: band = 15 deltas
    20: 12,   # VIX < 20: band = 12 deltas
    30: 10,   # VIX < 30: band = 10 deltas
    999: 8    # VIX >= 30: band = 8 deltas
}

# VIX shock detection
VIX_SHOCK_ABS = 4.0         # Points
VIX_SHOCK_ROC_PCT = 15.0    # Percentage

# VIX shock response
SHORT_VEGA_REDUCTION_PCT = 0.4  # 40% reduction

# Adjustment cooldown
ADJUSTMENT_COOLDOWN_SEC = 900  # 15 minutes

# Hedge preferences
HEDGE_PREFERRED = "OPTIONS"     # "OPTIONS" or "FUT"
HEDGE_DELTA_OFFSET = 35         # Target delta for hedges
```

## Portfolio State Tracking

The risk manager maintains a real-time snapshot of portfolio state:

```python
PortfolioState:
    net_delta: float       # Sum of all position deltas
    net_gamma: float       # Sum of all position gammas
    net_theta: float       # Sum of all position thetas
    net_vega: float        # Sum of all position vegas
    unrealized_pnl: float  # Current unrealized P&L
    realized_pnl: float    # Today's realized P&L
    daily_pnl: float       # Total daily P&L
    num_active_trades: int # Number of active positions
```

## Integration with Trade Manager

The risk manager is automatically invoked during each market update:

1. **Update portfolio state** from active trades and market data
2. **Check daily stop** - highest priority
3. **Check VIX shock** - if detected, take action
4. **Check delta bands** - if breached, place hedge
5. **Apply cooldown** after any action

## Backtesting with Risk Manager

The risk manager is active during backtests. To test specific scenarios:

### VIX Spike Scenario
```bash
python run.py
# Select mode: 3 (Backtest)
# Date range covering VIX spike (e.g., 2024-06-03 to 2024-06-14)
```

Expected output in logs:
- VIX_SHOCK events logged
- Positions closed to reduce vega
- Cooldown periods noted

### High Delta Scenario
- Occurs naturally during trending markets
- Delta hedges logged with "DELTA_HEDGE_BUY_CE" or "DELTA_HEDGE_BUY_PE"
- Net delta shown before/after hedge

### Daily Stop Scenario
- If backtest encounters severe loss day
- All positions closed
- System locked (no new entries rest of day)

## Notifications

Risk events trigger Telegram notifications (if configured):

1. **VIX Shock Alert:**
   ```
   ⚠️ VIX SHOCK DETECTED
   Previous VIX: 15.0
   Current VIX: 19.5
   Change: +4.5 pts (+30%)
   
   Actions Taken:
   • Reduced short vega by 40%
   • Closed 2 positions
   • Net vega: -500 → -300
   ```

2. **Delta Hedge Alert:**
   ```
   🔄 DELTA HEDGE EXECUTED
   Net Delta Before: +300
   Net Delta After: +8
   Change: -292
   
   Hedge Instruments:
   BUY 4 lots PE 24035 @ ₹45.00
   ```

3. **Daily Stop Alert:**
   ```
   🛑 DAILY LOSS KILL-SWITCH TRIGGERED
   Daily P&L: ₹-5,000
   Threshold: ₹-4,500
   
   ⚠️ ALL POSITIONS WILL BE CLOSED
   ⚠️ NO NEW ENTRIES TODAY
   ```

## Best Practices

1. **Capital Setting:** Ensure `CAPITAL` in config matches your actual trading capital for accurate daily stop calculation.

2. **VIX Thresholds:** Adjust `VIX_SHOCK_ABS` and `VIX_SHOCK_ROC_PCT` based on historical VIX behavior in your market.

3. **Delta Bands:** Tighter bands (lower values) = more frequent hedging but better delta control. Start with defaults and adjust based on transaction costs.

4. **Cooldown Period:** Increase if you find too many rapid adjustments. Decrease if you want more responsive risk management.

5. **Testing:** Always backtest over periods containing:
   - VIX spikes (2024-06-10, 2024-08-05)
   - Strong trends (2024-03-15 to 2024-03-22)
   - Calm ranges (2024-04-01 to 2024-04-15)

## Monitoring

Check risk manager status in logs:
```
Portfolio state: ΣΔ=150, ΣΓ=0.12, ΣΘ=-45, Σν=-320, Unrealized P&L=₹2,500
Risk Status:
  Daily Stop: OK
  VIX Shock: OK
  Cooldown: NO
```

## Troubleshooting

### No risk actions taken when expected
- Check if system is in cooldown
- Verify thresholds are not too high
- Confirm Greeks are being calculated

### Too many adjustments
- Increase cooldown period
- Widen delta bands
- Increase VIX shock thresholds

### Hedge orders failing
- Verify strike selection logic
- Check if instruments exist in broker data
- Review hedge price validation

## Security Note

The risk manager uses environment variables for sensitive data. Never commit API keys or tokens to the repository. See main README for setup instructions.
