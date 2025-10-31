"""
short_strangle_system_V4_PRODUCTION.py - LEGACY FILE (DEPRECATED)

⚠️ WARNING: This is a legacy file kept for reference only.
⚠️ Use run.py instead, which has the latest features and security updates.

Enhanced Short Strangle NIFTY Options Trading System with Production-Quality Backtesting

SECURITY NOTE: This file contains hard-coded credentials.
DO NOT USE THIS FILE. Use run.py with environment variables instead.
"""

import sys
import os

# Immediately warn and exit
print("\n" + "="*80)
print("⚠️  WARNING: This is a LEGACY file with hard-coded credentials")
print("="*80)
print("\nThis file is DEPRECATED and should not be used.")
print("Please use run.py instead:")
print("  python run.py")
print("\nFor security, set environment variables for credentials:")
print("  export KITE_API_KEY='your_key'")
print("  export KITE_API_SECRET='your_secret'")
print("\nSee docs/environment_setup.md for details.")
print("="*80 + "\n")
sys.exit(1)

# Legacy code below (NOT EXECUTED due to sys.exit above)

import time
import logging
from datetime import datetime, date, time as dt_time
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum
import pandas as pd
import numpy as np
from colorama import Fore, Style
from tabulate import tabulate
import sqlite3
import requests
import webbrowser
from kiteconnect import KiteConnect
from pathlib import Path

# Import historical data manager
from historical_data_manager import HistoricalDataManager


class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"


class Config:
    # DEPRECATED: Hard-coded credentials (DO NOT USE)
    API_KEY = "DEPRECATED_USE_ENV_VARS"
    API_SECRET = "DEPRECATED_USE_ENV_VARS"
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


class MarketData:
    def __init__(self, **kwargs):
        self.nifty_spot = kwargs.get('nifty_spot', 0.0)
        self.nifty_future = kwargs.get('nifty_future', 0.0)
        self.nifty_open = kwargs.get('nifty_open', 0.0)
        self.nifty_high = kwargs.get('nifty_high', 0.0)
        self.nifty_low = kwargs.get('nifty_low', 0.0)
        self.india_vix = kwargs.get('india_vix', 0.0)
        self.vix_30day_avg = kwargs.get('vix_30day_avg', 0.0)
        self.banknifty_spot = kwargs.get('banknifty_spot', 0.0)
        self.banknifty_open = kwargs.get('banknifty_open', 0.0)
        self.banknifty_high = kwargs.get('banknifty_high', 0.0)
        self.banknifty_low = kwargs.get('banknifty_low', 0.0)
        self.sensex_spot = kwargs.get('sensex_spot', 0.0)
        self.advance_decline_ratio = kwargs.get('advance_decline_ratio', 0.0)
        self.timestamp = kwargs.get('timestamp', datetime.now())
        self.iv_percentile = kwargs.get('iv_percentile', 50.0)
        self.atm_iv = kwargs.get('atm_iv', 0.0)
        self.iv_rank = kwargs.get('iv_rank', 50.0)


class Trade:
    def __init__(self, trade_id: str, symbol: str, qty: int, direction: Direction, price: float,
                 timestamp: datetime, option_type: str):
        self.trade_id = trade_id
        self.symbol = symbol
        self.qty = qty
        self.direction = direction
        self.entry_price = price
        self.current_price = price
        self.timestamp = timestamp
        self.option_type = option_type
        self.slippage = 0.0
        self.greeks = None
        self.highest_profit = 0.0
        self.trailing_stop_price = None
        self.strike_price = self._extract_strike_from_symbol(symbol)
        self.rolled_from = None

    def _extract_strike_from_symbol(self, symbol: str) -> float:
        """Extract strike price from option symbol"""
        try:
            import re
            match = re.search(r'(\d{5,})(CE|PE)$', symbol)
            if match:
                return float(match.group(1))
        except:
            pass
        return 0.0

    def update_price(self, price: float):
        self.current_price = price
        self.slippage = abs(self.current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0.0
        current_pnl = self.get_pnl()
        if current_pnl > self.highest_profit:
            self.highest_profit = current_pnl

    def get_pnl(self) -> float:
        return (self.entry_price - self.current_price) * self.qty * (1 if self.direction == Direction.SELL else -1)

    def get_pnl_pct(self) -> float:
        """Get P&L as percentage of entry premium"""
        if self.entry_price == 0:
            return 0.0
        return (self.get_pnl() / (self.entry_price * self.qty)) * 100


class DatabaseManager:
    def __init__(self, db_file: str):
        self.conn = sqlite3.connect(db_file)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS trades
                       (
                           trade_id
                           TEXT
                           PRIMARY
                           KEY,
                           symbol
                           TEXT,
                           qty
                           INTEGER,
                           direction
                           TEXT,
                           entry_price
                           REAL,
                           exit_price
                           REAL,
                           entry_time
                           TEXT,
                           exit_time
                           TEXT,
                           option_type
                           TEXT,
                           pnl
                           REAL,
                           strike_price
                           REAL,
                           rolled_from
                           TEXT
                       )
                       ''')
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS daily_performance
                       (
                           date
                           TEXT
                           PRIMARY
                           KEY,
                           total_trades
                           INTEGER,
                           win_trades
                           INTEGER,
                           total_pnl
                           REAL,
                           ce_pnl
                           REAL,
                           pe_pnl
                           REAL,
                           max_drawdown
                           REAL,
                           profit_factor
                           REAL,
                           sharpe_ratio
                           REAL,
                           rolled_positions
                           INTEGER
                       )
                       ''')
        self.conn.commit()

    def save_trade(self, trade: Trade, exit_price: float = None, exit_time: datetime = None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO trades 
            (trade_id, symbol, qty, direction, entry_price, exit_price, entry_time, exit_time, 
             option_type, pnl, strike_price, rolled_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade.trade_id, trade.symbol, trade.qty, trade.direction.value,
            trade.entry_price, exit_price,
            trade.timestamp.isoformat(),
            exit_time.isoformat() if exit_time else None,
            trade.option_type,
            trade.get_pnl() if exit_price else None,
            trade.strike_price,
            trade.rolled_from
        ))
        self.conn.commit()

    def save_daily_performance(self, date_str: str, metrics: Any):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO daily_performance 
            (date, total_trades, win_trades, total_pnl, ce_pnl, pe_pnl, max_drawdown, 
             profit_factor, sharpe_ratio, rolled_positions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str, metrics.total_trades, metrics.win_trades, metrics.total_pnl,
            metrics.ce_pnl, metrics.pe_pnl, metrics.max_drawdown,
            metrics.profit_factor, metrics.sharpe_ratio, metrics.rolled_positions
        ))
        self.conn.commit()

    def get_performance_history(self, days: int = 30) -> pd.DataFrame:
        query = f"SELECT * FROM daily_performance ORDER BY date DESC LIMIT {days}"
        return pd.read_sql_query(query, self.conn)

    def get_all_trades(self) -> pd.DataFrame:
        query = "SELECT * FROM trades ORDER BY entry_time"
        return pd.read_sql_query(query, self.conn)

    def close(self):
        self.conn.close()


