"""
Broker interface for the Short Strangle Trading System
PRODUCTION-READY VERSION - HTTP-ONLY (No WebSocket threading issues)

This version uses HTTP polling instead of WebSocket to avoid signal/threading conflicts.
WebSocket can be enabled later once system is stable.
"""

import logging
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List
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

        # Live trading components (HTTP-based)
        self.instruments_cache: Optional[pd.DataFrame] = None
        self.instruments_cache_time: Optional[datetime] = None
        self.pending_orders: Dict[str, Dict] = {}
        self.quote_cache: Dict[str, Dict] = {}  # Cache quotes to reduce API calls
        self.quote_cache_time: Dict[str, datetime] = {}

        if self.backtest_data is not None:
            self.backtest_data['timestamp'] = pd.to_datetime(self.backtest_data['timestamp'])
            logging.info(
                f"Backtest mode initialized with {len(self.backtest_data)} rows"
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
                        logging.info("✓ Loaded valid access token from file")
                        logging.info("✓ Using HTTP polling for market data (WebSocket disabled)")
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

            logging.info("✓ Authentication successful")
            logging.info("✓ Using HTTP polling for market data")
            return True

        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            return False

    # ═══════════════════════════════════════════════════════════
    # LIVE OPTION CHAIN FETCHING
    # ═══════════════════════════════════════════════════════════

    def fetch_instruments(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Fetch and cache NFO instruments
        Cache valid for 1 hour to reduce API calls
        """
        if self.backtest_data is not None:
            return pd.DataFrame()

        # Check cache validity
        if (not force_refresh and
            self.instruments_cache is not None and
            self.instruments_cache_time is not None):

            cache_age = (datetime.now() - self.instruments_cache_time).seconds
            if cache_age < 3600:  # 1 hour
                logging.debug(f"Using cached instruments (age: {cache_age}s)")
                return self.instruments_cache

        try:
            logging.info("Fetching live NFO instruments...")
            instruments = self.kite.instruments("NFO")
            df = pd.DataFrame(instruments)

            # Filter for NIFTY options only
            nifty_options = df[
                (df['name'] == 'NIFTY') &
                (df['instrument_type'].isin(['CE', 'PE']))
            ].copy()

            self.instruments_cache = nifty_options
            self.instruments_cache_time = datetime.now()

            logging.info(f"✓ Cached {len(nifty_options)} NIFTY option instruments")
            return nifty_options

        except Exception as e:
            logging.error(f"Failed to fetch instruments: {e}")
            if self.instruments_cache is not None:
                logging.warning("Returning stale cached instruments")
                return self.instruments_cache
            return pd.DataFrame()

    def find_live_option_symbol(self, strike: float, option_type: str,
                                expiry: date) -> Optional[Dict]:
        """
        Find live option instrument matching strike, type, and expiry
        FIXED: Proper datetime conversion for expiry comparison
        Returns: Dict with 'tradingsymbol' and 'instrument_token'
        """
        instruments = self.fetch_instruments()

        if instruments.empty:
            logging.error("No instruments available")
            return None

        # ═══════════════════════════════════════════════════════════════
        # FIX: Ensure expiry column is datetime type
        # ═══════════════════════════════════════════════════════════════

        # Convert expiry column to datetime if it isn't already
        if not pd.api.types.is_datetime64_any_dtype(instruments['expiry']):
            try:
                instruments['expiry'] = pd.to_datetime(instruments['expiry'])
                logging.debug("Converted expiry column to datetime")
            except Exception as e:
                logging.error(f"Failed to convert expiry column to datetime: {e}")
                return None

        # Convert input expiry to datetime for comparison
        if isinstance(expiry, date) and not isinstance(expiry, datetime):
            expiry_dt = datetime.combine(expiry, datetime.min.time())
        else:
            expiry_dt = expiry

        # ═══════════════════════════════════════════════════════════════
        # Filter by strike, type, and expiry
        # ═══════════════════════════════════════════════════════════════

        try:
            matches = instruments[
                (instruments['strike'] == strike) &
                (instruments['instrument_type'] == option_type.upper()) &
                (instruments['expiry'].dt.date == expiry_dt.date())
                ]
        except Exception as e:
            logging.error(f"Error filtering instruments: {e}")
            # Fallback: try without .dt accessor
            try:
                # Convert expiry column to date objects for comparison
                instruments['expiry_date'] = instruments['expiry'].apply(
                    lambda x: x.date() if hasattr(x, 'date') else x
                )
                matches = instruments[
                    (instruments['strike'] == strike) &
                    (instruments['instrument_type'] == option_type.upper()) &
                    (instruments['expiry_date'] == expiry_dt.date())
                    ]
            except Exception as e2:
                logging.error(f"Fallback filtering also failed: {e2}")
                return None

        if matches.empty:
            logging.error(
                f"No live symbol found for Strike={strike}, Type={option_type}, "
                f"Expiry={expiry_dt.date()}"
            )
            # Debug: Show available expiries for this strike and type
            debug_matches = instruments[
                (instruments['strike'] == strike) &
                (instruments['instrument_type'] == option_type.upper())
                ]
            if not debug_matches.empty:
                available_expiries = debug_matches['expiry'].unique()
                logging.info(f"Available expiries for {strike} {option_type}: {available_expiries[:5]}")
            return None

        if len(matches) > 1:
            logging.warning(f"Multiple matches found for {strike} {option_type}, using first")

        instrument = matches.iloc[0]

        result = {
            'tradingsymbol': instrument['tradingsymbol'],
            'instrument_token': instrument['instrument_token'],
            'exchange': instrument['exchange'],
            'strike': instrument['strike'],
            'expiry': instrument['expiry']
        }

        logging.info(f"✓ Found: {result['tradingsymbol']} (Token: {result['instrument_token']})")
        return result

    # ═══════════════════════════════════════════════════════════
    # HTTP-BASED QUOTE FETCHING (with caching to reduce API calls)
    # ═══════════════════════════════════════════════════════════

    def get_quote(self, symbol: str, use_cache: bool = True) -> float:
        """
        Get option price using HTTP API with intelligent caching
        Cache is valid for 1 second to balance freshness vs API limits
        """
        if self.backtest_data is not None:
            # Existing backtest logic (unchanged)
            current_row = self.backtest_data.iloc[self.current_index]
            market_data = self.get_market_data()

            ce_symbol = current_row.get('ce_symbol', '')
            pe_symbol = current_row.get('pe_symbol', '')

            if symbol == ce_symbol:
                price = current_row.get('ce_price', 0.0)
                if pd.notna(price) and price > 0:
                    return float(price)

            elif symbol == pe_symbol:
                price = current_row.get('pe_price', 0.0)
                if pd.notna(price) and price > 0:
                    return float(price)

            # Fallback to Black-Scholes
            parsed = Utils.parse_option_symbol(symbol)
            if parsed:
                _, strike, option_type = parsed
                current_date = market_data.timestamp.date()
                days_to_add = (Config.WEEKLY_EXPIRY_DAY - current_date.weekday()) % 7
                if days_to_add == 0:
                    days_to_add = 7
                expiry = current_date + pd.Timedelta(days=days_to_add)
                dte = self.greeks_calc.get_dte(expiry, current_date)

                if dte < 0 or market_data.india_vix <= 0 or market_data.nifty_spot <= 0:
                    return 0.0

                price = self.greeks_calc.get_option_price(
                    spot=market_data.nifty_spot,
                    strike=strike,
                    dte=dte,
                    volatility=market_data.india_vix,
                    option_type=option_type
                )

                return max(0.0, min(price, 5000.0))
            else:
                return market_data.nifty_spot

        # ═══════════════════════════════════════════════════════════
        # LIVE TRADING MODE - HTTP with smart caching
        # ═══════════════════════════════════════════════════════════

        try:
            # Check cache first (1 second validity)
            if use_cache and symbol in self.quote_cache:
                cache_time = self.quote_cache_time.get(symbol)
                if cache_time and (datetime.now() - cache_time).seconds < 1:
                    return self.quote_cache[symbol]

            # Fetch fresh quote
            quote = self.kite.quote(symbol)
            price = quote[symbol]['last_price']

            # Validate price
            if price > 10000 or price < 0:
                logging.error(f"Invalid live price for {symbol}: {price}")
                return 0.0

            # Update cache
            self.quote_cache[symbol] = price
            self.quote_cache_time[symbol] = datetime.now()

            return price

        except Exception as e:
            logging.error(f"Failed to fetch quote for {symbol}: {e}")
            # Return cached value if available
            if symbol in self.quote_cache:
                logging.warning(f"Using cached quote for {symbol}")
                return self.quote_cache[symbol]
            return 0.0

    def get_batch_quotes(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch multiple quotes in one API call (more efficient)
        """
        if self.backtest_data is not None:
            return {s: self.get_quote(s) for s in symbols}

        try:
            quotes = self.kite.quote(symbols)
            result = {}

            for symbol in symbols:
                if symbol in quotes:
                    price = quotes[symbol]['last_price']
                    if 0 < price < 10000:
                        result[symbol] = price
                        # Update cache
                        self.quote_cache[symbol] = price
                        self.quote_cache_time[symbol] = datetime.now()
                    else:
                        result[symbol] = 0.0
                else:
                    result[symbol] = 0.0

            return result

        except Exception as e:
            logging.error(f"Failed to fetch batch quotes: {e}")
            return {s: 0.0 for s in symbols}

    def get_quote_with_greeks(self, symbol: str, strike: float, option_type: str,
                              expiry: date, spot: float, vix: float,
                              current_date: date) -> tuple:
        """
        🆕 NEW: Get option price AND calculate Greeks for live trading

        Args:
            symbol: Option symbol (e.g., "NFO:NIFTY25N0426400CE")
            strike: Strike price
            option_type: "CE" or "PE"
            expiry: Expiry date
            spot: Current NIFTY spot
            vix: Current VIX
            current_date: Current date for DTE calculation

        Returns:
            Tuple of (price, greeks) or (price, None) if calculation fails
        """
        # Get price (existing logic)
        price = self.get_quote(symbol)

        if price <= 0:
            return price, None

        # Calculate DTE
        dte = self.greeks_calc.get_dte(expiry, current_date)

        if dte < 0:
            logging.warning(f"Negative DTE for {symbol}: {dte}")
            return price, None

        # 🆕 Calculate Greeks using Black-Scholes
        try:
            greeks = self.greeks_calc.calculate_all_greeks(
                spot=spot,
                strike=strike,
                dte=dte,
                volatility=vix,
                option_type=option_type
            )

            logging.debug(
                f"Greeks calculated for {symbol}: "
                f"Δ={greeks.delta:.1f}, Θ={greeks.theta:.2f}, "
                f"Γ={greeks.gamma:.3f}, ν={greeks.vega:.2f}"
            )

            return price, greeks

        except Exception as e:
            logging.error(f"Failed to calculate Greeks for {symbol}: {e}")
            return price, None

    # ═══════════════════════════════════════════════════════════
    # ORDER PLACEMENT & VERIFICATION
    # ═══════════════════════════════════════════════════════════

    def place_order(self, symbol: str, qty: int, direction: Direction,
                    price: float) -> str:
        """
        Place order with DRY RUN support

        Modes:
        - Backtest: Uses historical data
        - Dry Run: Simulates live orders (no broker calls)
        - Paper: Simulates orders (checks PAPER_TRADING flag)
        - Live: Actual broker orders
        """

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # MODE 1: BACKTEST (Historical Data)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if self.backtest_data is not None:
            logging.info(
                f"[BACKTEST] ORDER: {direction.value} {qty} lots {symbol} @ ₹{price:.2f}"
            )
            return f"backtest_order_{Utils.generate_id()}"

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # MODE 2: DRY RUN (Simulate Live Orders)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if Config.DRY_RUN_MODE:
            order_id = f"dryrun_order_{Utils.generate_id()}"

            # Store order details for tracking
            self.pending_orders[order_id] = {
                'symbol': symbol,
                'qty': qty,
                'direction': direction,
                'price': price,
                'timestamp': datetime.now(),
                'status': 'COMPLETE',  # Simulate instant fill
                'mode': 'DRY_RUN'
            }

            # Detailed logging
            lot_size = self.get_lot_size(symbol)
            total_qty = qty * lot_size
            total_value = price * total_qty

            logging.info(
                f"[DRY RUN] ✓ ORDER SIMULATED: {direction.value} {qty} lots "
                f"({total_qty} qty) {symbol} @ ₹{price:.2f}"
            )
            logging.info(
                f"[DRY RUN]   Total Value: ₹{total_value:,.2f} | "
                f"Order ID: {order_id}"
            )

            # Console output with color
            from colorama import Fore, Style
            color = Fore.RED if direction == Direction.SELL else Fore.GREEN
            print(f"\n{color}{'─' * 70}{Style.RESET_ALL}")
            print(f"{color}[DRY RUN] ORDER SIMULATED{Style.RESET_ALL}")
            print(f"{color}{direction.value} {qty} lots of {symbol} @ ₹{price:.2f}{Style.RESET_ALL}")
            print(f"{color}Total: {total_qty} qty | Value: ₹{total_value:,.2f}{Style.RESET_ALL}")
            print(f"{color}Order ID: {order_id}{Style.RESET_ALL}")
            print(f"{color}{'─' * 70}{Style.RESET_ALL}\n")

            return order_id

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # MODE 3: PAPER TRADING (if not already in DRY_RUN)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if Config.PAPER_TRADING:
            logging.info(
                f"[PAPER] ORDER SIMULATED: {direction.value} {qty} lots "
                f"{symbol} @ ₹{price:.2f}"
            )
            return f"paper_order_{Utils.generate_id()}"

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # MODE 4: LIVE TRADING (Real Broker Orders)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        try:
            # Validate inputs
            if qty <= 0:
                logging.error(f"Invalid quantity: {qty}")
                return ""

            if price <= 0:
                logging.error(f"Invalid price: {price}")
                return ""

            # Place REAL order via broker
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NFO,
                tradingsymbol=symbol.replace('NFO:', ''),
                transaction_type=direction.value,
                quantity=qty * 75,  # NIFTY lot size
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=price,
                validity=self.kite.VALIDITY_DAY
            )

            logging.info(
                f"[LIVE] ✓ ORDER PLACED: {order_id} | {direction.value} {qty} lots "
                f"{symbol} @ ₹{price:.2f}"
            )

            # Track for verification
            self.pending_orders[order_id] = {
                'symbol': symbol,
                'qty': qty,
                'direction': direction,
                'price': price,
                'timestamp': datetime.now(),
                'status': 'PENDING',
                'mode': 'LIVE'
            }

            # Wait and verify
            time.sleep(0.5)
            self.verify_order_status(order_id)

            return order_id

        except Exception as e:
            logging.error(f"[LIVE] Order placement failed for {symbol}: {e}")
            return ""

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. UPDATE verify_order_status() to handle DRY_RUN
    # ═══════════════════════════════════════════════════════════════════════════

    def verify_order_status(self, order_id: str, max_retries: int = 3) -> bool:
        """
        Verify order status with DRY_RUN support
        """
        # Skip verification in backtest or dry run mode
        if self.backtest_data is not None or Config.DRY_RUN_MODE:
            return True

        # Existing verification logic for live/paper trading
        if not order_id:
            return True

        for attempt in range(max_retries):
            try:
                order_history = self.kite.order_history(order_id)

                if not order_history:
                    logging.warning(f"No history for order {order_id}")
                    time.sleep(1)
                    continue

                latest_status = order_history[-1]
                status = latest_status['status']

                if order_id in self.pending_orders:
                    self.pending_orders[order_id]['status'] = status
                    self.pending_orders[order_id]['filled_qty'] = latest_status.get('filled_quantity', 0)
                    self.pending_orders[order_id]['pending_qty'] = latest_status.get('pending_quantity', 0)

                if status == 'COMPLETE':
                    logging.info(f"✓ Order {order_id} COMPLETE")
                    return True
                elif status == 'REJECTED':
                    logging.error(f"✗ Order {order_id} REJECTED: {latest_status.get('status_message', 'Unknown')}")
                    return False
                elif status == 'CANCELLED':
                    logging.warning(f"✗ Order {order_id} CANCELLED")
                    return False
                else:
                    logging.info(f"Order {order_id} status: {status} (attempt {attempt + 1}/{max_retries})")
                    time.sleep(1)

            except Exception as e:
                logging.error(f"Error verifying order {order_id}: {e}")
                time.sleep(1)

        logging.warning(f"Order {order_id} verification timeout")
        return False

    # ═══════════════════════════════════════════════════════════
    # POSITION RECONCILIATION
    # ═══════════════════════════════════════════════════════════

    def reconcile_positions(self) -> Dict[str, Dict]:
        """
        Fetch current positions from broker
        """
        if self.backtest_data is not None:
            return {}

        try:
            positions = self.kite.positions()
            net_positions = positions.get('net', [])

            active_positions = {}
            for pos in net_positions:
                if pos['quantity'] != 0:
                    symbol = pos['tradingsymbol']
                    active_positions[symbol] = {
                        'quantity': pos['quantity'],
                        'average_price': pos['average_price'],
                        'last_price': pos['last_price'],
                        'pnl': pos['pnl'],
                        'product': pos['product']
                    }

            if active_positions:
                logging.info(f"✓ Reconciled {len(active_positions)} active positions")
                for symbol, info in active_positions.items():
                    logging.info(
                        f"  {symbol}: Qty={info['quantity']}, "
                        f"Avg={info['average_price']:.2f}, "
                        f"LTP={info['last_price']:.2f}, "
                        f"P&L={info['pnl']:.2f}"
                    )
            else:
                logging.info("No active positions found")

            return active_positions

        except Exception as e:
            logging.error(f"Failed to reconcile positions: {e}")
            return {}

    # ═══════════════════════════════════════════════════════════
    # EXISTING METHODS
    # ═══════════════════════════════════════════════════════════

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

        # Live market data using HTTP
        try:
            quotes = self.kite.quote(["NSE:NIFTY 50", "NSE:INDIA VIX"])
            nifty_spot = quotes["NSE:NIFTY 50"]['last_price']
            india_vix = quotes["NSE:INDIA VIX"]['last_price']

            # Cache the quotes
            self.quote_cache["NSE:NIFTY 50"] = nifty_spot
            self.quote_cache["NSE:INDIA VIX"] = india_vix
            self.quote_cache_time["NSE:NIFTY 50"] = datetime.now()
            self.quote_cache_time["NSE:INDIA VIX"] = datetime.now()

            return MarketData(
                nifty_spot=nifty_spot,
                india_vix=india_vix,
                timestamp=datetime.now()
            )

        except Exception as e:
            logging.error(f"Failed to get live market data: {e}")
            # Return cached values if available
            nifty_spot = self.quote_cache.get("NSE:NIFTY 50", 0.0)
            india_vix = self.quote_cache.get("NSE:INDIA VIX", 0.0)
            return MarketData(nifty_spot=nifty_spot, india_vix=india_vix)