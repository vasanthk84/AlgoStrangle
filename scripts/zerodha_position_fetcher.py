"""
Zerodha NIFTY Options Position Fetcher
Fetches open NIFTY weekly options positions and saves to CSV
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from kiteconnect import KiteConnect
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class ZerodhaPositionFetcher:
    def __init__(self, api_key: str, access_token_file: str = "access_token.txt"):
        """
        Initialize the position fetcher
        
        Args:
            api_key: Your Zerodha API key
            access_token_file: Path to file containing access token
        """
        self.api_key = api_key
        self.access_token_file = access_token_file
        self.kite = KiteConnect(api_key=api_key)
        self.instruments_cache = None
        
    def authenticate(self) -> bool:
        """Authenticate with Zerodha using stored access token"""
        try:
            token_file = Path(self.access_token_file)
            if token_file.exists():
                with open(token_file, "r") as f:
                    content = f.read().strip()
                    if ',' in content:
                        access_token, expiry = content.split(",")
                        expiry_dt = pd.to_datetime(expiry)
                        
                        if expiry_dt > datetime.now():
                            self.kite.set_access_token(access_token)
                            # Test authentication
                            self.kite.profile()
                            logging.info("✓ Authentication successful using stored token")
                            return True
                        else:
                            logging.warning("Stored access token has expired")
            
            # Need new authentication
            logging.info("Generating new access token...")
            print(f"\nVisit this URL to authenticate:\n{self.kite.login_url()}\n")
            
            import webbrowser
            webbrowser.open(self.kite.login_url())
            
            request_token = input("Enter the request_token from the URL after login: ").strip()
            
            # You need to provide your API secret here
            api_secret = input("Enter your API secret: ").strip()
            
            data = self.kite.generate_session(request_token, api_secret=api_secret)
            access_token = data["access_token"]
            
            # Save token with expiry (valid till midnight)
            expiry = (datetime.now() + pd.Timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            
            with open(token_file, "w") as f:
                f.write(f"{access_token},{expiry.isoformat()}")
            
            self.kite.set_access_token(access_token)
            logging.info("✓ New authentication successful")
            return True
            
        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            return False
    
    def fetch_nfo_instruments(self) -> pd.DataFrame:
        """Fetch and cache NFO instruments"""
        if self.instruments_cache is not None:
            return self.instruments_cache
        
        try:
            logging.info("Fetching NFO instruments...")
            instruments = self.kite.instruments("NFO")
            df = pd.DataFrame(instruments)
            
            # Filter for NIFTY options only
            nifty_options = df[
                (df['name'] == 'NIFTY') &
                (df['instrument_type'].isin(['CE', 'PE']))
            ].copy()
            
            # Ensure expiry is datetime
            nifty_options['expiry'] = pd.to_datetime(nifty_options['expiry'])
            
            self.instruments_cache = nifty_options
            logging.info(f"✓ Cached {len(nifty_options)} NIFTY option instruments")
            return nifty_options
            
        except Exception as e:
            logging.error(f"Failed to fetch instruments: {e}")
            return pd.DataFrame()
    
    def get_positions(self) -> List[Dict]:
        """Fetch current positions from Zerodha"""
        try:
            positions = self.kite.positions()
            net_positions = positions.get('net', [])
            
            # Filter for NIFTY options with non-zero quantity
            nifty_positions = []
            for pos in net_positions:
                if pos['quantity'] != 0 and 'NIFTY' in pos['tradingsymbol']:
                    nifty_positions.append(pos)
            
            logging.info(f"✓ Found {len(nifty_positions)} NIFTY option positions")
            return nifty_positions
            
        except Exception as e:
            logging.error(f"Failed to fetch positions: {e}")
            return []
    
    def enrich_position_with_details(self, position: Dict, instruments_df: pd.DataFrame) -> Optional[Dict]:
        """
        Enrich position data with instrument details
        
        Returns enriched position dict or None if not found
        """
        tradingsymbol = position['tradingsymbol']
        
        # Find instrument details
        instrument = instruments_df[
            instruments_df['tradingsymbol'] == tradingsymbol
        ]
        
        if instrument.empty:
            logging.warning(f"Instrument not found: {tradingsymbol}")
            return None
        
        instrument = instrument.iloc[0]
        
        # Determine direction
        qty = position['quantity']
        direction = "SELL" if qty < 0 else "BUY"
        
        # Get absolute quantity in lots (NIFTY lot size = 75)
        abs_qty = abs(qty)
        lots = abs_qty // 75
        
        if lots == 0:
            logging.warning(f"Position too small (< 1 lot): {tradingsymbol}")
            return None
        
        # Build enriched data
        enriched = {
            'symbol': f"NFO:{tradingsymbol}",
            'option_type': instrument['instrument_type'],
            'strike_price': int(instrument['strike']),
            'qty': lots,
            'direction': direction,
            'entry_price': position['average_price'],
            'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # Approximate
            'expiry_date': instrument['expiry'].strftime('%Y-%m-%d'),
            'current_price': position['last_price'],
            'pnl': position['pnl']
        }
        
        return enriched
    
    def fetch_and_save_positions(self, output_file: str = "manual_trades.csv") -> bool:
        """
        Main function: Fetch positions and save to CSV
        
        Args:
            output_file: Path to output CSV file
            
        Returns:
            True if successful, False otherwise
        """
        logging.info("=" * 80)
        logging.info("ZERODHA NIFTY OPTIONS POSITION FETCHER")
        logging.info("=" * 80)
        
        # Step 1: Authenticate
        if not self.authenticate():
            logging.error("Authentication failed. Exiting.")
            return False
        
        # Step 2: Fetch instruments
        instruments_df = self.fetch_nfo_instruments()
        if instruments_df.empty:
            logging.error("Failed to fetch instruments. Exiting.")
            return False
        
        # Step 3: Fetch positions
        positions = self.get_positions()
        if not positions:
            logging.warning("No NIFTY option positions found.")
            return False
        
        # Step 4: Enrich positions with details
        enriched_positions = []
        for pos in positions:
            enriched = self.enrich_position_with_details(pos, instruments_df)
            if enriched:
                enriched_positions.append(enriched)
        
        if not enriched_positions:
            logging.warning("No valid positions to export.")
            return False
        
        # Step 5: Save to CSV
        try:
            output_path = Path(output_file)
            
            # Write CSV with exact format
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'symbol', 'option_type', 'strike_price', 'qty', 
                    'direction', 'entry_price', 'entry_time', 'expiry_date'
                ])
                writer.writeheader()
                
                for pos in enriched_positions:
                    writer.writerow({
                        'symbol': pos['symbol'],
                        'option_type': pos['option_type'],
                        'strike_price': pos['strike_price'],
                        'qty': pos['qty'],
                        'direction': pos['direction'],
                        'entry_price': f"{pos['entry_price']:.2f}",
                        'entry_time': pos['entry_time'],
                        'expiry_date': pos['expiry_date']
                    })
            
            logging.info(f"✓ Successfully saved {len(enriched_positions)} positions to {output_file}")
            
            # Display summary
            print(f"\n{'=' * 80}")
            print("POSITIONS EXPORTED:")
            print(f"{'=' * 80}")
            
            for pos in enriched_positions:
                pnl_str = f"₹{pos['pnl']:+,.2f}" if pos['pnl'] != 0 else "N/A"
                print(f"{pos['symbol']}")
                print(f"  {pos['option_type']} {pos['strike_price']} | "
                      f"{pos['direction']} {pos['qty']} lots @ ₹{pos['entry_price']:.2f}")
                print(f"  Current: ₹{pos['current_price']:.2f} | P&L: {pnl_str}")
                print()
            
            print(f"{'=' * 80}")
            print(f"✓ Saved to: {output_path.absolute()}")
            print(f"{'=' * 80}\n")
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to save CSV: {e}")
            return False


def main():
    """Main execution function"""
    print("""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                  ZERODHA NIFTY OPTIONS POSITION FETCHER                       ║
║                                                                               ║
║  This utility fetches your open NIFTY weekly options positions from Zerodha  ║
║  and saves them to manual_trades.csv for import into the trading system.     ║
╚═══════════════════════════════════════════════════════════════════════════════╝
""")
    
    # Configuration (use same values from your config.py)
    API_KEY = "qdss2yswc2iuen3j"
    ACCESS_TOKEN_FILE = "access_token.txt"
    OUTPUT_FILE = "manual_trades.csv"
    
    # Create fetcher and run
    fetcher = ZerodhaPositionFetcher(API_KEY, ACCESS_TOKEN_FILE)
    success = fetcher.fetch_and_save_positions(OUTPUT_FILE)
    
    if success:
        print("✓ Position export completed successfully!")
        print(f"\nYou can now run the trading system with:")
        print("  python run.py")
        print("  Select mode: 4 (Manage Manual Trades)")
    else:
        print("✗ Position export failed. Check logs for details.")


if __name__ == "__main__":
    main()