class NotificationManager:
    def __init__(self):
        self.bot_token = Config.TELEGRAM_BOT_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID

    def send_alert(self, message: str, level: str):
        if self.bot_token == "your_telegram_bot_token":
            return  # Skip if not configured
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': f"{level}: {message}",
                'parse_mode': 'HTML'
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()
        except Exception as e:
            logging.error(f"Failed to send Telegram alert: {e}")

    def send_daily_summary(self, metrics: Any):
        message = (
            f"<b>Daily Summary</b>\n"
            f"Total Trades: {metrics.total_trades}\n"
            f"Win Rate: {metrics.win_rate:.1f}%\n"
            f"Total P&L: Rs.{metrics.total_pnl:,.2f}\n"
            f"CE P&L: Rs.{metrics.ce_pnl:,.2f}\n"
            f"PE P&L: Rs.{metrics.pe_pnl:,.2f}\n"
            f"Profit Factor: {metrics.profit_factor:.2f}"
        )
        self.send_alert(message, "INFO")


class Utils:
    @staticmethod
    def get_now(backtest_timestamp: Optional[datetime] = None) -> datetime:
        return backtest_timestamp if backtest_timestamp is not None else datetime.now()

    @staticmethod
    def is_market_hours(backtest_timestamp: Optional[datetime] = None) -> bool:
        now = Utils.get_now(backtest_timestamp).time()
        start = dt_time.fromisoformat(Config.MARKET_START)
        end = dt_time.fromisoformat(Config.MARKET_END)
        return start <= now <= end

    @staticmethod
    def is_entry_window(backtest_timestamp: Optional[datetime] = None) -> bool:
        now = Utils.get_now(backtest_timestamp).time()
        start = dt_time.fromisoformat(Config.ENTRY_START)
        stop = dt_time.fromisoformat(Config.ENTRY_STOP)
        return start <= now <= stop

    @staticmethod
    def is_square_off_time(backtest_timestamp: Optional[datetime] = None) -> bool:
        now = Utils.get_now(backtest_timestamp).time()
        square_off = dt_time.fromisoformat(Config.SQUARE_OFF)
        return now >= square_off

    @staticmethod
    def is_holiday(backtest_date: Optional[date] = None) -> bool:
        if backtest_date:
            return backtest_date.weekday() in [5, 6]
        today = datetime.now().date()
        return today.weekday() in [5, 6]

    @staticmethod
    def generate_id() -> str:
        return str(np.random.randint(100000, 999999))

    @staticmethod
    def prepare_option_symbol(strike: float, option_type: str, expiry: date) -> str:
        expiry_str = expiry.strftime("%y%b").upper()
        strike_str = str(int(strike))
        return f"NIFTY{expiry_str}{strike_str}{option_type}"


