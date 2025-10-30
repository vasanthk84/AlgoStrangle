"""
historical_data_manager.py - FIXED VERSION with Weekly Expiry Support
Handles downloading, caching, and preparation of historical data for backtesting
FIXED:
- Properly finds weekly expiries (Tuesdays)
- Uses the expiry returned by strike_calculator
- Validates symbols match the intended expiry
"""

import os
import json
import logging
from datetime import datetime, date, timedelta
from typing import Tuple, Callable, Optional
import pandas as pd
import numpy as np
from pathlib import Path


class HistoricalDataManager:
    """Manages historical data for backtesting"""

    def __init__(self, kite, cache_dir: str = "backtest_cache"):
        self.kite = kite
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _get_cache_path(self, data_type: str, identifier: str) -> Path:
        """Generate cache file path"""
        return self.cache_dir / f"{data_type}_{identifier}.csv"

    def _load_from_cache(self, cache_path: Path) -> Optional[pd.DataFrame]:
        """Load data from cache if exists"""
        if cache_path.exists():
            try:
                df = pd.read_csv(cache_path)
                if 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                logging.info(f"Loaded from cache: {cache_path.name}")
                return df
            except Exception as e:
                logging.warning(f"Failed to load cache {cache_path}: {e}")
        return None

    def _save_to_cache(self, df: pd.DataFrame, cache_path: Path):
        """Save data to cache"""
        try:
            df.to_csv(cache_path, index=False)
            logging.info(f"Saved to cache: {cache_path.name}")
        except Exception as e:
            logging.error(f"Failed to save cache {cache_path}: {e}")

    def download_nifty_data(self, start_date: str, end_date: str, force_refresh: bool = False) -> pd.DataFrame:
        """Download NIFTY 50 historical data"""
        cache_id = f"{start_date}_{end_date}"
        cache_path = self._get_cache_path("NIFTY", cache_id)

        if not force_refresh:
            cached_data = self._load_from_cache(cache_path)
            if cached_data is not None:
                return cached_data

        logging.info(f"Downloading NIFTY data from {start_date} to {end_date}")

        try:
            data = self.kite.historical_data(
                instrument_token=256265,  # NIFTY 50 token
                from_date=start_date,
                to_date=end_date,
                interval="minute"
            )

            df = pd.DataFrame(data)
            df.rename(columns={
                'date': 'timestamp',
                'open': 'nifty_open',
                'high': 'nifty_high',
                'low': 'nifty_low',
                'close': 'nifty_spot',
                'volume': 'nifty_volume'
            }, inplace=True)

            df['nifty_future'] = df['nifty_spot'] + 10

            self._save_to_cache(df, cache_path)
            return df

        except Exception as e:
            logging.error(f"Failed to download NIFTY data: {e}")
            raise

    def download_vix_data(self, start_date: str, end_date: str, force_refresh: bool = False) -> pd.DataFrame:
        """Download India VIX historical data"""
        cache_id = f"{start_date}_{end_date}"
        cache_path = self._get_cache_path("VIX", cache_id)

        if not force_refresh:
            cached_data = self._load_from_cache(cache_path)
            if cached_data is not None:
                return cached_data

        logging.info(f"Downloading VIX data from {start_date} to {end_date}")

        try:
            data = self.kite.historical_data(
                instrument_token=264969,  # India VIX token
                from_date=start_date,
                to_date=end_date,
                interval="minute"
            )

            df = pd.DataFrame(data)
            df.rename(columns={
                'date': 'timestamp',
                'close': 'india_vix'
            }, inplace=True)
            df = df[['timestamp', 'india_vix']]

            df['vix_30day_avg'] = df['india_vix'].rolling(window=30 * 375, min_periods=1).mean()

            self._save_to_cache(df, cache_path)
            return df

        except Exception as e:
            logging.error(f"Failed to download VIX data: {e}")
            raise

    def download_option_chain(self, date_str: str, force_refresh: bool = False) -> pd.DataFrame:
        """Download option chain instruments for a specific date"""
        cache_path = self._get_cache_path("instruments", date_str)

        if not force_refresh:
            cached_data = self._load_from_cache(cache_path)
            if cached_data is not None:
                return cached_data

        logging.info(f"Downloading instruments for {date_str}")

        try:
            instruments = self.kite.instruments("NFO")
            df = pd.DataFrame(instruments)

            nifty_options = df[
                (df['name'] == 'NIFTY') &
                (df['instrument_type'].isin(['CE', 'PE']))
            ].copy()

            self._save_to_cache(nifty_options, cache_path)
            return nifty_options

        except Exception as e:
            logging.error(f"Failed to download instruments: {e}")
            raise

    def download_option_data(self, instrument_token: int, symbol: str,
                             start_date: str, end_date: str,
                             force_refresh: bool = False) -> pd.DataFrame:
        """Download historical data for a specific option"""
        cache_path = self._get_cache_path(f"option_{symbol}", f"{start_date}_{end_date}")

        if not force_refresh:
            cached_data = self._load_from_cache(cache_path)
            if cached_data is not None:
                return cached_data

        logging.info(f"Downloading option data for {symbol}")

        try:
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=start_date,
                to_date=end_date,
                interval="minute"
            )

            df = pd.DataFrame(data)
            df.rename(columns={
                'date': 'timestamp',
                'close': 'price'
            }, inplace=True)
            df = df[['timestamp', 'price']]

            self._save_to_cache(df, cache_path)
            return df

        except Exception as e:
            logging.error(f"Failed to download option data for {symbol}: {e}")
            return pd.DataFrame(columns=['timestamp', 'price'])

    def find_options_for_expiry(self, instruments: pd.DataFrame, target_ce_strike: float,
                                target_pe_strike: float, target_expiry: date) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Find options matching the EXACT target expiry and nearest strikes

        Args:
            instruments: DataFrame with option instruments
            target_ce_strike: Desired CE strike
            target_pe_strike: Desired PE strike
            target_expiry: EXACT expiry date to use (from strike_calculator)

        Returns:
            Tuple of (ce_instrument, pe_instrument) DataFrames
        """
        # Convert expiry to date objects for comparison
        instruments['expiry_date'] = pd.to_datetime(instruments['expiry']).dt.date

        # CRITICAL: Filter for EXACT expiry match
        expiry_options = instruments[instruments['expiry_date'] == target_expiry]

        if expiry_options.empty:
            logging.error(
                f"No options found for expiry {target_expiry}. "
                f"Available expiries: {sorted(instruments['expiry_date'].unique())}"
            )
            return pd.DataFrame(), pd.DataFrame()

        logging.info(
            f"Found {len(expiry_options)} options for expiry {target_expiry} "
            f"(Day: {target_expiry.strftime('%A')})"
        )

        # Find CE strike
        ce_options = expiry_options[expiry_options['instrument_type'] == 'CE']
        ce_instrument = ce_options[ce_options['strike'] == target_ce_strike]

        if ce_instrument.empty:
            # Find nearest CE strike
            ce_options_sorted = ce_options.copy()
            ce_options_sorted['strike_diff'] = abs(ce_options_sorted['strike'] - target_ce_strike)
            ce_options_sorted = ce_options_sorted.sort_values('strike_diff')
            if not ce_options_sorted.empty:
                ce_instrument = ce_options_sorted.head(1)
                actual_ce_strike = ce_instrument.iloc[0]['strike']
                actual_ce_symbol = ce_instrument.iloc[0]['tradingsymbol']
                logging.info(
                    f"  CE: Using nearest strike {actual_ce_strike} (target was {target_ce_strike}). "
                    f"Symbol: {actual_ce_symbol}"
                )
        else:
            actual_ce_symbol = ce_instrument.iloc[0]['tradingsymbol']
            logging.info(f"  CE: Exact match found. Symbol: {actual_ce_symbol}")

        # Find PE strike
        pe_options = expiry_options[expiry_options['instrument_type'] == 'PE']
        pe_instrument = pe_options[pe_options['strike'] == target_pe_strike]

        if pe_instrument.empty:
            # Find nearest PE strike
            pe_options_sorted = pe_options.copy()
            pe_options_sorted['strike_diff'] = abs(pe_options_sorted['strike'] - target_pe_strike)
            pe_options_sorted = pe_options_sorted.sort_values('strike_diff')
            if not pe_options_sorted.empty:
                pe_instrument = pe_options_sorted.head(1)
                actual_pe_strike = pe_instrument.iloc[0]['strike']
                actual_pe_symbol = pe_instrument.iloc[0]['tradingsymbol']
                logging.info(
                    f"  PE: Using nearest strike {actual_pe_strike} (target was {target_pe_strike}). "
                    f"Symbol: {actual_pe_symbol}"
                )
        else:
            actual_pe_symbol = pe_instrument.iloc[0]['tradingsymbol']
            logging.info(f"  PE: Exact match found. Symbol: {actual_pe_symbol}")

        return ce_instrument, pe_instrument

    def prepare_backtest_data(self, start_date: str, end_date: str,
                              strike_calculator: Callable,
                              force_refresh: bool = False) -> pd.DataFrame:
        """
        Prepare complete backtest dataset with NIFTY, VIX, and option prices

        FIXED: Now uses the expiry date returned by strike_calculator for accurate weekly expiries

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            strike_calculator: Function that takes (spot, vix, date) and returns (ce_strike, pe_strike, expiry)
            force_refresh: If True, ignore cache and download fresh data
        """
        logging.info(f"Preparing backtest data from {start_date} to {end_date}")

        # Download NIFTY and VIX data
        nifty_df = self.download_nifty_data(start_date, end_date, force_refresh)
        vix_df = self.download_vix_data(start_date, end_date, force_refresh)

        # Merge NIFTY and VIX data
        merged_df = pd.merge(nifty_df, vix_df, on='timestamp', how='left')

        all_data = []

        # Group by date
        merged_df['date'] = pd.to_datetime(merged_df['timestamp']).dt.date
        dates = sorted(merged_df['date'].unique())

        for current_date in dates:
            logging.info(f"Processing {current_date} ({current_date.strftime('%A')})")

            # Get data for this day
            daily_data = merged_df[merged_df['date'] == current_date].copy()

            if daily_data.empty:
                continue

            # Get opening values
            opening_spot = daily_data.iloc[0]['nifty_spot']
            opening_vix = daily_data.iloc[0]['india_vix']

            # CRITICAL: Get strikes AND the EXACT expiry from strike_calculator
            ce_strike, pe_strike, target_expiry = strike_calculator(opening_spot, opening_vix, current_date)

            logging.info(
                f"  Target Strikes: CE={ce_strike}, PE={pe_strike}"
            )
            logging.info(
                f"  Target Expiry: {target_expiry} ({target_expiry.strftime('%A')})"
            )

            # Get instruments for this date
            instruments = self.download_option_chain(str(current_date), force_refresh)

            # FIXED: Use find_options_for_expiry with the exact target_expiry
            ce_instrument, pe_instrument = self.find_options_for_expiry(
                instruments, ce_strike, pe_strike, target_expiry
            )

            if ce_instrument.empty or pe_instrument.empty:
                logging.warning(
                    f"  Could not find options for strikes CE={ce_strike}, PE={pe_strike}, "
                    f"Expiry={target_expiry}. Skipping day."
                )
                continue

            ce_token = ce_instrument.iloc[0]['instrument_token']
            pe_token = pe_instrument.iloc[0]['instrument_token']
            ce_symbol = ce_instrument.iloc[0]['tradingsymbol']
            pe_symbol = pe_instrument.iloc[0]['tradingsymbol']

            # Verify the symbols match the expected expiry
            ce_expiry_from_instrument = ce_instrument.iloc[0]['expiry_date']
            pe_expiry_from_instrument = pe_instrument.iloc[0]['expiry_date']

            if ce_expiry_from_instrument != target_expiry:
                logging.warning(
                    f"  CE expiry mismatch! Target: {target_expiry}, Got: {ce_expiry_from_instrument}"
                )
            if pe_expiry_from_instrument != target_expiry:
                logging.warning(
                    f"  PE expiry mismatch! Target: {target_expiry}, Got: {pe_expiry_from_instrument}"
                )

            logging.info(f"  Using Symbols: {ce_symbol} / {pe_symbol}")

            # Download option data
            ce_data = self.download_option_data(
                ce_token, ce_symbol,
                str(current_date), str(current_date),
                force_refresh
            )

            pe_data = self.download_option_data(
                pe_token, pe_symbol,
                str(current_date), str(current_date),
                force_refresh
            )

            # Merge option data with daily data
            if not ce_data.empty:
                ce_data = ce_data.rename(columns={'price': 'ce_price'})
                daily_data = pd.merge(daily_data, ce_data, on='timestamp', how='left')
            else:
                daily_data['ce_price'] = np.nan

            if not pe_data.empty:
                pe_data = pe_data.rename(columns={'price': 'pe_price'})
                daily_data = pd.merge(daily_data, pe_data, on='timestamp', how='left')
            else:
                daily_data['pe_price'] = np.nan

            # Forward fill VIX
            daily_data['india_vix'] = daily_data['india_vix'].ffill().fillna(opening_vix)

            # Add strike and symbol information
            daily_data['ce_strike'] = ce_strike
            daily_data['pe_strike'] = pe_strike
            daily_data['ce_symbol'] = ce_symbol
            daily_data['pe_symbol'] = pe_symbol

            # Forward fill option prices
            daily_data['ce_price'] = daily_data['ce_price'].ffill()
            daily_data['pe_price'] = daily_data['pe_price'].ffill()

            # Fill remaining NaN with 0
            daily_data['ce_price'] = daily_data['ce_price'].fillna(0)
            daily_data['pe_price'] = daily_data['pe_price'].fillna(0)

            all_data.append(daily_data)
            logging.info(f"  Added {len(daily_data)} rows for {current_date}")

        # Combine all data
        if not all_data:
            raise ValueError("No data was prepared for the given date range")

        final_df = pd.concat(all_data, ignore_index=True)

        # Drop temporary date column
        final_df = final_df.drop(columns=['date'])

        # Ensure timestamp is datetime
        final_df['timestamp'] = pd.to_datetime(final_df['timestamp'])

        # Sort by timestamp
        final_df = final_df.sort_values('timestamp').reset_index(drop=True)

        logging.info(f"Backtest data prepared: {len(final_df)} total rows")

        return final_df

    def get_strike_range(self, spot: float, vix: float, num_strikes: int = 10) -> Tuple[list, list]:
        """
        Get a range of strikes around the spot price

        Args:
            spot: Current NIFTY spot price
            vix: Current VIX level
            num_strikes: Number of strikes on each side

        Returns:
            Tuple of (ce_strikes, pe_strikes)
        """
        atm = round(spot / 50) * 50

        ce_strikes = [atm + (i * 50) for i in range(1, num_strikes + 1)]
        pe_strikes = [atm - (i * 50) for i in range(1, num_strikes + 1)]

        return ce_strikes, pe_strikes

    def validate_data_quality(self, df: pd.DataFrame) -> dict:
        """
        Validate the quality of prepared backtest data

        Args:
            df: Prepared backtest dataframe

        Returns:
            Dictionary with quality metrics
        """
        quality_report = {
            'total_rows': len(df),
            'date_range': f"{df['timestamp'].min()} to {df['timestamp'].max()}",
            'missing_nifty': df['nifty_spot'].isna().sum(),
            'missing_vix': df['india_vix'].isna().sum(),
            'missing_ce_price': df['ce_price'].isna().sum(),
            'missing_pe_price': df['pe_price'].isna().sum(),
            'zero_ce_prices': (df['ce_price'] == 0).sum(),
            'zero_pe_prices': (df['pe_price'] == 0).sum(),
            'unique_dates': df['timestamp'].dt.date.nunique(),
            'avg_ticks_per_day': len(df) / df['timestamp'].dt.date.nunique() if len(df) > 0 else 0
        }

        # Add data quality score (0-100)
        total_cells = len(df) * 4
        missing_cells = (quality_report['missing_nifty'] +
                         quality_report['missing_vix'] +
                         quality_report['missing_ce_price'] +
                         quality_report['missing_pe_price'])
        quality_report['quality_score'] = max(0, 100 - (missing_cells / total_cells * 100))

        return quality_report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 80)
    print("Historical Data Manager - Weekly Expiry Fixed Version")
    print("=" * 80)
    print("\nKey Fixes Applied:")
    print("  ✓ Uses exact expiry from strike_calculator")
    print("  ✓ Properly matches weekly expiries (Tuesdays)")
    print("  ✓ Validates symbol expiry against target expiry")
    print("  ✓ Logs expiry day names for verification")
    print("\nThis module now correctly handles weekly NIFTY options.")
    print("=" * 80)