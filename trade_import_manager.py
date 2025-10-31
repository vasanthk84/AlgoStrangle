"""
trade_import_manager.py
Import and manage manually executed trades from CSV file

USAGE:
1. Execute your trades manually on broker
2. Update manual_trades.csv with trade details
3. Run system in "Manage Mode" - it will monitor and adjust trades
"""

import logging
import csv
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict
import pandas as pd

from strangle import Trade, Direction


class ManualTradeImporter:
    """
    Imports manually executed trades from CSV file for system monitoring
    """
    
    def __init__(self, csv_file: str = "manual_trades.csv"):
        self.csv_file = csv_file
        self.required_columns = [
            'symbol',           # e.g., NFO:NIFTY25N0426600CE
            'option_type',      # CE or PE
            'strike_price',     # e.g., 26600
            'qty',              # Number of lots
            'direction',        # SELL or BUY
            'entry_price',      # Price at which you entered
            'entry_time',       # YYYY-MM-DD HH:MM:SS
            'expiry_date'       # YYYY-MM-DD
        ]
        
    def create_template_if_missing(self):
        """Creates a template CSV file if it doesn't exist"""
        if not Path(self.csv_file).exists():
            logging.info(f"Creating template file: {self.csv_file}")
            
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.required_columns)
                
                # Add example row
                writer.writerow([
                    'NFO:NIFTY25N0426600CE',  # symbol
                    'CE',                      # option_type
                    '26600',                   # strike_price
                    '2',                       # qty
                    'SELL',                    # direction
                    '85.50',                   # entry_price
                    '2025-10-30 09:20:00',     # entry_time
                    '2025-11-04'               # expiry_date
                ])
                writer.writerow([
                    'NFO:NIFTY25N0425600PE',  # symbol
                    'PE',                      # option_type
                    '25600',                   # strike_price
                    '2',                       # qty
                    'SELL',                    # direction
                    '78.25',                   # entry_price
                    '2025-10-30 09:20:00',     # entry_time
                    '2025-11-04'               # expiry_date
                ])
                
            print(f"✅ Template created: {self.csv_file}")
            print(f"📝 Edit this file with your actual trade details")
            
    def validate_csv(self) -> bool:
        """Validates the CSV file format"""
        try:
            df = pd.read_csv(self.csv_file)
            
            # Check for required columns
            missing_cols = [col for col in self.required_columns if col not in df.columns]
            
            if missing_cols:
                logging.error(f"Missing required columns: {missing_cols}")
                return False
                
            # Check for empty file (only headers)
            if len(df) == 0:
                logging.warning(f"CSV file is empty (no trades to import)")
                return False
                
            return True
            
        except FileNotFoundError:
            logging.error(f"File not found: {self.csv_file}")
            return False
        except Exception as e:
            logging.error(f"Failed to validate CSV: {e}")
            return False
            
    def import_trades(self, lot_size: int = 75) -> List[Trade]:
        """
        Import trades from CSV file
        
        Returns:
            List of Trade objects
        """
        if not self.validate_csv():
            return []
            
        try:
            df = pd.read_csv(self.csv_file)
            imported_trades = []
            
            for idx, row in df.iterrows():
                try:
                    # Parse direction
                    direction = Direction.SELL if row['direction'].upper() == 'SELL' else Direction.BUY
                    
                    # Parse entry time
                    entry_time = pd.to_datetime(row['entry_time'])
                    
                    # Parse expiry date
                    expiry_date = pd.to_datetime(row['expiry_date']).date()
                    
                    # Generate unique trade ID
                    trade_id = f"manual_{idx}_{datetime.now().strftime('%H%M%S')}"
                    
                    # Create Trade object
                    trade = Trade(
                        trade_id=trade_id,
                        symbol=row['symbol'],
                        qty=int(row['qty']),
                        direction=direction,
                        price=float(row['entry_price']),
                        timestamp=entry_time,
                        option_type=row['option_type'],
                        lot_size=lot_size,
                        strike_price=float(row['strike_price']),
                        expiry=expiry_date,
                        spot_at_entry=float(row['strike_price'])  # Estimate
                    )
                    
                    imported_trades.append(trade)
                    
                    logging.info(
                        f"✅ Imported: {row['option_type']} {row['strike_price']} | "
                        f"Qty: {row['qty']} lots | Entry: ₹{row['entry_price']}"
                    )
                    
                except Exception as e:
                    logging.error(f"Failed to import row {idx}: {e}")
                    continue
                    
            return imported_trades
            
        except Exception as e:
            logging.error(f"Failed to import trades: {e}")
            return []
            
    def export_active_trades_to_csv(self, active_trades: Dict, output_file: str = None):
        """
        Export current active trades back to CSV (for manual editing)
        
        Args:
            active_trades: Dictionary of Trade objects
            output_file: Output filename (default: manual_trades_export.csv)
        """
        if output_file is None:
            output_file = f"manual_trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.required_columns + ['current_price', 'pnl', 'pnl_pct'])
                
                for trade in active_trades.values():
                    writer.writerow([
                        trade.symbol,
                        trade.option_type,
                        trade.strike_price,
                        trade.qty,
                        trade.direction.value,
                        trade.entry_price,
                        trade.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        trade.expiry.strftime('%Y-%m-%d') if trade.expiry else '',
                        trade.current_price,
                        f"{trade.get_pnl():.2f}",
                        f"{trade.get_pnl_pct():.2f}"
                    ])
                    
            logging.info(f"✅ Exported active trades to: {output_file}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to export trades: {e}")
            return False


