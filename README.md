# AlgoStrangle - Automated Options Trading System

A sophisticated algorithmic trading system for NIFTY options with advanced portfolio-level risk management, designed for short strangle strategies with automated adjustments.

## Features

### Core Trading
- ✅ **Adaptive Short Strangle Strategy** - Delta-based strike selection
- ✅ **Regime Detection** - Trend-following with 50-day lookback
- ✅ **Multiple Strategy Support** - Short strangle, put spreads, call spreads, iron condors
- ✅ **Automated Rolling** - Delta-triggered position adjustments at 30 delta
- ✅ **Transaction Cost Modeling** - Realistic P&L with slippage and fees
- ✅ **Greeks Calculation** - Black-Scholes with caching for performance

### Portfolio Risk Management (New!)
- 🔥 **VIX Shock Detection** - Auto-reduce exposure on volatility spikes
- 🔥 **Delta Band Monitoring** - Automated hedging to control directional risk
- 🔥 **Daily Loss Kill-Switch** - Hard stop at 1.5% capital loss
- 🔥 **Regime-Aware Adjustments** - VIX-based parameter scaling
- 🔥 **Cooldown Mechanism** - Prevents excessive adjustments

### System
- 📊 **Comprehensive Backtesting** - Historical data with stress scenarios
- 🔔 **Telegram Notifications** - Real-time alerts for all events
- 📈 **Live Dashboard** - Real-time P&L and Greeks monitoring
- 🔒 **Security** - Environment variable based credentials
- 📝 **Audit Trail** - Complete trade history and logs

## Quick Start

### Prerequisites

```bash
# Python 3.8+
python3 --version

# Install dependencies
pip install numpy pandas scipy requests colorama tabulate kiteconnect python-dotenv
```

### Setup

1. **Clone repository:**
   ```bash
   git clone https://github.com/vasanthk84/AlgoStrangle.git
   cd AlgoStrangle
   ```

2. **Configure environment variables** (see [Environment Setup](docs/environment_setup.md)):
   ```bash
   # Create .env file
   cat > .env << EOF
   KITE_API_KEY=your_api_key_here
   KITE_API_SECRET=your_api_secret_here
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   EOF
   ```

3. **Run backtest** (no credentials needed):
   ```bash
   python run.py
   # Select: 3 (Backtest Mode)
   # Date range: 2024-06-01 to 2024-06-30
   ```

4. **View results:**
   ```bash
   ls -la logs/trades/
   ls -la logs/performance/
   ```

## Usage

### Backtest Mode

Test strategy with historical data:
```bash
python run.py
# Select mode: 3
# Enter date range (e.g., 2024-06-01 to 2024-06-30)
```

**Risk Scenario Backtests:**
- VIX Spike: 2024-06-03 to 2024-06-14
- Trending Market: 2024-03-15 to 2024-03-22
- See [Backtest Guide](docs/backtest_guide.md) for more scenarios

### Paper Trading Mode

Test with live data but simulated orders:
```bash
python run.py
# Select mode: 1 (Paper Trading)
```

### Live Trading Mode

**⚠️ Use with caution - real money at risk!**
```bash
python run.py
# Select mode: 2 (Live Trading)
# Confirm: yes
```

### Manual Trade Management

Monitor manually executed trades:
```bash
python run.py
# Select mode: 4 (Manage Manual Trades)
# Update manual_trades.csv with your positions
# Choose: Monitor Only or Auto-Management
```

## Portfolio Risk Management

### VIX Shock Protection

Automatically detects and responds to volatility spikes:
- **Trigger:** VIX jump ≥4 points OR ≥15% intraday
- **Action:** Reduce short vega by 40%
- **Cooldown:** 15 minutes before next adjustment

Example:
```
VIX: 15.0 → 19.5 (+30%)
Action: Close 2 of 5 short positions
Result: Vega reduced -500 → -300
```

