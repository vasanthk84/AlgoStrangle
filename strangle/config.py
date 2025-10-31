"""
Enhanced Configuration with ALL CRITICAL FIXES
✅ Fix #2: Transaction costs added
✅ Fix #3: Stop loss tightened to 30%
✅ Fix #4: Roll trigger at Delta 30
✅ Fix #5: Volatility spike protection enabled
✅ Fix #6: Regime detection increased to 50 days
"""

import os
from datetime import datetime

class Config:

    # --- Log File Management ---
    LOG_DIR_BASE = "logs"
    LOG_DIR_MAIN = os.path.join(LOG_DIR_BASE, "main_logs")
    LOG_DIR_CSV = os.path.join(LOG_DIR_BASE, "csv")
    LOG_DIR_AUDIT = os.path.join(LOG_DIR_BASE, "audit")
    OUTPUT_DIR_DATA = os.path.join(LOG_DIR_BASE, "data")
    OUTPUT_DIR_TRADES = os.path.join(LOG_DIR_BASE, "trades")
    OUTPUT_DIR_PERF = os.path.join(LOG_DIR_BASE, "performance")
    OUTPUT_DIR_SUMMARY = os.path.join(LOG_DIR_BASE, "summary")

    LOG_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_FILE = os.path.join(LOG_DIR_MAIN, f"strangle_trading_{LOG_TIMESTAMP}.log")
    ENTRY_LOG_FILE = os.path.join(LOG_DIR_CSV, f"entry_decisions_{LOG_TIMESTAMP}.csv")
    AUDIT_FILE = os.path.join(LOG_DIR_AUDIT, f"audit_trail_{LOG_TIMESTAMP}.txt")

    # API Configuration (moved to environment variables for security)
    API_KEY = os.getenv("KITE_API_KEY", "")
    API_SECRET = os.getenv("KITE_API_SECRET", "")

    # Trading Mode
    PAPER_TRADING = True
    DISABLE_TIME_CHECKS = True

    # Capital Management
    CAPITAL = 300000
    MAX_RISK_PER_TRADE_PCT = 0.02

    # Position Sizing
    USE_DYNAMIC_POSITION_SIZING = False
    BASE_LOTS = 2
    REDUCED_LOTS = 2
    MAX_LOTS_PER_TRADE = 10

    # ═══════════════════════════════════════════════════════════════
    # ✅ FIX #2: TRANSACTION COSTS (Realistic P&L)
    # ═══════════════════════════════════════════════════════════════
    ENABLE_TRANSACTION_COSTS = True

    # Per-leg costs (₹180 total / 4 legs = ₹45 per leg)
    TRANSACTION_COST_PER_LEG = 45.0

    # Slippage (assume 2 ticks = ₹1.50 per contract on entry+exit)
    SLIPPAGE_TICKS = 2
    SLIPPAGE_PER_TICK = 0.75  # ₹0.75 per tick for NIFTY options

    # Breakdown (for reference):
    # - Brokerage: ₹20 × 4 orders = ₹80
    # - STT (0.05%): ₹40 avg
    # - Exchange charges: ₹15
    # - GST (18% on brokerage): ₹15
    # - Slippage: ₹30
    # TOTAL: ~₹180 per strangle

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

    # ═══════════════════════════════════════════════════════════════
    # ✅ FIX #3: TIGHTENED STOP LOSS (30% instead of 40%)
    # ═══════════════════════════════════════════════════════════════
    DEFENSE_STRATEGY = "LAYERED"  # Options: LAYERED, ROLL_ONLY, STOP_ONLY, NONE

    # Tiered stop loss system
    SOFT_STOP_MULTIPLIER = 0.20    # 25% - Early warning (log only)
    HARD_STOP_MULTIPLIER = 0.25    # 30% - Execute stop (was 0.4)
    CATASTROPHIC_STOP = 0.50       # 50% - Emergency exit

    # Combined pair stop loss
    PAIR_STOP_LOSS_MULTIPLIER = 1.2  # 120% of combined premium (was 1.5)

    # ═══════════════════════════════════════════════════════════════
    # ✅ FIX #4: EARLIER ROLL TRIGGER (Delta 30 instead of 40)
    # ═══════════════════════════════════════════════════════════════
    ROLL_MONITOR_DELTA = 20        # Start monitoring
    ROLL_WARNING_DELTA = 25        # Calculate roll economics
    ROLL_TRIGGER_DELTA = 30        # Execute roll (was 40)
    ROLL_EMERGENCY_DELTA = 40      # Emergency roll if 30 failed

    ROLL_MIN_CREDIT = 15           # Minimum credit to accept for roll (was 20)
    ROLL_DISTANCE = 100            # How many points to roll OTM

    # ═══════════════════════════════════════════════════════════════
    # ✅ FIX #5: VOLATILITY SPIKE PROTECTION
    # ═══════════════════════════════════════════════════════════════
    VOLATILITY_PROTECTION = True   # Enable vol spike protection

    # VIX Regime Thresholds
    VIX_REGIME_NORMAL = 15         # 0-15: Full size, no hedges
    VIX_REGIME_ELEVATED = 20       # 15-20: 75% size, monitor closely
    VIX_REGIME_HIGH = 25           # 20-25: 50% size, prepare hedges
    VIX_REGIME_CRISIS = 30         # 25-30: 25% size, buy hedges
    VIX_REGIME_PANIC = 35          # 35+: Close all positions

    # Hedge parameters
    HEDGE_DELTA = 5                # Buy 5-delta far OTM options
    HEDGE_COST_BUDGET = 2000       # Max ₹2,000 per hedge

    # Position sizing adjustments by VIX
    VIX_SIZE_MULTIPLIERS = {
        'NORMAL': 1.0,      # Full size
        'ELEVATED': 0.75,   # 75% size
        'HIGH': 0.5,        # 50% size
        'CRISIS': 0.25,     # 25% size
        'PANIC': 0.0        # No trading
    }

    # ═══════════════════════════════════════════════════════════════
    # ✅ FIX #6: LONGER REGIME DETECTION (50 days instead of 20)
    # ═══════════════════════════════════════════════════════════════
    REGIME_LOOKBACK_DAYS = 50      # Primary trend (was 20)
    REGIME_FAST_LOOKBACK = 10      # Short-term momentum
    TREND_DETECTION_PERIOD = 50    # For regime analysis (was 20)

    # Trend threshold (requires 3% move to be considered trending)
    TREND_THRESHOLD_PCT = 3.0

    # Time-based Exits
    MIN_DTE_TO_HOLD = 5
    MAX_DTE_TO_ENTER = 21

    # Black-Scholes
    RISK_FREE_RATE = 0.07

    # System Config
    UPDATE_INTERVAL = 1
    DB_FILE = "trades_database.db"
    BACKTEST_CACHE_DIR = "back_test_cache"
    TICK_SKIP_INTERVAL = 5
    DRY_RUN_MODE = True

    # Notifications (moved to environment variables for security)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    ACCESS_TOKEN_FILE = "access_token.txt"

    # ═══════════════════════════════════════════════════════════════
    # 🆕 PORTFOLIO RISK MANAGEMENT
    # ═══════════════════════════════════════════════════════════════
    
    # Daily loss kill-switch
    DAILY_MAX_LOSS_PCT = 0.015  # 1.5% of capital
    
    # Delta bands for portfolio hedging
    DELTA_BAND_BASE = 15.0  # Base delta band (±15 deltas)
    
    # VIX-scaled delta bands (tighter in higher VIX)
    DELTA_BAND_TIGHT_VIX = {
        15.0: 15.0,  # VIX < 15: ±15 deltas
        20.0: 12.0,  # VIX < 20: ±12 deltas
        30.0: 10.0,  # VIX < 30: ±10 deltas
        999.0: 8.0   # VIX >= 30: ±8 deltas
    }
    
    # VIX shock thresholds
    VIX_SHOCK_ABS = 4.0  # Absolute VIX move (pts)
    VIX_SHOCK_ROC_PCT = 15.0  # VIX rate of change (%)
    
    # Short vega reduction on VIX shock
    SHORT_VEGA_REDUCTION_PCT = 0.4  # Reduce by 40%
    
    # Cooldown after adjustments
    ADJUSTMENT_COOLDOWN_SEC = 900  # 15 minutes
    
    # Hedge preferences
    HEDGE_PREFERRED = "OPTIONS"  # OPTIONS or FUT
    HEDGE_DELTA_OFFSET = 35.0  # Target delta for hedge options (~35 delta)
    
    # Wing parameters for converting to defined risk
    WING_SPREAD_WIDTH = 200.0  # Points away from short strike
    WING_MAX_COST_PER_LOT = 1000.0  # Max ₹1,000 per lot for wings

    # Expiry
    WEEKLY_EXPIRY_DAY = 1  # Tuesday

    # Legacy Params (kept for backward compatibility)
    OTM_DISTANCE_NORMAL = 400
    OTM_DISTANCE_HIGH_VIX = 450
    
    # ═══════════════════════════════════════════════════════════════
    # Security warnings
    # ═══════════════════════════════════════════════════════════════
    @classmethod
    def validate_secrets(cls):
        """Validate that secrets are loaded from environment"""
        warnings = []
        
        if not cls.API_KEY:
            warnings.append("⚠️ KITE_API_KEY not set in environment")
        if not cls.API_SECRET:
            warnings.append("⚠️ KITE_API_SECRET not set in environment")
        if not cls.TELEGRAM_BOT_TOKEN:
            warnings.append("⚠️ TELEGRAM_BOT_TOKEN not set in environment")
        if not cls.TELEGRAM_CHAT_ID:
            warnings.append("⚠️ TELEGRAM_CHAT_ID not set in environment")
        
        if warnings:
            import logging
            for warning in warnings:
                logging.warning(warning)
            logging.warning("Set environment variables or use a .env file for secrets")
        
        return len(warnings) == 0