def print_import_instructions():
    """Print instructions for using manual trade import"""
    print("""
╔════════════════════════════════════════════════════════════════════════════════╗
║                       MANUAL TRADE IMPORT MODE                                 ║
╠════════════════════════════════════════════════════════════════════════════════╣
║                                                                                ║
║  📝 STEP 1: Execute Trades Manually                                           ║
║     - Place your trades through broker app/website                            ║
║     - Note down: Symbol, Strike, Entry Price, Qty, Time                       ║
║                                                                                ║
║  📋 STEP 2: Update manual_trades.csv                                          ║
║     - Open manual_trades.csv in any text editor                               ║
║     - Add your trade details (one trade per row)                              ║
║     - Save the file                                                            ║
║                                                                                ║
║  🚀 STEP 3: Run System in Manage Mode                                         ║
║     - System will import trades and start monitoring                          ║
║     - It will apply stops, rolls, and adjustments automatically               ║
║     - No new trades will be initiated                                         ║
║                                                                                ║
║  ⚙️  WHAT SYSTEM WILL DO:                                                      ║
║     ✅ Monitor live prices and calculate P&L                                   ║
║     ✅ Calculate Greeks (Delta, Theta, Gamma) in real-time                     ║
║     ✅ Apply HARD STOP (30% loss) automatically                                ║
║     ✅ Roll positions when Delta hits 30                                       ║
║     ✅ Exit at profit target (50%)                                             ║
║     ✅ Square off at 15:20 IST                                                 ║
║     ✅ Send Telegram alerts for all actions                                    ║
║                                                                                ║
║  🎯 PERFECT FOR:                                                               ║
║     - Trading from different timezones (CST, PST, etc.)                       ║
║     - Manual trade execution + automated management                           ║
║     - Stepping away from desk while trades are monitored                      ║
║                                                                                ║
╚════════════════════════════════════════════════════════════════════════════════╝

CSV FORMAT EXAMPLE:
symbol,option_type,strike_price,qty,direction,entry_price,entry_time,expiry_date
NFO:NIFTY25N0426600CE,CE,26600,2,SELL,85.50,2025-10-30 09:20:00,2025-11-04
NFO:NIFTY25N0425600PE,PE,25600,2,SELL,78.25,2025-10-30 09:20:00,2025-11-04

⚠️  IMPORTANT NOTES:
  • Symbol format: NFO:NIFTY[YY][MONTH][DD][STRIKE][CE/PE]
  • Time format: YYYY-MM-DD HH:MM:SS (IST timezone assumed)
  • Expiry format: YYYY-MM-DD (Next Tuesday for weekly options)
  • Direction: SELL for short strangle (most common)
  
💡 TIP: After importing, system will create trade pairs automatically
    """)


if __name__ == "__main__":
    # Test the importer
    logging.basicConfig(level=logging.INFO)
    
    print_import_instructions()
    
    importer = ManualTradeImporter()
    importer.create_template_if_missing()
    
    print("\n✅ Template file created. Edit 'manual_trades.csv' and run system in Manage Mode.")