### Delta Hedging

Maintains portfolio delta within safe bands:
- **Bands:** ±15 deltas (tighter at high VIX)
- **Hysteresis:** Exit at 60% of trigger to prevent oscillation
- **Action:** Buy options to neutralize directional risk

Example:
```
Net Delta: +300 (too long)
Action: Buy 4 lots of 35-delta PUTs
Result: Delta reduced to +8
```

### Daily Loss Kill-Switch

Hard stop to prevent catastrophic losses:
- **Threshold:** 1.5% of capital (default: ₹4,500 on ₹300,000)
- **Action:** Close all positions, lock system for the day

### Regime Adjustments

VIX-aware parameter scaling:
| VIX  | Position Size | Roll Delta | Stop Loss |
|------|--------------|------------|-----------|
| <15  | 100%         | 30         | 30%       |
| 15-20| 80%          | 27         | 27%       |
| 20-25| 60%          | 24         | 24%       |
| >25  | 30%          | 21         | 21%       |

See [Risk Policy Documentation](docs/risk_policy.md) for details.

## Configuration

All parameters in `strangle/config.py`:

### Basic Settings
```python
CAPITAL = 300000  # Trading capital
BASE_LOTS = 2  # Base position size
PAPER_TRADING = True  # Safe mode
```

### Risk Management
```python
# Daily loss limit
DAILY_MAX_LOSS_PCT = 0.015  # 1.5% of capital

# VIX shock detection
VIX_SHOCK_ABS = 4.0  # Points
VIX_SHOCK_ROC_PCT = 15.0  # Percentage

# Delta bands
DELTA_BAND_BASE = 15.0  # ±15 deltas

# Cooldown
ADJUSTMENT_COOLDOWN_SEC = 900  # 15 minutes
```

### Strategy Params
```python
# Stop loss
HARD_STOP_MULTIPLIER = 0.25  # 30% loss

# Roll trigger
ROLL_TRIGGER_DELTA = 30  # Roll at delta 30

# Profit target
PROFIT_TARGET_PCT = 50.0  # 50% profit
```

## Project Structure

```
AlgoStrangle/
├── strangle/                    # Core modules
│   ├── config.py               # Configuration (load from env)
│   ├── risk_policy.py          # Portfolio risk manager (NEW)
│   ├── trade_manager.py        # Position management
│   ├── strategy.py             # Trading logic
│   ├── broker.py               # Kite Connect interface
│   ├── models.py               # Data models (Trade, Greeks, etc.)
│   ├── notifier.py             # Telegram notifications
│   ├── greeks_calculator.py    # Black-Scholes Greeks
│   └── ...
├── tests/                      # Unit tests (NEW)
│   └── test_risk_policy.py    # Risk manager tests
├── docs/                       # Documentation (NEW)
│   ├── risk_policy.md          # Risk management details
│   ├── environment_setup.md    # Env var setup guide
│   └── backtest_guide.md       # Backtesting guide
├── logs/                       # Generated logs
│   ├── main_logs/              # Execution logs
│   ├── trades/                 # Trade CSVs
│   ├── performance/            # Daily performance
│   └── data/                   # Backtest data
├── run.py                      # Main entry point
└── .env                        # Environment variables (create this)
```

## Testing

### Run Unit Tests

```bash
python tests/test_risk_policy.py
```

Expected output:
```
============================================================
PORTFOLIO RISK MANAGER - UNIT TESTS
============================================================

=== Test: VIX Shock - Absolute Threshold ===
✓ VIX shock detected...

...

============================================================
TEST RESULTS: 11 passed, 0 failed
============================================================
```

### Run Backtest Scenarios

See [Backtest Guide](docs/backtest_guide.md) for detailed scenarios.

## Notifications

Configure Telegram for real-time alerts:

