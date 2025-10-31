# AlgoStrangle - Automated Options Trading System

A sophisticated options trading system for NIFTY short strangles with portfolio-level risk management.

## Features

- **Automated Short Strangle Execution** - Regime-aware entry logic
- **Portfolio Risk Management** - VIX shock detection, delta hedging, daily loss limits
- **Dynamic Position Sizing** - VIX-based scaling
- **Risk Defense Layers**:
  - VIX spike protection with automatic position reduction
  - Portfolio delta monitoring with hysteresis-based hedging
  - Daily kill-switch to cap losses
  - Regime-aware parameter adjustments
- **Backtesting Engine** - Test strategies on historical data
- **Real-time Monitoring** - Console dashboard and Telegram alerts

## Quick Start

### 1. Installation

```bash
# Clone repository
git clone https://github.com/vasanthk84/AlgoStrangle.git
cd AlgoStrangle

# Install dependencies (if requirements.txt exists)
pip install -r requirements.txt

# Or install manually
pip install pandas numpy kiteconnect pytest python-dotenv colorama tabulate requests
```

### 2. Configure Environment Variables

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

```bash
# Kite Connect API
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here

# Telegram Notifications
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

**Security Note**: Never commit `.env` to version control. It's already in `.gitignore`.

### 3. Run Tests

```bash
# Install pytest if not already installed
pip install pytest

# Run unit tests
pytest tests/ -v

# Or use make (if Makefile exists)
make test
```

### 4. Run Backtest

```bash
# Backtest on VIX spike period
python run.py backtest --start 2024-06-03 --end 2024-06-14

# Backtest on trend day
python run.py backtest --start 2024-07-15 --end 2024-07-15

# Backtest on calm period
python run.py backtest --start 2024-05-01 --end 2024-05-15
```

Check `logs/` directory for results.

### 5. Paper Trading

```bash
# Dry run mode (no real orders)
python run.py --mode paper

# Live trading (use with caution!)
python run.py --mode live
```

## Configuration

Main configuration file: `strangle/config.py`

### Capital and Position Sizing
```python
CAPITAL = 300000
BASE_LOTS = 2
MAX_LOTS_PER_TRADE = 10
```

### Risk Management Parameters
```python
# Daily loss limit
DAILY_MAX_LOSS_PCT = 0.015  # 1.5% of capital

# Delta bands (VIX-scaled)
DELTA_BAND_BASE = 15.0

# VIX shock thresholds
VIX_SHOCK_ABS = 4.0          # Absolute move (pts)
VIX_SHOCK_ROC_PCT = 15.0     # Rate of change (%)

# Position reduction on shock
SHORT_VEGA_REDUCTION_PCT = 0.4  # 40%

# Cooldown after adjustments
ADJUSTMENT_COOLDOWN_SEC = 900  # 15 minutes
```

### Stop Loss and Roll Triggers
```python
HARD_STOP_MULTIPLIER = 0.25    # 30% loss
ROLL_TRIGGER_DELTA = 30        # Roll at delta 30
```

See `docs/risk_policy.md` for detailed explanation of all parameters.

## Project Structure

```
AlgoStrangle/
├── strangle/                # Core trading modules
│   ├── config.py           # Configuration (secrets via env)
│   ├── risk_policy.py      # Portfolio risk manager
│   ├── trade_manager.py    # Trade execution and P&L
│   ├── strategy.py         # Entry/exit logic
│   ├── broker.py           # Kite Connect interface
│   ├── models.py           # Data models (Trade, Greeks, etc.)
│   ├── notifier.py         # Telegram notifications
│   └── ...
├── tests/                   # Unit tests
│   └── test_risk_policy.py
├── docs/                    # Documentation
│   ├── risk_policy.md      # Risk management guide
│   └── backtest_readme.md  # Backtest guide
├── logs/                    # Log files (auto-created)
├── run.py                   # Main entry point
├── .env.example            # Environment template
└── README.md               # This file
```

## Risk Management

The system includes multiple safety layers:

### 1. VIX Shock Detection
Automatically detects volatility spikes and:
- Reduces short vega exposure by 40%
- Converts naked strangles to defined-risk spreads
- Pauses new entries for cooldown period

### 2. Delta Hedging
Maintains portfolio delta neutrality:
- Monitors net portfolio delta
- Places hedges when delta exceeds VIX-scaled bands
- Uses hysteresis to prevent excessive trading

### 3. Daily Kill-Switch
Caps daily losses:
- Triggers when daily P&L ≤ -1.5% of capital
- Closes all positions immediately
- Blocks entries for rest of trading day

### 4. Regime Awareness
Adjusts parameters based on VIX:
- High VIX → smaller size, wider strikes, tighter stops
- Low VIX → normal sizing and parameters

See `docs/risk_policy.md` for examples and detailed explanations.

## Notifications

The system sends Telegram alerts for:
- Trade entries and exits
- Profit targets and stop losses
- VIX shocks and risk actions
- Delta hedges placed
- Daily kill-switch triggered
- Daily summary

## Testing

### Unit Tests
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_risk_policy.py -v

# Run with coverage
pytest tests/ --cov=strangle --cov-report=html
```

### Backtesting

See `docs/backtest_readme.md` for detailed backtesting guide.

Key backtest scenarios:
1. **VIX Spike** (June 2024) - Tests shock detection and vega reduction
2. **Trend Day** - Tests delta hedging and rolling
3. **Calm Period** - Baseline performance

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `KITE_API_KEY` | Kite Connect API key | Yes (for live/paper) |
| `KITE_API_SECRET` | Kite Connect API secret | Yes (for live/paper) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Optional |
| `TELEGRAM_CHAT_ID` | Telegram chat ID | Optional |

### Loading Environment Variables

**Option 1: python-dotenv (recommended)**
```bash
pip install python-dotenv
```
The system auto-loads `.env` if python-dotenv is installed.

**Option 2: Manual export**
```bash
export KITE_API_KEY="your_key"
export KITE_API_SECRET="your_secret"
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

## Logs and Output

Logs are written to `logs/` directory:

```
logs/
├── main_logs/              # Main system logs
│   └── strangle_trading_YYYYMMDD_HHMMSS.log
├── csv/                    # Entry decision logs (CSV)
├── audit/                  # Audit trail
├── trades/                 # Trade history
├── performance/            # Performance metrics
└── summary/                # Backtest summaries
```

## Troubleshooting

### API Key Errors
- Ensure `.env` file exists and has correct values
- Check environment variables are loaded: `echo $KITE_API_KEY`
- Verify API key is active on Kite Connect dashboard

### Telegram Not Working
- Verify bot token and chat ID are correct
- Test bot by sending `/start` to your bot on Telegram
- Check logs for connection errors

### Tests Failing
- Ensure all dependencies installed: `pip install pytest`
- Check Python version (3.8+ recommended)
- Run with verbose: `pytest tests/ -v -s`

### Backtest Issues
- Ensure historical data available in cache
- Check date ranges are valid (weekdays only)
- Verify VIX data present in backtest dataset

## Contributing

1. Create a feature branch
2. Make changes
3. Run tests: `pytest tests/ -v`
4. Commit with descriptive message
5. Open pull request

## Disclaimer

This software is for educational purposes only. Options trading involves substantial risk of loss. Past performance does not guarantee future results. Use at your own risk.

## License

See LICENSE file for details.

## Support

- Documentation: `docs/` directory
- Issues: GitHub Issues
- Contact: [Repository owner]

---

**Remember**: Always test with paper trading before going live!
