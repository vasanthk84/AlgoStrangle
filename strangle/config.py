"""
Configuration settings for the Short Strangle Trading System
"""


class Config:
    API_KEY = "qdss2yswc2iuen3j"
    API_SECRET = "q9cfy774cgt8z0exp0tlat4rntj7huqs"
    PAPER_TRADING = True
    CAPITAL = 1000000
    BASE_LOTS = 50
    REDUCED_LOTS = 25
    VIX_THRESHOLD = 20.0
    MARKET_START = "09:15:00"
    MARKET_END = "15:30:00"
    ENTRY_START = "09:30:00"
    ENTRY_STOP = "14:30:00"
    SQUARE_OFF = "15:15:00"
    STOP_LOSS_PCT = 0.25
    TRAILING_STOP_PCT = 0.15
    MIN_COMBINED_PREMIUM = 50
    MAX_COMBINED_PREMIUM = 200
    OTM_DISTANCE_NORMAL = 250
    OTM_DISTANCE_HIGH_VIX = 350
    UPDATE_INTERVAL = 1
    PROFIT_TARGET_PCT = 0.50
    MAX_LOSS_ONE_LEG_PCT = 1.50
    ROLL_THRESHOLD_PCT = 0.75
    MIN_IV_PERCENTILE = 30
    MAX_IV_PERCENTILE = 80
    # ADJUSTED FOR LOW VIX REGIMES
    VIX_HIGH_THRESHOLD = 18.0  # Lowered from 25.0
    VIX_LOW_THRESHOLD = 10.0  # Lowered from 15.0
    # NOTE: As per SEBI guidelines, NIFTY weekly expiry is now TUESDAY (not Thursday)
    DB_FILE = "trades_database.db"
    LOG_FILE = "strangle_trading.log"
    AUDIT_FILE = "audit_trail.txt"
    TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"
    TELEGRAM_CHAT_ID = "your_chat_id"
    ACCESS_TOKEN_FILE = "access_token.txt"
    BACKTEST_CACHE_DIR = "backtest_cache"