1. **Create bot:** Message [@BotFather](https://t.me/botfather)
2. **Get chat ID:** Message [@userinfobot](https://t.me/userinfobot)
3. **Set env vars:**
   ```bash
   export TELEGRAM_BOT_TOKEN="your_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   ```

Notification types:
- 📊 Trade entries/exits
- 🛑 Stop losses triggered
- 🎯 Profit targets hit
- ⚠️ VIX shocks detected
- 🔄 Delta hedges placed
- 🚨 Daily stop triggered

## Output Files

### Trade History
`logs/trades/backtest_trades_*.csv`
```csv
trade_id,symbol,entry_price,exit_price,pnl,exit_reason,trade_type
T001,NIFTY24000CE,100,80,3000,PROFIT_TARGET,BASE
T002,NIFTY24100PE,45,40,-750,TIME_SQUARE_OFF,HEDGE
```

### Daily Performance
`logs/performance/backtest_daily_performance_*.csv`
```csv
date,trades,win_rate,pnl,max_drawdown,risk_events
2024-06-03,3,66.7,1500,500,0
2024-06-04,2,50.0,-2000,2000,VIX_SHOCK
```

### Logs
`logs/main_logs/strangle_trading_*.log`
- Detailed execution log
- Risk events
- Greek calculations
- Order flow

## Performance Metrics

Typical backtest results (2024-06-01 to 2024-06-30):
- **Total Trades:** 45
- **Win Rate:** 67%
- **Total P&L:** ₹12,345
- **Max Drawdown:** ₹3,456 (1.2%)
- **Sharpe Ratio:** 1.4
- **VIX Shocks Handled:** 3
- **Delta Hedges:** 5
- **Daily Stops:** 0

## Security

### ✅ Best Practices
- Environment variables for all credentials
- `.env` file in `.gitignore`
- No hard-coded secrets in code
- Separate dev/prod credentials

### 🚫 Never Commit
- `.env` files
- API keys
- Access tokens
- Database files with live data

See [Environment Setup Guide](docs/environment_setup.md).

## Troubleshooting

### "KITE_API_KEY not set" Warning

**For Backtest:** Ignore - backtests work without credentials

**For Live Trading:** Set environment variables:
```bash
export KITE_API_KEY="your_key"
export KITE_API_SECRET="your_secret"
```

### Telegram Not Working

1. Verify env vars are set:
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```
2. Check bot is active (message it on Telegram)
3. Verify chat ID is numeric

### No Risk Events in Backtest

1. Choose date range with volatility (e.g., 2024-06-03 to 2024-06-14)
2. Check thresholds aren't too high
3. Verify capital setting matches

### Backtest Crashes

1. Clear cache: `rm -rf back_test_cache/*`
2. Force refresh data in backtest menu
3. Check logs: `tail -f logs/main_logs/*.log`

## Roadmap

- [ ] Machine learning for strike selection
- [ ] Multi-asset support (BANKNIFTY, FINNIFTY)
- [ ] Web dashboard for monitoring
- [ ] Cloud deployment guide
- [ ] Automated parameter optimization
- [ ] Risk-parity position sizing

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

This project is for educational purposes. Use at your own risk.

## Disclaimer

**⚠️ RISK WARNING**

Trading derivatives involves substantial risk of loss. Past performance does not guarantee future results. This software is provided "as-is" without warranty. The authors are not responsible for any trading losses.

Always:
- Test thoroughly in paper trading mode first
- Start with small position sizes
- Never risk more than you can afford to lose
- Monitor positions actively
- Have proper risk controls in place

## Support

- 📖 Documentation: See `docs/` folder
- 🐛 Issues: [GitHub Issues](https://github.com/vasanthk84/AlgoStrangle/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/vasanthk84/AlgoStrangle/discussions)

## Acknowledgments

- Kite Connect API by Zerodha
- Options pricing: Black-Scholes model
- Community contributors

---

**Built with ❤️ for algorithmic options traders**

Last Updated: 2025-10-31
