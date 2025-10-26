"""
Enhanced Configuration with Delta-Based Strategy
FIXED: Added specific output directories for final backtest CSV exports within /logs.
"""

import os
from datetime import datetime

class Config:

    # --- Log File Management ---
    LOG_DIR_BASE = "logs"
    LOG_DIR_MAIN = os.path.join(LOG_DIR_BASE, "main_logs")
    LOG_DIR_CSV = os.path.join(LOG_DIR_BASE, "csv") # For runtime entry decisions
    LOG_DIR_AUDIT = os.path.join(LOG_DIR_BASE, "audit")

    # --- FIX: Added Output Directories for Final Backtest CSVs ---
    OUTPUT_DIR_DATA = os.path.join(LOG_DIR_BASE, "data") # For backtest_data_production.csv
    OUTPUT_DIR_TRADES = os.path.join(LOG_DIR_BASE, "trades") # For backtest_trades_*.csv
    OUTPUT_DIR_PERF = os.path.join(LOG_DIR_BASE, "performance") # For backtest_daily_performance_*.csv
    OUTPUT_DIR_SUMMARY = os.path.join(LOG_DIR_BASE, "summary") # For final copied entry decisions
    # --- End Fix ---

    # Create directories (moved back here for simplicity, will be created early in run.py)
    # Note: run.py MUST ensure these are created before use.

    LOG_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

    LOG_FILE = os.path.join(LOG_DIR_MAIN, f"strangle_trading_{LOG_TIMESTAMP}.log")
    ENTRY_LOG_FILE = os.path.join(LOG_DIR_CSV, f"entry_decisions_{LOG_TIMESTAMP}.csv")
    AUDIT_FILE = os.path.join(LOG_DIR_AUDIT, f"audit_trail_{LOG_TIMESTAMP}.txt")

    # API Configuration
    API_KEY = "qdss2yswc2iuen3j"
    API_SECRET = "q9cfy774cgt8z0exp0tlat4rntj7huqs"

    # Trading Mode
    PAPER_TRADING = True

    # Capital Management
    CAPITAL = 1000000
    MAX_RISK_PER_TRADE_PCT = 0.02

    # Position Sizing (lots)
    BASE_LOTS = 10
    REDUCED_LOTS = 5
    MAX_LOTS_PER_TRADE = 10

    # VIX Thresholds
    VIX_THRESHOLD = 12.0
    VIX_HIGH_THRESHOLD = 18.0
    VIX_LOW_THRESHOLD = 8.0

    # Market Timing
    MARKET_START = "09:15:00"
    MARKET_END = "15:30:00"
    ENTRY_START = "09:30:00"
    ENTRY_STOP = "14:30:00"
    SQUARE_OFF_TIME = "15:20:00"

    # Profit/Loss Targets
    PROFIT_TARGET_PCT = 50.0
    LEG_STOP_LOSS_MULTIPLIER = 2.0
    PAIR_STOP_LOSS_MULTIPLIER = 1.5

    # Time-based Exits
    MIN_DTE_TO_HOLD = 5
    MAX_DTE_TO_ENTER = 21

    # Rolling/Adjustments
    ENABLE_ROLLING = True
    ROLL_TRIGGER_DELTA = 40
    ROLL_MIN_CREDIT = 20

    # Position Defense
    ENABLE_HEDGE = True
    HEDGE_TRIGGER_LOSS_PCT = 100
    HEDGE_DELTA_OFFSET = 5

    # Black-Scholes
    RISK_FREE_RATE = 0.07

    # System Config
    UPDATE_INTERVAL = 1
    DB_FILE = "trades_database.db" # Keep DB in root
    BACKTEST_CACHE_DIR = "back_test_cache"

    # Notifications
    TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"
    TELEGRAM_CHAT_ID = "your_chat_id"
    ACCESS_TOKEN_FILE = "access_token.txt"

    # Expiry
    WEEKLY_EXPIRY_DAY = 1

    # Legacy Params
    OTM_DISTANCE_NORMAL = 400
    OTM_DISTANCE_HIGH_VIX = 450

    # Regime Detection
    REGIME_LOOKBACK_DAYS = 20
    TREND_DETECTION_PERIOD = 20