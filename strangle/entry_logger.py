"""
Entry Decision Logger - Precise day-wise entry tracking
Save as: strangle/entry_logger.py
FIXED: Added 'avg_vix' to the summary dict to match run.py
"""

import csv
import os
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any
from pathlib import Path
import pandas as pd


class EntryLogger:
    """Logs one-line entry decisions per day for easy triage"""

    def __init__(self, log_file: str = "entry_decisions.csv"):
        self.log_file = log_file
        self.current_date = None
        self.entry_attempted_today = False
        self._initialize_log()

    def _initialize_log(self):
        """Create log file with headers if it doesn't exist"""
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Date',
                    'Time',
                    'Entry_Approved',
                    'VIX',
                    'IV_Rank',
                    'IV_Percentile',
                    'Spot',
                    'CE_Strike',
                    'PE_Strike',
                    'CE_Delta',
                    'PE_Delta',
                    'Combined_Premium',
                    'Lots',
                    'Reason'
                ])

    def log_decision(self, market_data, approved: str, reason: str, lots: int = 0, combined_premium: float = 0.0):
        """
        Logs a single entry decision for the day.
        """
        current_date_str = market_data.timestamp.strftime('%Y-%m-%d')
        current_time_str = market_data.timestamp.strftime('%H:%M:%S')

        if current_date_str == self.current_date and self.entry_attempted_today:
            return

        ce_strike = 0.0
        pe_strike = 0.0
        ce_delta = 0.0
        pe_delta = 0.0

        try:
            with open(self.log_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    current_date_str,
                    current_time_str,
                    approved,
                    f"{market_data.india_vix:.2f}",
                    f"{market_data.iv_rank:.1f}",
                    f"{market_data.iv_percentile:.1f}",
                    f"{market_data.nifty_spot:.2f}",
                    ce_strike,
                    pe_strike,
                    ce_delta,
                    pe_delta,
                    f"{combined_premium:.2f}",
                    lots,
                    reason
                ])

            self.current_date = current_date_str
            if approved == 'YES':
                self.entry_attempted_today = True

        except Exception as e:
            logging.error(f"Error logging entry decision: {e}")

    def reset_daily(self):
        """Call at the start of a new trading day"""
        self.entry_attempted_today = False

    def get_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get summary metrics from the log file"""
        default_summary = {
            "total_days": 0,
            "approved_days": 0,
            "rejected_days": 0,
            "avg_premium": 0.0,
            "approval_rate": 0.0,
            "avg_vix": 0.0  # Default value
        }

        if not os.path.exists(self.log_file):
            logging.warning(f"Log file not found at {self.log_file}. Returning empty summary.")
            return default_summary

        try:
            df = pd.read_csv(self.log_file, header=0)
        except pd.errors.EmptyDataError:
            logging.warning(f"Log file {self.log_file} is empty. Returning empty summary.")
            return default_summary
        except Exception as e:
            logging.error(f"Failed to read entry log: {e}")
            return default_summary

        if df.empty:
            return default_summary

        try:
            df['Date'] = pd.to_datetime(df['Date'])
            unique_dates = df['Date'].unique()
            if len(unique_dates) > days:
                start_date = unique_dates[-days]
                df = df[df['Date'] >= start_date]

            df['Entry_Approved'] = df['Entry_Approved'].astype(str).str.upper().str.strip()
            total_days = len(df['Date'].unique())
            approved_days = len(df[df['Entry_Approved'] == 'YES'])

            avg_premium = 0.0
            if approved_days > 0:
                 avg_premium = df[df['Entry_Approved'] == 'YES']['Combined_Premium'].mean()

            approval_rate = 0.0
            if total_days > 0:
                approval_rate = (approved_days / total_days) * 100

            # --- FIX: Calculate and add 'avg_vix' ---
            avg_vix = 0.0
            if total_days > 0 and 'VIX' in df.columns:
                # Ensure VIX is numeric, handling potential string formatting
                avg_vix = pd.to_numeric(df['VIX'], errors='coerce').mean()

            return {
                "total_days": total_days,
                "approved_days": approved_days,
                "rejected_days": total_days - approved_days,
                "avg_premium": avg_premium,
                "approval_rate": approval_rate,
                "avg_vix": avg_vix # Add the key run.py is looking for
            }

        except KeyError as e:
            logging.error(f"Header mismatch in {self.log_file}. Missing key: {e}")
            logging.error("Please delete the log file and re-run.")
            return default_summary

    def print_recent(self, days: int = 10):
        """Print recent entry decisions"""
        if not os.path.exists(self.log_file):
            print("No entry log found")
            return

        try:
            df = pd.read_csv(self.log_file, header=0)
        except pd.errors.EmptyDataError:
            print("Entry log is empty.")
            return

        if df.empty:
            print("Entry log is empty")
            return

        recent = df.tail(days)

        print("\n" + "=" * 120)
        print("RECENT ENTRY DECISIONS")
        print("=" * 120)

        for _, row in recent.iterrows():
            try:
                status = "✓ ENTERED" if row['Entry_Approved'].upper().strip() == 'YES' else "✗ SKIPPED"

                if row['Entry_Approved'].upper().strip() == 'YES':
                    print(
                        f"{row['Date']} {row['Time']} | {status} | "
                        f"VIX={row['VIX']} IV_R={row['IV_Rank']}% | "
                        f"CE:{row['CE_Strike']} PE:{row['PE_Strike']} | "
                        f"Premium={row['Combined_Premium']} Lots={row['Lots']} | "
                        f"{row['Reason']}"
                    )
                else:
                    print(
                        f"{row['Date']} {row['Time']} | {status} | "
                        f"VIX={row['VIX']} IV_R={row['IV_Rank']}% | "
                        f"Reason: {row['Reason']}"
                    )
            except KeyError as e:
                print(f"Error parsing log row, missing key: {e}. Row: {row}")