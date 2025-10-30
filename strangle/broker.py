"""
Broker interface for the Short Strangle Trading System
FIXED:
- Uses ACTUAL historical option prices from backtest data
- Falls back to Black-Scholes only when real prices unavailable
- Validates all prices for sanity
"""

import logging
from datetime import datetime, date
from pathlib import Path
import pandas as pd
from kiteconnect import KiteConnect

from .config import Config
from .models import Direction, MarketData
from .utils import Utils
from .greeks_calculator import GreeksCalculator


class BrokerInterface:
    def __init__(self, backtest_data: pd.DataFrame = None):
        self.kite = KiteConnect(api_key=Config.API_KEY)
        self.backtest_data = backtest_data
        self.current_index = 0
        self.access_token_expiry = None
        self.greeks_calc = GreeksCalculator()

        if self.backtest_data is not None:
            self.backtest_data['timestamp'] = pd.to_datetime(self.backtest_data['timestamp'])
            logging.info(
                f"Backtest mode initialized with {len(self.backtest_data)} rows. "
                f"Columns: {list(self.backtest_data.columns)}"
            )

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
        """
        Get option price - FIXED to use real historical prices
        """
        if self.backtest_data is not None:
            # --- BACKTESTING MODE: Use REAL historical prices ---
            current_row = self.backtest_data.iloc[self.current_index]
            market_data = self.get_market_data()

            # Check if this symbol matches the CE or PE in current row
            ce_symbol = current_row.get('ce_symbol', '')
            pe_symbol = current_row.get('pe_symbol', '')

            # CRITICAL: Use actual historical prices from the data
            if symbol == ce_symbol:
                price = current_row.get('ce_price', 0.0)
                if pd.notna(price) and price > 0:
                    logging.debug(f"Using REAL CE price for {symbol}: {price:.2f}")
                    return float(price)
                else:
                    logging.warning(
                        f"No valid CE price in data for {symbol} at index {self.current_index}. "
                        f"ce_price value: {price}. Will calculate using Black-Scholes."
                    )

            elif symbol == pe_symbol:
                price = current_row.get('pe_price', 0.0)
                if pd.notna(price) and price > 0:
                    logging.debug(f"Using REAL PE price for {symbol}: {price:.2f}")
                    return float(price)
                else:
                    logging.warning(
                        f"No valid PE price in data for {symbol} at index {self.current_index}. "
                        f"pe_price value: {price}. Will calculate using Black-Scholes."
                    )

            # If symbol doesn't match current CE/PE, or price is missing, fall back to calculation
            logging.warning(
                f"Symbol {symbol} doesn't match current CE ({ce_symbol}) or PE ({pe_symbol}). "
                f"Falling back to Black-Scholes calculation."
            )

            # Fall back to Black-Scholes calculation
            parsed = Utils.parse_option_symbol(symbol)
            if parsed:
                _, strike, option_type = parsed

                current_date = market_data.timestamp.date()

                # Calculate next Tuesday expiry
                days_to_add = (Config.WEEKLY_EXPIRY_DAY - current_date.weekday()) % 7
                if days_to_add == 0:
                    days_to_add = 7
                expiry = current_date + pd.Timedelta(days=days_to_add)

                dte = self.greeks_calc.get_dte(expiry, current_date)

                # Validate inputs
                if dte < 0:
                    logging.warning(f"DTE is negative ({dte}) for {symbol}. Returning 0.")
                    return 0.0

                if market_data.india_vix <= 0 or pd.isna(market_data.india_vix):
                    logging.error(f"Invalid VIX ({market_data.india_vix}) for {symbol}. Returning 0.")
                    return 0.0

                if market_data.nifty_spot <= 0 or pd.isna(market_data.nifty_spot):
                    logging.error(f"Invalid Spot ({market_data.nifty_spot}) for {symbol}. Returning 0.")
                    return 0.0

                try:
                    price = self.greeks_calc.get_option_price(
                        spot=market_data.nifty_spot,
                        strike=strike,
                        dte=dte,
                        volatility=market_data.india_vix,
                        option_type=option_type
                    )

                    # Validate calculated price
                    MAX_REASONABLE_PRICE = 5000

                    if price > MAX_REASONABLE_PRICE:
                        logging.error(
                            f"UNREALISTIC Black-Scholes price for {symbol}: {price:.2f}. "
                            f"Inputs: Spot={market_data.nifty_spot:.2f}, Strike={strike}, "
                            f"DTE={dte}, VIX={market_data.india_vix:.2f}. Returning 0."
                        )
                        return 0.0

                    if price < 0:
                        logging.warning(f"Negative price for {symbol}: {price:.2f}. Returning 0.")
                        return 0.0

                    # Expiry day check
                    if dte == 0:
                        if option_type == "CE":
                            intrinsic = max(0, market_data.nifty_spot - strike)
                        else:
                            intrinsic = max(0, strike - market_data.nifty_spot)

                        if price > intrinsic + 10:
                            logging.warning(
                                f"Expiry day: Calculated price {price:.2f} exceeds "
                                f"intrinsic {intrinsic:.2f} for {symbol}. Using intrinsic."
                            )
                            price = intrinsic

                    logging.info(f"Calculated Black-Scholes price for {symbol}: {price:.2f}")
                    return max(0.0, price)

                except Exception as e:
                    logging.error(
                        f"Error calculating price for {symbol}: {e}. "
                        f"Spot={market_data.nifty_spot:.2f}, Strike={strike}, "
                        f"DTE={dte}, VIX={market_data.india_vix:.2f}",
                        exc_info=True
                    )
                    return 0.0
            else:
                # Not an option symbol, return NIFTY spot
                return market_data.nifty_spot

        # --- LIVE TRADING MODE ---
        try:
            quote = self.kite.quote(symbol)
            price = quote[symbol]['last_price']

            # Validate live price
            if price > 10000 or price < 0:
                logging.error(f"Invalid live price for {symbol}: {price}. Returning 0.")
                return 0.0

            return price
        except Exception as e:
            logging.error(f"Failed to fetch live quote for {symbol}: {e}")
            return 0.0

    def get_lot_size(self, symbol: str) -> int:
        """Get lot size for NIFTY"""
        return 75

    def get_market_data(self) -> MarketData:
        """Get current market data"""
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
                timestamp=row['timestamp'],
                ce_symbol=row.get('ce_symbol', ''),
                pe_symbol=row.get('pe_symbol', '')
            )

        # Placeholder for live market data
        return MarketData(
            nifty_spot=self.get_quote("NIFTY 50"),
            india_vix=self.get_quote("INDIA VIX")
        )

    def place_order(self, symbol: str, qty: int, direction: Direction, price: float) -> str:
        """Place order"""
        if self.backtest_data is not None:
            logging.info(
                f"ORDER PLACED: {direction.value} {qty} of {symbol} @ Rs.{price:.2f}"
            )
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