"""
debug_instruments.py
Check what instruments are available for a specific date
"""

from kiteconnect import KiteConnect
from historical_data_manager import HistoricalDataManager
from datetime import datetime, date
import pandas as pd
from colorama import Fore, Style

# Your API credentials
API_KEY = "qdss2yswc2iuen3j"
API_SECRET = "q9cfy774cgt8z0exp0tlat4rntj7huqs"

def authenticate_kite():
    """Authenticate with Kite"""
    kite = KiteConnect(api_key=API_KEY)
    
    try:
        # Try to load existing token
        with open("access_token.txt", "r") as f:
            access_token, expiry = f.read().split(",")
            expiry = pd.to_datetime(expiry)
            if expiry > datetime.now():
                kite.set_access_token(access_token)
                print(f"{Fore.GREEN}Using existing access token{Style.RESET_ALL}")
                return kite
    except:
        pass
    
    # Generate new token
    print(f"Visit: {kite.login_url()}")
    request_token = input("Enter request_token: ").strip()
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]
    
    expiry = (datetime.now() + pd.Timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    with open("access_token.txt", "w") as f:
        f.write(f"{access_token},{expiry.isoformat()}")
    
    kite.set_access_token(access_token)
    return kite


def check_date_availability(target_date_str: str):
    """Check what data is available for a specific date"""
    target_date = pd.to_datetime(target_date_str).date()
    
    print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}CHECKING INSTRUMENTS FOR: {target_date}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")
    
    # Authenticate
    kite = authenticate_kite()
    
    # Create data manager
    data_manager = HistoricalDataManager(kite, "backtest_cache")
    
    # Get instruments
    print("Fetching instruments from Kite API...")
    instruments = kite.instruments("NFO")
    nifty_options = [i for i in instruments if i['name'] == 'NIFTY' and i['instrument_type'] in ['CE', 'PE']]
    
    print(f"Total NIFTY options: {len(nifty_options)}\n")
    
    # Check expiries available
    expiries = sorted(set(i['expiry'] for i in nifty_options if i.get('expiry')))
    print(f"{Fore.GREEN}Available Expiries:{Style.RESET_ALL}")
    for exp in expiries[:10]:  # Show first 10
        exp_date = pd.to_datetime(exp).date() if isinstance(exp, str) else exp
        print(f"  {exp_date}")
    if len(expiries) > 10:
        print(f"  ... and {len(expiries) - 10} more")
    
    # Check strikes for nearest expiry
    if expiries:
        nearest_expiry = expiries[0]
        nearest_exp_date = pd.to_datetime(nearest_expiry).date() if isinstance(nearest_expiry, str) else nearest_expiry
        
        print(f"\n{Fore.GREEN}Strikes for expiry {nearest_exp_date}:{Style.RESET_ALL}")
        
        ce_strikes = sorted(set(i['strike'] for i in nifty_options 
                               if i['expiry'] == nearest_expiry and i['instrument_type'] == 'CE'))
        pe_strikes = sorted(set(i['strike'] for i in nifty_options 
                               if i['expiry'] == nearest_expiry and i['instrument_type'] == 'PE'))
        
        print(f"  CE strikes ({len(ce_strikes)} total):")
        print(f"    Min: {ce_strikes[0] if ce_strikes else 'N/A'}")
        print(f"    Max: {ce_strikes[-1] if ce_strikes else 'N/A'}")
        print(f"    Sample: {ce_strikes[::len(ce_strikes)//10] if ce_strikes else 'N/A'}")
        
        print(f"  PE strikes ({len(pe_strikes)} total):")
        print(f"    Min: {pe_strikes[0] if pe_strikes else 'N/A'}")
        print(f"    Max: {pe_strikes[-1] if pe_strikes else 'N/A'}")
        print(f"    Sample: {pe_strikes[::len(pe_strikes)//10] if pe_strikes else 'N/A'}")
    
    # Check historical data availability
    print(f"\n{Fore.CYAN}Checking Historical Data Availability:{Style.RESET_ALL}")
    
    # NIFTY spot
    try:
        nifty_token = 256265
        nifty_data = kite.historical_data(
            instrument_token=nifty_token,
            from_date=target_date_str,
            to_date=target_date_str,
            interval="minute"
        )
        if nifty_data:
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} NIFTY spot data: {len(nifty_data)} records")
        else:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} NIFTY spot data: No data")
    except Exception as e:
        print(f"  {Fore.RED}✗{Style.RESET_ALL} NIFTY spot data: Error - {e}")
    
    # VIX
    try:
        vix_token = 264969
        vix_data = kite.historical_data(
            instrument_token=vix_token,
            from_date=target_date_str,
            to_date=target_date_str,
            interval="minute"
        )
        if vix_data:
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} VIX data: {len(vix_data)} records")
        else:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} VIX data: No data")
    except Exception as e:
        print(f"  {Fore.RED}✗{Style.RESET_ALL} VIX data: Error - {e}")
    
    # Sample option
    if nifty_options:
        sample_option = nifty_options[0]
        try:
            option_data = kite.historical_data(
                instrument_token=sample_option['instrument_token'],
                from_date=target_date_str,
                to_date=target_date_str,
                interval="minute"
            )
            if option_data:
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Option data (sample): {len(option_data)} records")
                print(f"    Tested: {sample_option['tradingsymbol']}")
            else:
                print(f"  {Fore.RED}✗{Style.RESET_ALL} Option data (sample): No data")
                print(f"    Tested: {sample_option['tradingsymbol']}")
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} Option data (sample): Error - {e}")
    
    print(f"\n{Fore.YELLOW}Recommendation:{Style.RESET_ALL}")
    if target_date > date.today():
        print(f"  {Fore.RED}The selected date is in the FUTURE!{Style.RESET_ALL}")
        print(f"  Please select a date from the past where actual trading occurred.")
        print(f"  Suggested date range: 2024-01-01 to {date.today() - pd.Timedelta(days=7)}")
    elif target_date > date.today() - pd.Timedelta(days=7):
        print(f"  {Fore.YELLOW}The selected date is very recent.{Style.RESET_ALL}")
        print(f"  Some data might not be available yet.")
        print(f"  Try a date at least 1 week in the past.")
    else:
        print(f"  {Fore.GREEN}Date looks good for backtesting!{Style.RESET_ALL}")


def main():
    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  INSTRUMENTS & DATA AVAILABILITY CHECKER  {Style.RESET_ALL}
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
""")
    
    target_date = input("Enter date to check (YYYY-MM-DD): ").strip()
    
    try:
        pd.to_datetime(target_date)
        check_date_availability(target_date)
    except ValueError:
        print(f"{Fore.RED}Invalid date format. Use YYYY-MM-DD{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
