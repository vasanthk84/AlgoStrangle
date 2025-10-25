"""
Broker interface for the Short Strangle Trading System
"""

import logging
from datetime import datetime
from pathlib import Path
import pandas as pd
from kiteconnect import KiteConnect

from .config import Config
from .models import Direction, MarketData
from .utils import Utils


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
            import webbrowser
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
