"""
historical_data_manager.py
Manages downloading and caching of historical instruments and price data for backtesting
"""

import pandas as pd
import pickle
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import time
from kiteconnect import KiteConnect
import json


class HistoricalDataManager:
    """Manages historical data download and caching for options backtesting"""

    def __init__(self, kite: KiteConnect, cache_dir: str = "backtest_cache"):
        self.kite = kite
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        # Create subdirectories
        (self.cache_dir / "instruments").mkdir(exist_ok=True)
        (self.cache_dir / "nifty").mkdir(exist_ok=True)
        (self.cache_dir / "vix").mkdir(exist_ok=True)
        (self.cache_dir / "options").mkdir(exist_ok=True)

        self.logger = logging.getLogger(__name__)

    def get_cache_filename(self, data_type: str, identifier: str, date_str: str = None) -> Path:
        """Generate cache filename"""
        if date_str:
            return self.cache_dir / data_type / f"{identifier}_{date_str}.pkl"
        return self.cache_dir / data_type / f"{identifier}.pkl"

    def save_to_cache(self, data: any, data_type: str, identifier: str, date_str: str = None):
        """Save data to cache"""
        cache_file = self.get_cache_filename(data_type, identifier, date_str)
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)
        self.logger.info(f"Cached {data_type}/{identifier} to {cache_file}")

    def load_from_cache(self, data_type: str, identifier: str, date_str: str = None) -> Optional[any]:
        """Load data from cache"""
        cache_file = self.get_cache_filename(data_type, identifier, date_str)
        if cache_file.exists():
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        return None

    def fetch_with_retry(self, fetch_func, *args, retries: int = 3, **kwargs):
        """Fetch data with retry logic"""
        for attempt in range(retries):
            try:
                result = fetch_func(*args, **kwargs)
                return result
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1}/{retries} failed: {e}")
                if attempt + 1 == retries:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
        return None

    def download_nifty_data(self, start_date: str, end_date: str, force_refresh: bool = False) -> pd.DataFrame:
        """Download NIFTY 50 spot data"""
        cache_key = f"{start_date}_{end_date}"

        # Check cache first
        if not force_refresh:
            cached_data = self.load_from_cache("nifty", cache_key)
            if cached_data is not None:
                self.logger.info(f"Loaded NIFTY data from cache: {cache_key}")
                return cached_data

        self.logger.info(f"Downloading NIFTY data from {start_date} to {end_date}")

        # NIFTY 50 token
        nifty_token = 256265

        all_data = []
        current_start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        while current_start < end:
            current_end = min(current_start + pd.Timedelta(days=60), end)

            try:
                data = self.kite.historical_data(
                    instrument_token=nifty_token,
                    from_date=current_start.strftime("%Y-%m-%d"),
                    to_date=current_end.strftime("%Y-%m-%d"),
                    interval="minute"
                )
                all_data.extend(data)
                self.logger.info(f"Downloaded NIFTY data: {current_start.date()} to {current_end.date()}")
            except Exception as e:
                self.logger.error(f"Failed to download NIFTY data: {e}")

            current_start = current_end + pd.Timedelta(days=1)
            time.sleep(0.34)  # Rate limit: 3 requests/sec

        df = pd.DataFrame(all_data)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['date'])
            df = df.drop(columns=['date'])

            # Save to cache
            self.save_to_cache(df, "nifty", cache_key)

        return df

    def download_vix_data(self, start_date: str, end_date: str, force_refresh: bool = False) -> pd.DataFrame:
        """Download India VIX data"""
        cache_key = f"{start_date}_{end_date}"

        # Check cache first
        if not force_refresh:
            cached_data = self.load_from_cache("vix", cache_key)
            if cached_data is not None:
                self.logger.info(f"Loaded VIX data from cache: {cache_key}")
                return cached_data

        self.logger.info(f"Downloading VIX data from {start_date} to {end_date}")

        # India VIX token
        vix_token = 264969

        all_data = []
        current_start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        while current_start < end:
            current_end = min(current_start + pd.Timedelta(days=60), end)

            try:
                data = self.kite.historical_data(
                    instrument_token=vix_token,
                    from_date=current_start.strftime("%Y-%m-%d"),
                    to_date=current_end.strftime("%Y-%m-%d"),
                    interval="minute"
                )
                all_data.extend(data)
                self.logger.info(f"Downloaded VIX data: {current_start.date()} to {current_end.date()}")
            except Exception as e:
                self.logger.error(f"Failed to download VIX data: {e}")

            current_start = current_end + pd.Timedelta(days=1)
            time.sleep(0.34)  # Rate limit

        df = pd.DataFrame(all_data)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['date'])
            df = df.drop(columns=['date'])

            # Save to cache
            self.save_to_cache(df, "vix", cache_key)

        return df

    def get_instruments_for_date(self, target_date: date, force_refresh: bool = False) -> List[Dict]:
        """Get NFO instruments list for a specific date (or closest available)"""
        date_str = target_date.strftime('%Y-%m-%d')

        # Check cache first
        if not force_refresh:
            cached_instruments = self.load_from_cache("instruments", "nfo", date_str)
            if cached_instruments is not None:
                self.logger.info(f"Loaded instruments from cache for {date_str}")
                return cached_instruments

        # Try to get current instruments (works for recent/future dates)
        try:
            instruments = self.kite.instruments("NFO")
            nifty_options = [
                i for i in instruments
                if i['name'] == 'NIFTY' and i['instrument_type'] in ['CE', 'PE']
            ]

            # Save to cache
            self.save_to_cache(nifty_options, "instruments", "nfo", date_str)
            self.logger.info(f"Downloaded {len(nifty_options)} NIFTY options instruments")

            return nifty_options
        except Exception as e:
            self.logger.error(f"Failed to download instruments: {e}")
            return []

    def find_option_token(self, instruments: List[Dict], strike: float, option_type: str,
                         expiry: date) -> Tuple[Optional[int], Optional[str]]:
        """
        Find option instrument token by strike, type, and expiry
        Returns: (token, symbol) or (None, None)
        """
        candidates = []

        # First pass: exact match
        for instrument in instruments:
            if instrument.get('strike') != strike:
                continue
            if instrument.get('instrument_type') != option_type:
                continue

            inst_expiry = instrument.get('expiry')
            if inst_expiry:
                if isinstance(inst_expiry, str):
                    inst_expiry = pd.to_datetime(inst_expiry).date()

                # Allow expiry within same week (up to 7 days difference)
                expiry_diff = abs((inst_expiry - expiry).days)
                if expiry_diff <= 7:
                    candidates.append({
                        'token': instrument['instrument_token'],
                        'symbol': instrument['tradingsymbol'],
                        'expiry': inst_expiry,
                        'diff': expiry_diff
                    })

        if candidates:
            # Return the closest expiry match
            best_match = min(candidates, key=lambda x: x['diff'])
            return best_match['token'], best_match['symbol']

        # Second pass: try nearby strikes (within 50 points)
        self.logger.warning(f"No exact match for strike {strike}, trying nearby strikes")

        for strike_offset in [0, 50, -50, 100, -100]:
            adjusted_strike = strike + strike_offset

            for instrument in instruments:
                if instrument.get('strike') != adjusted_strike:
                    continue
                if instrument.get('instrument_type') != option_type:
                    continue

                inst_expiry = instrument.get('expiry')
                if inst_expiry:
                    if isinstance(inst_expiry, str):
                        inst_expiry = pd.to_datetime(inst_expiry).date()

                    expiry_diff = abs((inst_expiry - expiry).days)
                    if expiry_diff <= 14:  # Allow 2 weeks for fallback
                        candidates.append({
                            'token': instrument['instrument_token'],
                            'symbol': instrument['tradingsymbol'],
                            'expiry': inst_expiry,
                            'diff': expiry_diff,
                            'strike_diff': abs(strike_offset)
                        })

        if not candidates:
            # Log available strikes for debugging
            available_strikes = sorted(set(i['strike'] for i in instruments
                                          if i.get('instrument_type') == option_type))
            self.logger.warning(
                f"No suitable {option_type} option found near strike {strike}. "
                f"Available strikes: {available_strikes[:10]}...{available_strikes[-10:]}"
            )
            return None, None

        # Return the closest match (prefer smaller strike difference, then expiry)
        best_match = min(candidates, key=lambda x: (x.get('strike_diff', 0), x['diff']))
        if best_match.get('strike_diff', 0) > 0:
            self.logger.info(
                f"Using adjusted strike: requested {strike}, using {strike + best_match['strike_diff']}"
            )
        return best_match['token'], best_match['symbol']

    def download_option_data(self, token: int, symbol: str, start_date: str, end_date: str,
                            force_refresh: bool = False) -> pd.DataFrame:
        """Download option price data"""
        cache_key = f"{symbol}_{start_date}_{end_date}"

        # Check cache first
        if not force_refresh:
            cached_data = self.load_from_cache("options", cache_key)
            if cached_data is not None:
                self.logger.info(f"Loaded option data from cache: {symbol}")
                return cached_data

        self.logger.info(f"Downloading option data for {symbol}")

        all_data = []
        current_start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        while current_start < end:
            current_end = min(current_start + pd.Timedelta(days=60), end)

            try:
                data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=current_start.strftime("%Y-%m-%d"),
                    to_date=current_end.strftime("%Y-%m-%d"),
                    interval="minute"
                )
                all_data.extend(data)
            except Exception as e:
                self.logger.warning(f"Failed to download data for {symbol}: {e}")
                break

            current_start = current_end + pd.Timedelta(days=1)
            time.sleep(0.34)  # Rate limit

        df = pd.DataFrame(all_data)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['date'])
            df = df.drop(columns=['date'])

            # Save to cache
            self.save_to_cache(df, "options", cache_key)

        return df

    def prepare_backtest_data(self, start_date: str, end_date: str,
                             strike_calculator, force_refresh: bool = False) -> pd.DataFrame:
        """
        Prepare complete backtest dataset with NIFTY, VIX, and option prices

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            strike_calculator: Function that takes (spot, vix) and returns (ce_strike, pe_strike, expiry)
            force_refresh: Force download even if cached data exists
        """
        self.logger.info(f"Preparing backtest data from {start_date} to {end_date}")

        # Download base data
        nifty_data = self.download_nifty_data(start_date, end_date, force_refresh)
        vix_data = self.download_vix_data(start_date, end_date, force_refresh)

        if nifty_data.empty or vix_data.empty:
            raise ValueError("Failed to download NIFTY or VIX data")

        # Prepare daily data
        backtest_data_list = []
        date_range = pd.date_range(start_date, end_date, freq='D')

        for current_date in date_range:
            # Skip weekends
            if current_date.weekday() >= 5:
                continue

            date_obj = current_date.date()
            self.logger.info(f"Processing {date_obj}")

            # Get daily NIFTY data
            daily_nifty = nifty_data[nifty_data['timestamp'].dt.date == date_obj]
            if daily_nifty.empty:
                self.logger.warning(f"No NIFTY data for {date_obj}")
                continue

            # Get daily VIX data
            daily_vix = vix_data[vix_data['timestamp'].dt.date == date_obj]
            if daily_vix.empty:
                self.logger.warning(f"No VIX data for {date_obj}")
                continue

            spot = daily_nifty['close'].iloc[0]
            vix = daily_vix['close'].mean()

            # Calculate strikes for this date
            ce_strike, pe_strike, expiry = strike_calculator(spot, vix, date_obj)

            self.logger.info(f"  Strikes: CE={ce_strike}, PE={pe_strike}, Expiry={expiry}")

            # Get instruments for this date
            instruments = self.get_instruments_for_date(date_obj, force_refresh)
            if not instruments:
                self.logger.warning(f"No instruments available for {date_obj}")
                continue

            # Find option tokens
            ce_token, ce_symbol = self.find_option_token(instruments, ce_strike, 'CE', expiry)
            pe_token, pe_symbol = self.find_option_token(instruments, pe_strike, 'PE', expiry)

            if not ce_token or not pe_token:
                self.logger.warning(f"  No tokens found for strikes CE={ce_strike}/PE={pe_strike}")
                continue

            self.logger.info(f"  Found: {ce_symbol} / {pe_symbol}")

            # Download option data
            ce_data = self.download_option_data(ce_token, ce_symbol, start_date, end_date, force_refresh)
            pe_data = self.download_option_data(pe_token, pe_symbol, start_date, end_date, force_refresh)

            if ce_data.empty or pe_data.empty:
                self.logger.warning(f"  No option price data for {ce_symbol}/{pe_symbol}")
                continue

            # Merge data for this day
            daily_data = daily_nifty.copy()
            daily_data = daily_data.rename(columns={
                'close': 'nifty_spot',
                'open': 'nifty_open',
                'high': 'nifty_high',
                'low': 'nifty_low'
            })

            # Add VIX data
            vix_aligned = daily_vix.set_index('timestamp')['close'].reindex(daily_data['timestamp'])
            daily_data['india_vix'] = vix_aligned.values
            daily_data['india_vix'] = daily_data['india_vix'].fillna(method='ffill').fillna(vix)

            # Add option prices
            ce_aligned = ce_data[ce_data['timestamp'].dt.date == date_obj].set_index('timestamp')['close']
            pe_aligned = pe_data[pe_data['timestamp'].dt.date == date_obj].set_index('timestamp')['close']

            daily_data['ce_price'] = ce_aligned.reindex(daily_data['timestamp']).values
            daily_data['pe_price'] = pe_aligned.reindex(daily_data['timestamp']).values

            # Forward fill missing option prices
            daily_data['ce_price'] = daily_data['ce_price'].fillna(method='ffill')
            daily_data['pe_price'] = daily_data['pe_price'].fillna(method='ffill')

            # Add metadata
            daily_data['ce_symbol'] = ce_symbol
            daily_data['pe_symbol'] = pe_symbol
            daily_data['ce_strike'] = ce_strike
            daily_data['pe_strike'] = pe_strike

            # Calculate 30-day VIX average
            daily_data['vix_30day_avg'] = daily_data['india_vix'].rolling(window=30, min_periods=1).mean()

            # Drop rows with missing critical data
            daily_data = daily_data.dropna(subset=['ce_price', 'pe_price', 'india_vix'])

            if not daily_data.empty:
                backtest_data_list.append(daily_data)
                self.logger.info(f"  Added {len(daily_data)} rows for {date_obj}")

        if not backtest_data_list:
            raise ValueError("No valid backtest data collected")

        # Combine all data
        backtest_data = pd.concat(backtest_data_list, ignore_index=True)
        backtest_data = backtest_data.sort_values('timestamp').reset_index(drop=True)

        self.logger.info(f"Backtest data prepared: {len(backtest_data)} total rows")

        return backtest_data

    def debug_available_instruments(self, target_date: date, strike_range: tuple = (24000, 25500)):
        """
        Debug function to see what instruments are available for a date
        """
        instruments = self.get_instruments_for_date(target_date, force_refresh=True)

        if not instruments:
            print(f"No instruments found for {target_date}")
            return

        print(f"\n{Fore.CYAN}Available NIFTY Options for {target_date}:{Style.RESET_ALL}")
        print(f"Total instruments: {len(instruments)}\n")

        # Filter by strike range
        filtered = [i for i in instruments
                   if strike_range[0] <= i.get('strike', 0) <= strike_range[1]]

        # Group by expiry
        expiries = {}
        for inst in filtered:
            exp = inst.get('expiry')
            if isinstance(exp, str):
                exp = pd.to_datetime(exp).date()
            if exp not in expiries:
                expiries[exp] = {'CE': [], 'PE': []}
            expiries[exp][inst['instrument_type']].append(inst['strike'])

        for expiry in sorted(expiries.keys()):
            print(f"\n{Fore.GREEN}Expiry: {expiry}{Style.RESET_ALL}")
            ce_strikes = sorted(set(expiries[expiry]['CE']))
            pe_strikes = sorted(set(expiries[expiry]['PE']))
            print(f"  CE strikes: {ce_strikes[:5]} ... {ce_strikes[-5:]}")
            print(f"  PE strikes: {pe_strikes[:5]} ... {pe_strikes[-5:]}")
            print(f"  Total CE: {len(ce_strikes)}, Total PE: {len(pe_strikes)}")

    def clear_cache(self, data_type: str = None):
        """Clear cached data"""
        if data_type:
            cache_path = self.cache_dir / data_type
            if cache_path.exists():
                for file in cache_path.glob("*.pkl"):
                    file.unlink()
                self.logger.info(f"Cleared {data_type} cache")
        else:
            for subdir in ["instruments", "nifty", "vix", "options"]:
                cache_path = self.cache_dir / subdir
                if cache_path.exists():
                    for file in cache_path.glob("*.pkl"):
                        file.unlink()
            self.logger.info("Cleared all cache")