class BrokerInterface:
    def __init__(self, backtest_data: pd.DataFrame = None):
        self.kite = KiteConnect(api_key=Config.API_KEY)
        self.backtest_data = backtest_data
        self.current_index = 0
        self.access_token_expiry = None

    def authenticate(self):
        if self.backtest_data is not None:
            logging.info("Backtesting mode: Using historical data")
            return True
        try:
            token_file = Path(Config.ACCESS_TOKEN_FILE)
            if token_file.exists():
                with open(token_file, "r") as f:
                    access_token, expiry = f.read().split(",")
                    expiry = pd.to_datetime(expiry)
                    if expiry > datetime.now():
                        self.kite.set_access_token(access_token)
                        self.kite.profile()
                        self.access_token_expiry = expiry
                        logging.info("Loaded valid access token from file")
                        return True
            logging.info("Generating new access token")
            print(f"Visit this URL to authenticate: {self.kite.login_url()}")
            webbrowser.open(self.kite.login_url())
            request_token = input("Enter the request_token from the URL after login: ").strip()
            data = self.kite.generate_session(request_token, api_secret=Config.API_SECRET)
            access_token = data["access_token"]
            expiry = (datetime.now() + pd.Timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            with open(token_file, "w") as f:
                f.write(f"{access_token},{expiry.isoformat()}")
            self.kite.set_access_token(access_token)
            self.access_token_expiry = expiry
            logging.info("Authentication successful")
            return True
        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            return False

    def get_quote(self, symbol: str) -> float:
        if self.backtest_data is not None:
            current_row = self.backtest_data.iloc[self.current_index]
            if symbol.startswith("NIFTY") and symbol.endswith("CE"):
                return current_row.get('ce_price', 0.0)
            elif symbol.startswith("NIFTY") and symbol.endswith("PE"):
                return current_row.get('pe_price', 0.0)
            return current_row.get('nifty_spot', 0.0)
        try:
            quote = self.kite.quote(symbol)
            return quote[symbol]['last_price']
        except Exception:
            logging.error(f"Failed to fetch quote for {symbol}")
            return 0.0

    def get_lot_size(self, symbol: str) -> int:
        return 50

    def get_market_data(self) -> MarketData:
        if self.backtest_data is not None:
            row = self.backtest_data.iloc[self.current_index]
            return MarketData(
                nifty_spot=row.get('nifty_spot', 0.0),
                nifty_future=row.get('nifty_future', 0.0),
                nifty_open=row.get('nifty_open', 0.0),
                nifty_high=row.get('nifty_high', 0.0),
                nifty_low=row.get('nifty_low', 0.0),
                india_vix=row.get('india_vix', 0.0),
                vix_30day_avg=row.get('vix_30day_avg', 0.0),
                timestamp=pd.to_datetime(row['timestamp'])
            )
        return MarketData()

    def place_order(self, symbol: str, qty: int, direction: Direction, price: float) -> str:
        if self.backtest_data is not None:
            logging.info(f"ORDER PLACED: {direction.value} {qty} of {symbol} @ Rs.{price:.2f}")
            return f"sim_order_{Utils.generate_id()}"
        try:
            order_id = self.kite.place_order(
                variety="regular",
                exchange="NFO",
                tradingsymbol=symbol,
                transaction_type=direction.value,
                quantity=qty,
                product="MIS",
                order_type="LIMIT",
                price=price
            )
            return order_id
        except Exception as e:
            logging.error(f"Order placement failed for {symbol}: {e}")
            return ""


class TradeManager:
    def __init__(self, broker: BrokerInterface, db: DatabaseManager, notifier: NotificationManager):
        self.broker = broker
        self.db = db
        self.notifier = notifier
        self.active_trades: Dict[str, Trade] = {}
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.win_trades = 0
        self.ce_pnl = 0.0
        self.pe_pnl = 0.0
        self.ce_trades = 0
        self.pe_trades = 0
        self.rolled_positions = 0
        self.daily_pnl_history = []

    def add_trade(self, trade: Trade):
        self.active_trades[trade.trade_id] = trade
        self.db.save_trade(trade)
        self.total_trades += 1
        if trade.option_type == "CE":
            self.ce_trades += 1
        else:
            self.pe_trades += 1
        logging.info(
            f"TRADE ENTERED: {trade.direction.value} {trade.qty} {trade.symbol} @ Rs.{trade.entry_price:.2f}"
        )
        self.notifier.send_alert(
            f"New Trade: {trade.direction.value} {trade.qty} {trade.symbol} @ Rs.{trade.entry_price:.2f}",
            "INFO"
        )

    def close_trade(self, trade_id: str, exit_price: float):
        if trade_id in self.active_trades:
            trade = self.active_trades[trade_id]
            trade.update_price(exit_price)
            pnl = trade.get_pnl()
            self.daily_pnl += pnl
            if trade.option_type == "CE":
                self.ce_pnl += pnl
            else:
                self.pe_pnl += pnl
            if pnl > 0:
                self.win_trades += 1
            self.db.save_trade(trade, exit_price, datetime.now())
            logging.info(f"TRADE CLOSED: {trade.symbol}, P&L: Rs.{pnl:,.2f}")
            self.notifier.send_alert(
                f"Closed Trade: {trade.symbol}, P&L: Rs.{pnl:,.2f}",
                "INFO" if pnl >= 0 else "WARNING"
            )
            del self.active_trades[trade_id]

    def get_leg_trades(self, option_type: str) -> List[Trade]:
        return [t for t in self.active_trades.values() if t.option_type == option_type]

    def get_leg_pnl(self, option_type: str) -> float:
        return sum(t.get_pnl() for t in self.get_leg_trades(option_type))

    def check_leg_stop_loss(self, option_type: str) -> bool:
        leg_trades = self.get_leg_trades(option_type)
        if not leg_trades:
            return False
        total_entry_premium = sum(t.entry_price * t.qty for t in leg_trades)
        if total_entry_premium == 0:
            return False
        leg_pnl = self.get_leg_pnl(option_type)
        loss_pct = abs(leg_pnl / total_entry_premium)
        return loss_pct >= Config.MAX_LOSS_ONE_LEG_PCT

    def reset_daily_metrics(self):
        """Reset metrics for new trading day"""
        self.daily_pnl_history.append(self.daily_pnl)
        self.daily_pnl = 0.0
        self.ce_pnl = 0.0
        self.pe_pnl = 0.0

    def get_performance_metrics(self) -> Any:
        class Metrics:
            pass

        metrics = Metrics()
        metrics.total_trades = self.total_trades
        metrics.win_trades = self.win_trades
        metrics.win_rate = (self.win_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        metrics.total_pnl = self.daily_pnl
        metrics.ce_pnl = self.ce_pnl
        metrics.pe_pnl = self.pe_pnl
        metrics.rolled_positions = self.rolled_positions

        # Calculate drawdown
        if self.daily_pnl_history:
            cumulative = np.cumsum(self.daily_pnl_history)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = cumulative - running_max
            metrics.max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0.0
        else:
            metrics.max_drawdown = 0.0

        # Calculate profit factor
        if self.daily_pnl_history:
            profits = [p for p in self.daily_pnl_history if p > 0]
            losses = [abs(p) for p in self.daily_pnl_history if p < 0]
            total_profit = sum(profits) if profits else 0
            total_loss = sum(losses) if losses else 1
            metrics.profit_factor = total_profit / total_loss if total_loss > 0 else 0.0
        else:
            metrics.profit_factor = 0.0

        # Calculate Sharpe ratio
        if len(self.daily_pnl_history) > 1:
            returns = np.array(self.daily_pnl_history)
            metrics.sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        else:
            metrics.sharpe_ratio = 0.0

        return metrics


class ShortStrangleStrategy:
    def __init__(self, broker: BrokerInterface, trade_manager: TradeManager, notifier: NotificationManager):
        self.broker = broker
        self.trade_manager = trade_manager
        self.notifier = notifier
        self.market_data = MarketData()
        self.vix_history = []
        self.entry_allowed_today = True
        # STATE TRACKING FOR SMART LOGGING
        self.last_entry_decision = None
        self.last_entry_reason = None
        self.entry_checks_today = 0

    def calculate_iv_percentile(self) -> float:
        if len(self.vix_history) < 30:
            self.vix_history.append(self.market_data.india_vix)
            return 50.0
        self.vix_history.append(self.market_data.india_vix)
        if len(self.vix_history) > 252:
            self.vix_history.pop(0)
        current_vix = self.market_data.india_vix
        below_current = sum(1 for v in self.vix_history if v < current_vix)
        percentile = (below_current / len(self.vix_history)) * 100
        return percentile

    def should_enter_trade(self) -> Tuple[bool, str]:
        vix = self.market_data.india_vix
        iv_percentile = self.calculate_iv_percentile()

        if vix < Config.VIX_LOW_THRESHOLD:
            reason = f"VIX too low ({vix:.2f} < {Config.VIX_LOW_THRESHOLD})"
            return False, reason
        if vix > Config.VIX_HIGH_THRESHOLD * 1.5:
            reason = f"VIX extremely high ({vix:.2f} > {Config.VIX_HIGH_THRESHOLD * 1.5})"
            return False, reason
        if iv_percentile < Config.MIN_IV_PERCENTILE:
            reason = f"IV percentile too low ({iv_percentile:.1f}% < {Config.MIN_IV_PERCENTILE}%)"
            return False, reason
        if iv_percentile > Config.MAX_IV_PERCENTILE:
            reason = f"IV percentile too high ({iv_percentile:.1f}% > {Config.MAX_IV_PERCENTILE}%)"
            return False, reason
        if len(self.trade_manager.active_trades) >= 2:
            reason = "Already have active positions"
            return False, reason

        reason = f"Entry approved - VIX: {vix:.2f}, IV Percentile: {iv_percentile:.1f}%"
        return True, reason

    def calculate_position_size(self, combined_premium: float) -> int:
        max_lots = Config.CAPITAL // (combined_premium * self.broker.get_lot_size("NIFTY") * 100)
        if self.market_data.india_vix > Config.VIX_THRESHOLD:
            return min(max_lots // 2, Config.REDUCED_LOTS)
        return min(max_lots, Config.BASE_LOTS)

    def select_strike(self, current_date: Optional[date] = None) -> Tuple[str, str]:
        spot = self.market_data.nifty_spot
        vix = self.market_data.india_vix

        if vix < Config.VIX_LOW_THRESHOLD:
            otm_distance = Config.OTM_DISTANCE_NORMAL - 50
        elif vix > Config.VIX_HIGH_THRESHOLD:
            otm_distance = Config.OTM_DISTANCE_HIGH_VIX + 100
        else:
            vix_range = Config.VIX_HIGH_THRESHOLD - Config.VIX_LOW_THRESHOLD
            vix_position = (vix - Config.VIX_LOW_THRESHOLD) / vix_range
            otm_distance = Config.OTM_DISTANCE_NORMAL + int(
                vix_position * (Config.OTM_DISTANCE_HIGH_VIX - Config.OTM_DISTANCE_NORMAL))

        ce_strike = round(spot / 50) * 50 + otm_distance
        pe_strike = round(spot / 50) * 50 - otm_distance

        # NEW SEBI RULES: Weekly expiry on TUESDAY (weekday 1), not Thursday
        # Calculate next Tuesday expiry
        current = pd.to_datetime(current_date or datetime.now())
        days_until_tuesday = (1 - current.weekday()) % 7  # Tuesday is weekday 1
        if days_until_tuesday == 0 and current.time() >= dt_time(15, 30):
            # If today is Tuesday after market close, get next Tuesday
            days_until_tuesday = 7
        expiry = (current + pd.Timedelta(days=days_until_tuesday)).date()

        ce_symbol = Utils.prepare_option_symbol(ce_strike, "CE", expiry)
        pe_symbol = Utils.prepare_option_symbol(pe_strike, "PE", expiry)

        logging.info(f"STRIKES SELECTED: CE={ce_strike}, PE={pe_strike}, OTM Distance={otm_distance}, VIX={vix:.2f}")
        return ce_symbol, pe_symbol

    def execute_entry(self, ce_symbol: str, pe_symbol: str, qty: int):
        ce_price = self.broker.get_quote(ce_symbol)
        pe_price = self.broker.get_quote(pe_symbol)
        combined_premium = ce_price + pe_price

        logging.info(f"ENTRY EXECUTION: CE={ce_price:.2f}, PE={pe_price:.2f}, Combined={combined_premium:.2f}")

        if Config.MIN_COMBINED_PREMIUM <= combined_premium <= Config.MAX_COMBINED_PREMIUM:
            for symbol, option_type in [(ce_symbol, "CE"), (pe_symbol, "PE")]:
                price = ce_price if option_type == "CE" else pe_price
                if price > 0:  # Only place order if valid price
                    order_id = self.broker.place_order(symbol, qty, Direction.SELL, price)
                    if order_id:
                        trade = Trade(order_id, symbol, qty, Direction.SELL, price, datetime.now(), option_type)
                        self.trade_manager.add_trade(trade)
        else:
            logging.warning(
                f"Combined premium Rs.{combined_premium:.2f} outside range [{Config.MIN_COMBINED_PREMIUM}, {Config.MAX_COMBINED_PREMIUM}]")

    def check_trailing_stop(self, trade: Trade) -> bool:
        pnl_pct = trade.get_pnl_pct()
        if pnl_pct > 0:
            required_trailing_level = trade.highest_profit * (1 - Config.TRAILING_STOP_PCT)
            if trade.trailing_stop_price is None or required_trailing_level > trade.trailing_stop_price:
                trade.trailing_stop_price = required_trailing_level
        if trade.trailing_stop_price is not None:
            current_pnl = trade.get_pnl()
            if current_pnl < trade.trailing_stop_price:
                logging.info(f"TRAILING STOP HIT: {trade.symbol}")
                return True
        return False

    def check_profit_target(self, trade: Trade) -> bool:
        pnl_pct = trade.get_pnl_pct()
        if pnl_pct >= Config.PROFIT_TARGET_PCT * 100:
            logging.info(f"PROFIT TARGET REACHED: {trade.symbol} at {pnl_pct:.1f}%")
            return True
        return False

    def should_roll_position(self, trade: Trade) -> bool:
        pnl_pct = trade.get_pnl_pct()
        if pnl_pct <= -Config.ROLL_THRESHOLD_PCT * 100 and trade.rolled_from is None:
            logging.info(f"ROLL THRESHOLD REACHED: {trade.symbol} at {pnl_pct:.1f}%")
            return True
        return False

    def roll_position(self, trade: Trade, current_date: Optional[date] = None):
        current_strike = trade.strike_price
        roll_distance = 100
        if trade.option_type == "CE":
            new_strike = current_strike + roll_distance
        else:
            new_strike = current_strike - roll_distance

        expiry = (pd.to_datetime(current_date or datetime.now()) + pd.Timedelta(
            days=7 - (current_date or datetime.now()).weekday())).date()
        new_symbol = Utils.prepare_option_symbol(new_strike, trade.option_type, expiry)
        new_price = self.broker.get_quote(new_symbol)

        if new_price > 0:
            exit_price = self.broker.get_quote(trade.symbol)
            self.trade_manager.close_trade(trade.trade_id, exit_price)

            order_id = self.broker.place_order(new_symbol, trade.qty, Direction.SELL, new_price)
            if order_id:
                new_trade = Trade(order_id, new_symbol, trade.qty, Direction.SELL, new_price,
                                  datetime.now(), trade.option_type)
                new_trade.rolled_from = trade.symbol
                self.trade_manager.add_trade(new_trade)
                self.trade_manager.rolled_positions += 1
                logging.info(f"POSITION ROLLED: {trade.symbol} -> {new_symbol}")

    def manage_active_positions(self, backtest_timestamp: Optional[datetime] = None):
        for trade_id in list(self.trade_manager.active_trades.keys()):
            trade = self.trade_manager.active_trades[trade_id]
            current_price = self.broker.get_quote(trade.symbol)
            if current_price > 0:
                trade.update_price(current_price)

            if self.check_profit_target(trade):
                exit_price = self.broker.get_quote(trade.symbol)
                if exit_price > 0:
                    self.trade_manager.close_trade(trade_id, exit_price)
                continue

            if self.check_trailing_stop(trade):
                exit_price = self.broker.get_quote(trade.symbol)
                if exit_price > 0:
                    self.trade_manager.close_trade(trade_id, exit_price)
                continue

            if self.should_roll_position(trade):
                self.roll_position(trade, backtest_timestamp.date() if backtest_timestamp else None)
                continue

        for option_type in ["CE", "PE"]:
            if self.trade_manager.check_leg_stop_loss(option_type):
                logging.warning(f"{option_type} LEG STOP LOSS HIT - Exiting all positions")
                for trade_id in list(self.trade_manager.active_trades.keys()):
                    trade = self.trade_manager.active_trades[trade_id]
                    exit_price = self.broker.get_quote(trade.symbol)
                    if exit_price > 0:
                        self.trade_manager.close_trade(trade_id, exit_price)
                break

    def run_cycle(self, backtest_timestamp: Optional[datetime] = None):
        self.market_data = self.broker.get_market_data()
        self.market_data.iv_percentile = self.calculate_iv_percentile()

        if Config.PAPER_TRADING or self.broker.backtest_data is not None or Utils.is_market_hours(backtest_timestamp):
            self.manage_active_positions(backtest_timestamp)

            if Utils.is_entry_window(backtest_timestamp) and self.entry_allowed_today:
                should_enter, reason = self.should_enter_trade()
                self.entry_checks_today += 1

                # SMART LOGGING: Only log when decision or reason changes
                if should_enter != self.last_entry_decision or reason != self.last_entry_reason:
                    logging.info(f"ENTRY EVALUATION: {reason}")
                    self.last_entry_decision = should_enter
                    self.last_entry_reason = reason

                if should_enter:
                    ce_symbol, pe_symbol = self.select_strike(backtest_timestamp.date() if backtest_timestamp else None)
                    combined_premium = self.broker.get_quote(ce_symbol) + self.broker.get_quote(pe_symbol)
                    if combined_premium > 0:
                        qty = self.calculate_position_size(combined_premium)
                        self.execute_entry(ce_symbol, pe_symbol, qty)
                        self.entry_allowed_today = False

            if Utils.is_square_off_time(backtest_timestamp):
                if self.trade_manager.active_trades:
                    logging.info("SQUARE OFF TIME - Closing all positions")
                for trade_id in list(self.trade_manager.active_trades.keys()):
                    trade = self.trade_manager.active_trades[trade_id]
                    exit_price = self.broker.get_quote(trade.symbol)
                    if exit_price > 0:
                        self.trade_manager.close_trade(trade_id, exit_price)

    def reset_daily_state(self):
        """Reset daily state for new trading day"""
        self.entry_allowed_today = True
        self.last_entry_decision = None
        self.last_entry_reason = None
        self.entry_checks_today = 0


class ConsoleDashboard:
    def __init__(self):
        self.last_update = 0

    def render(self, market_data: MarketData, trade_manager: TradeManager):
        if time.time() - self.last_update < 1:
            return
        print(f"\n{'=' * 80}")
        print(f"{Fore.CYAN}ENHANCED SHORT STRANGLE NIFTY OPTIONS{Style.RESET_ALL}")
        print(f"{'=' * 80}")
        data = [
            ["NIFTY Spot", f"{market_data.nifty_spot:.2f}"],
            ["India VIX", f"{market_data.india_vix:.2f}"],
            ["IV Percentile", f"{market_data.iv_percentile:.1f}%"],
            ["Active Trades", len(trade_manager.active_trades)],
            ["Daily P&L", f"Rs.{trade_manager.daily_pnl:,.2f}"],
            ["CE Leg P&L", f"Rs.{trade_manager.ce_pnl:,.2f}"],
            ["PE Leg P&L", f"Rs.{trade_manager.pe_pnl:,.2f}"],
            ["Rolled Positions", trade_manager.rolled_positions]
        ]
        print(tabulate(data, headers=["Metric", "Value"], tablefmt="grid"))

        if trade_manager.active_trades:
            print(f"\n{Fore.CYAN}Active Positions:{Style.RESET_ALL}")
            pos_data = []
            for trade in trade_manager.active_trades.values():
                pos_data.append([
                    trade.option_type,
                    trade.symbol,
                    f"Rs.{trade.entry_price:.2f}",
                    f"Rs.{trade.current_price:.2f}",
                    f"{trade.get_pnl_pct():.1f}%",
                    f"Rs.{trade.get_pnl():,.2f}",
                    f"Rs.{trade.trailing_stop_price:.2f}" if trade.trailing_stop_price else "N/A"
                ])
            print(tabulate(pos_data, headers=["Type", "Symbol", "Entry", "Current", "P&L%", "P&L", "Trail Stop"],
                           tablefmt="grid"))

        self.last_update = time.time()


def backtest_main(broker: BrokerInterface, start_date: str, end_date: str, force_refresh: bool = False):
    # Configure logging with UTF-8 encoding
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  ENHANCED SHORT STRANGLE NIFTY OPTIONS BACKTEST  {Style.RESET_ALL}
{Fore.CYAN}  Period: {start_date} to {end_date}  {Style.RESET_ALL}
{Fore.CYAN}  VIX Range: {Config.VIX_LOW_THRESHOLD} - {Config.VIX_HIGH_THRESHOLD} (Low VIX Regime)  {Style.RESET_ALL}
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
""")

    if not broker.authenticate():
        print(f"{Fore.RED}Authentication failed. Exiting backtest.{Style.RESET_ALL}")
        return

    # Initialize historical data manager
    data_manager = HistoricalDataManager(broker.kite, Config.BACKTEST_CACHE_DIR)

    # Define strike calculator function
    def calculate_strikes(spot: float, vix: float, current_date: date) -> Tuple[float, float, date]:
        """Calculate CE/PE strikes and expiry based on spot and VIX"""
        if vix > Config.VIX_THRESHOLD:
            otm_distance = Config.OTM_DISTANCE_HIGH_VIX
        else:
            otm_distance = Config.OTM_DISTANCE_NORMAL

        ce_strike = round(spot / 50) * 50 + otm_distance
        pe_strike = round(spot / 50) * 50 - otm_distance

        # NEW SEBI RULES: Weekly expiry on TUESDAY (weekday 1), not Thursday
        # Calculate next Tuesday expiry
        current = pd.to_datetime(current_date)
        days_until_tuesday = (1 - current.weekday()) % 7  # Tuesday is weekday 1
        if days_until_tuesday == 0 and current.time() >= pd.Timestamp('15:30').time():
            # If today is Tuesday after market close, get next Tuesday
            days_until_tuesday = 7
        expiry = (current + pd.Timedelta(days=days_until_tuesday)).date()

        return ce_strike, pe_strike, expiry

    print(f"{Fore.YELLOW}Downloading and preparing historical data...{Style.RESET_ALL}")
    print(f"Cache mode: {'REFRESH' if force_refresh else 'USE EXISTING'}")

    try:
        # Prepare backtest data
        backtest_data = data_manager.prepare_backtest_data(
            start_date, end_date, calculate_strikes, force_refresh
        )

        # Save to CSV for inspection
        output_file = "backtest_data_production.csv"
        backtest_data.to_csv(output_file, index=False)
        print(f"{Fore.GREEN}Backtest data saved to: {output_file}{Style.RESET_ALL}")
        print(f"Total data points: {len(backtest_data)}")
        print(f"Date range: {backtest_data['timestamp'].min()} to {backtest_data['timestamp'].max()}")

    except Exception as e:
        print(f"{Fore.RED}Failed to prepare backtest data: {e}{Style.RESET_ALL}")
        logging.error(f"Backtest data preparation failed: {e}", exc_info=True)
        return

    # Initialize trading components
    Config.PAPER_TRADING = True
    broker.backtest_data = backtest_data
    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    print(f"\n{Fore.CYAN}Starting backtest simulation...{Style.RESET_ALL}\n")

    # Run backtest day by day
    trading_days = pd.date_range(start_date, end_date, freq='D')
    total_days = len([d for d in trading_days if not Utils.is_holiday(d.date())])
    current_day = 0

    for current_date in trading_days:
        if Utils.is_holiday(current_date.date()):
            continue

        current_day += 1
        daily_data = backtest_data[backtest_data['timestamp'].dt.date == current_date.date()]
        if daily_data.empty:
            continue

        print(
            f"\n{Fore.YELLOW}[Day {current_day}/{total_days}] Trading Day: {current_date.strftime('%Y-%m-%d')}{Style.RESET_ALL}")

        # Reset daily state
        strategy.reset_daily_state()

        # Simulate intraday trading with progress indicator
        total_ticks = len(daily_data)
        last_progress = 0

        for idx, index in enumerate(daily_data.index):
            broker.current_index = index
            current_time = daily_data.loc[index, 'timestamp']

            strategy.run_cycle(current_time)

            # Show progress every 10%
            progress = int((idx / total_ticks) * 100)
            if progress >= last_progress + 10:
                print(f"  Progress: {progress}% | Time: {current_time.strftime('%H:%M')} | "
                      f"VIX: {strategy.market_data.india_vix:.2f} | "
                      f"Active Trades: {len(trade_manager.active_trades)}", end='\r')
                last_progress = progress

        print()  # New line after progress

        # End of day summary
        metrics = trade_manager.get_performance_metrics()
        db.save_daily_performance(current_date.strftime('%Y-%m-%d'), metrics)

        # Log daily results
        day_summary = (
            f"DAY SUMMARY: Trades={metrics.total_trades}, "
            f"Daily P&L=Rs.{trade_manager.daily_pnl:,.2f}, "
            f"CE=Rs.{metrics.ce_pnl:,.2f}, PE=Rs.{metrics.pe_pnl:,.2f}, "
            f"Entry Checks={strategy.entry_checks_today}"
        )
        logging.info(day_summary)
        print(f"  {day_summary}")

        # Reset daily metrics for next day
        trade_manager.reset_daily_metrics()

    # Final backtest summary
    print(f"\n{'=' * 80}")
    print(f"{Fore.CYAN}BACKTEST SUMMARY - {start_date} to {end_date}{Style.RESET_ALL}")
    print(f"{'=' * 80}")

    final_metrics = trade_manager.get_performance_metrics()
    cumulative_pnl = sum(trade_manager.daily_pnl_history)

    summary_data = [
        ["Total Trades", final_metrics.total_trades],
        ["Win Trades", final_metrics.win_trades],
        ["Win Rate", f"{final_metrics.win_rate:.1f}%"],
        ["Cumulative P&L", f"Rs.{cumulative_pnl:,.2f}"],
        ["Max Drawdown", f"Rs.{final_metrics.max_drawdown:,.2f}"],
        ["Profit Factor", f"{final_metrics.profit_factor:.2f}"],
        ["Sharpe Ratio", f"{final_metrics.sharpe_ratio:.2f}"],
        ["Rolled Positions", final_metrics.rolled_positions],
        ["Trading Days", len(trade_manager.daily_pnl_history)],
        ["Avg Daily P&L",
         f"Rs.{cumulative_pnl / len(trade_manager.daily_pnl_history):,.2f}" if trade_manager.daily_pnl_history else "N/A"]
    ]
    print(tabulate(summary_data, headers=["Metric", "Value"], tablefmt="grid"))

    # Show P&L distribution
    if trade_manager.daily_pnl_history:
        print(f"\n{Fore.CYAN}Daily P&L Distribution:{Style.RESET_ALL}")
        daily_pnl_array = np.array(trade_manager.daily_pnl_history)
        print(f"  Min Daily P&L: Rs.{np.min(daily_pnl_array):,.2f}")
        print(f"  Max Daily P&L: Rs.{np.max(daily_pnl_array):,.2f}")
        print(f"  Median Daily P&L: Rs.{np.median(daily_pnl_array):,.2f}")
        print(f"  Std Dev: Rs.{np.std(daily_pnl_array):,.2f}")

        winning_days = len([p for p in daily_pnl_array if p > 0])
        total_days = len(daily_pnl_array)
        print(f"  Winning Days: {winning_days}/{total_days} ({winning_days / total_days * 100:.1f}%)")

    # Export detailed results
    print(f"\n{Fore.GREEN}Exported Files:{Style.RESET_ALL}")
    print(f"  Database: {Config.DB_FILE}")
    print(f"  Backtest Data: backtest_data_production.csv")
    print(f"  Log File: {Config.LOG_FILE}")

    # Export trades to CSV
    all_trades = db.get_all_trades()
    if not all_trades.empty:
        trades_file = f"backtest_trades_{start_date}_to_{end_date}.csv"
        all_trades.to_csv(trades_file, index=False)
        print(f"  All Trades: {trades_file}")

    # Export daily performance
    daily_perf = db.get_performance_history(days=1000)
    if not daily_perf.empty:
        perf_file = f"backtest_daily_performance_{start_date}_to_{end_date}.csv"
        daily_perf.to_csv(perf_file, index=False)
        print(f"  Daily Performance: {perf_file}")

    print(f"\n{Fore.GREEN}Backtest completed successfully!{Style.RESET_ALL}\n")

    db.close()


def main():
    # Configure logging with UTF-8 encoding
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  ENHANCED SHORT STRANGLE NIFTY OPTIONS TRADING SYSTEM  {Style.RESET_ALL}
{Fore.CYAN}  Version 4.0 - Production Backtest Edition (FIXED)  {Style.RESET_ALL}
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
""")

    print("\nSelect Trading Mode:")
    print("1. Paper Trading (Default)")
    print("2. Live Trading")
    print("3. Backtest Mode")
    mode = input("Enter choice (1/2/3): ").strip() or "1"

    broker = BrokerInterface()

    if mode == "3":
        print(f"\n{Fore.CYAN}BACKTEST MODE{Style.RESET_ALL}")
        start_date = input("Enter start date (YYYY-MM-DD): ").strip()
        end_date = input("Enter end date (YYYY-MM-DD): ").strip()

        # Validate dates
        try:
            pd.to_datetime(start_date)
            pd.to_datetime(end_date)
        except ValueError:
            print(f"{Fore.RED}Invalid date format. Please use YYYY-MM-DD{Style.RESET_ALL}")
            return

        # Ask about cache refresh
        refresh_input = input("Force refresh cached data? (yes/no, default: no): ").strip().lower()
        force_refresh = refresh_input == "yes"

        backtest_main(broker, start_date, end_date, force_refresh)
        return

    if mode == "2":
        confirm = input(
            f"{Fore.YELLOW}You selected LIVE TRADING. This will place real orders. Confirm (yes/no)? {Style.RESET_ALL}"
        ).lower()
        if confirm != "yes":
            print(f"{Fore.YELLOW}Live trading cancelled. Exiting.{Style.RESET_ALL}")
            return
        Config.PAPER_TRADING = False

    if Utils.is_holiday():
        print(f"{Fore.YELLOW}Today is a holiday. Exiting.{Style.RESET_ALL}")
        return

    if not broker.authenticate():
        print(f"{Fore.RED}Broker authentication failed. Exiting.{Style.RESET_ALL}")
        return

    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    notifier.send_alert(
        f"<b>System Started</b>\nMode: {'Paper' if Config.PAPER_TRADING else 'Live'}\nCapital: Rs.{Config.CAPITAL:,}",
        "INFO"
    )

    print(f"\n{Fore.GREEN}Trading system started successfully!{Style.RESET_ALL}")
    print(f"Mode: {'PAPER TRADING' if Config.PAPER_TRADING else 'LIVE TRADING'}")
    print(f"Press Ctrl+C to stop\n")

    try:
        while True:
            if not Config.PAPER_TRADING and not Utils.is_market_hours():
                print(f"{Fore.YELLOW}Outside market hours. Waiting...{Style.RESET_ALL}")
                time.sleep(60)
                continue

            strategy.run_cycle()
            dashboard.render(strategy.market_data, trade_manager)
            time.sleep(Config.UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Shutting down gracefully...{Style.RESET_ALL}")

        # Close any open positions
        if trade_manager.active_trades:
            print(f"Closing {len(trade_manager.active_trades)} open positions...")
            for trade_id in list(trade_manager.active_trades.keys()):
                trade = trade_manager.active_trades[trade_id]
                exit_price = broker.get_quote(trade.symbol)
                if exit_price > 0:
                    trade_manager.close_trade(trade_id, exit_price)

        # Save final metrics
        metrics = trade_manager.get_performance_metrics()
        print(f"\n{Fore.CYAN}Session Summary:{Style.RESET_ALL}")
        print(f"Total Trades: {metrics.total_trades}")
        print(f"Win Rate: {metrics.win_rate:.1f}%")
        print(f"Total P&L: Rs.{metrics.total_pnl:,.2f}")

        notifier.send_alert("System shutdown", "INFO")
        db.close()

    except Exception as e:
        print(f"{Fore.RED}Fatal error: {e}{Style.RESET_ALL}")
        logging.error(f"Fatal error: {e}", exc_info=True)
        notifier.send_alert(f"Fatal error: {e}", "ERROR")
        db.close()


if __name__ == "__main__":
    main()