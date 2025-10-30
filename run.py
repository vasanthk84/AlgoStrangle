"""
run.py - Entry point for Short Strangle NIFTY Options Trading System
FIXED: Saves all final backtest CSV outputs into categorized /logs subdirectories.
"""

import sys
import time
import logging
from datetime import datetime, date
from typing import Tuple
import pandas as pd
import numpy as np
from colorama import Fore, Style
from tabulate import tabulate
import os
import shutil

# Import historical data manager
from historical_data_manager import HistoricalDataManager

# Import strangle package modules
from strangle import (
    Config,
    Utils,
    DatabaseManager,
    NotificationManager,
    BrokerInterface,
    TradeManager,
    ShortStrangleStrategy,
    ConsoleDashboard
)

# --- FIX: Create ALL log and output directories BEFORE setting up logging ---
os.makedirs(Config.LOG_DIR_MAIN, exist_ok=True)
os.makedirs(Config.LOG_DIR_CSV, exist_ok=True)
os.makedirs(Config.LOG_DIR_AUDIT, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_DATA, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_TRADES, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_PERF, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_SUMMARY, exist_ok=True)
# --- End Fix ---


def setup_logging():
    """Sets up the logging configuration."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def backtest_main(broker: BrokerInterface, start_date: str, end_date: str, force_refresh: bool = False):
    setup_logging()

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

    data_manager = HistoricalDataManager(broker.kite, Config.BACKTEST_CACHE_DIR)

    def calculate_strikes(spot: float, vix: float, current_date: date) -> Tuple[float, float, date]:
        # (Strike calculation logic remains the same)
        if vix > 20:
            otm_distance = 450
        elif vix > 15:
            otm_distance = 400
        else:
            otm_distance = 350
        ce_strike = round(spot / 50) * 50 + otm_distance
        pe_strike = round(spot / 50) * 50 - otm_distance
        current = pd.to_datetime(current_date)
        days_until_tuesday = (1 - current.weekday()) % 7
        if days_until_tuesday == 0 and current.time() >= pd.Timestamp('15:30').time():
            days_until_tuesday = 7
        if days_until_tuesday < Config.MIN_DTE_TO_HOLD:
             days_until_tuesday += 7
        expiry = (current + pd.Timedelta(days=days_until_tuesday)).date()
        return ce_strike, pe_strike, expiry

    print(f"{Fore.YELLOW}Downloading and preparing historical data...{Style.RESET_ALL}")
    print(f"Cache mode: {'REFRESH' if force_refresh else 'USE EXISTING'}")

    try:
        backtest_data = data_manager.prepare_backtest_data(
            start_date, end_date, calculate_strikes, force_refresh
        )

        # --- FIX: Save backtest_data_production.csv to logs/data/ ---
        output_filename = f"backtest_data_{start_date}_to_{end_date}.csv"
        output_file_path = os.path.join(Config.OUTPUT_DIR_DATA, output_filename)
        backtest_data.to_csv(output_file_path, index=False)
        print(f"{Fore.GREEN}Backtest data saved to: {output_file_path}{Style.RESET_ALL}")
        # --- End Fix ---

        print(f"Total data points: {len(backtest_data)}")
        print(f"Date range: {backtest_data['timestamp'].min()} to {backtest_data['timestamp'].max()}")

    except Exception as e:
        print(f"{Fore.RED}Failed to prepare backtest data: {e}{Style.RESET_ALL}")
        logging.error(f"Backtest data preparation failed: {e}", exc_info=True)
        return

    Config.PAPER_TRADING = True
    broker.backtest_data = backtest_data
    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    print(f"\n{Fore.CYAN}Starting backtest simulation...{Style.RESET_ALL}\n")

    # --- Backtest Loop (remains the same) ---
    trading_days = pd.date_range(start_date, end_date, freq='D')
    total_days = len([d for d in trading_days if not Utils.is_holiday(d.date())])
    current_day = 0
    for current_date in trading_days:
        if Utils.is_holiday(current_date.date()): continue
        current_day += 1
        daily_data = backtest_data[backtest_data['timestamp'].dt.date == current_date.date()]
        if daily_data.empty: continue
        print(f"\n{Fore.YELLOW}[Day {current_day}/{total_days}] Trading Day: {current_date.strftime('%Y-%m-%d')}{Style.RESET_ALL}")
        strategy.reset_daily_state()
        total_ticks = len(daily_data)
        last_progress = 0
        for idx, index in enumerate(daily_data.index):
            broker.current_index = index
            current_time = daily_data.loc[index, 'timestamp']
            strategy.run_cycle(current_time)
            progress = int((idx / total_ticks) * 100)
            if progress >= last_progress + 10:
                print(f"  Progress: {progress}% | Time: {current_time.strftime('%H:%M')} | VIX: {strategy.market_data.india_vix:.2f} | Active Trades: {len(trade_manager.active_trades)}", end='\r')
                last_progress = progress
        print() # Newline
        metrics = trade_manager.get_performance_metrics()
        db.save_daily_performance(current_date.strftime('%Y-%m-%d'), metrics)
        day_summary = f"DAY SUMMARY: Trades={metrics.total_trades}, P&L=Rs.{trade_manager.daily_pnl:,.2f}, CE=Rs.{metrics.ce_pnl:,.2f}, PE=Rs.{metrics.pe_pnl:,.2f}, Checks={strategy.entry_checks_today}"
        logging.info(day_summary)
        print(f"  {day_summary}")
    # --- End Backtest Loop ---

    # --- Final Summary and Export ---
    print(f"\n{'=' * 80}")
    print(f"{Fore.CYAN}BACKTEST SUMMARY - {start_date} to {end_date}{Style.RESET_ALL}")
    print(f"{'=' * 80}")

    final_metrics = trade_manager.get_performance_metrics()
    cumulative_pnl = sum(trade_manager.daily_pnl_history)

    # (Summary table printing remains the same)
    summary_data = [
        ["Total Trades", final_metrics.total_trades], ["Win Trades", final_metrics.win_trades],
        ["Win Rate", f"{final_metrics.win_rate:.1f}%"], ["Cumulative P&L", f"Rs.{cumulative_pnl:,.2f}"],
        ["Max Drawdown", f"Rs.{final_metrics.max_drawdown:,.2f}"], ["Profit Factor", f"{final_metrics.profit_factor:.2f}"],
        ["Sharpe Ratio", f"{final_metrics.sharpe_ratio:.2f}"], ["Rolled Positions", final_metrics.rolled_positions],
        ["Trading Days", len(trade_manager.daily_pnl_history)],
        ["Avg Daily P&L", f"Rs.{cumulative_pnl / len(trade_manager.daily_pnl_history):,.2f}" if trade_manager.daily_pnl_history else "N/A"]
    ]
    print(tabulate(summary_data, headers=["Metric", "Value"], tablefmt="grid"))
    if trade_manager.daily_pnl_history:
        print(f"\n{Fore.CYAN}Daily P&L Distribution:{Style.RESET_ALL}")
        daily_pnl_array = np.array(trade_manager.daily_pnl_history)
        print(f"  Min Daily P&L: Rs.{np.min(daily_pnl_array):,.2f}")
        print(f"  Max Daily P&L: Rs.{np.max(daily_pnl_array):,.2f}")
        # ... (rest of distribution printing) ...
        winning_days = len([p for p in daily_pnl_array if p > 0])
        total_d = len(daily_pnl_array)
        print(f"  Winning Days: {winning_days}/{total_d} ({winning_days / total_d * 100:.1f}%)")

    print(f"\n{Fore.GREEN}Exported Files:{Style.RESET_ALL}")
    print(f"  Database: {Config.DB_FILE}")
    print(f"  Log File: {Config.LOG_FILE}") # Correct path

    # --- FIX: Save Exports to Logs Subdirectories ---
    # Export trades to logs/trades/
    all_trades = db.get_all_trades()
    if not all_trades.empty:
        trades_filename = f"backtest_trades_{start_date}_to_{end_date}.csv"
        trades_filepath = os.path.join(Config.OUTPUT_DIR_TRADES, trades_filename)
        all_trades.to_csv(trades_filepath, index=False)
        print(f"  All Trades: {trades_filepath}")

    # Export daily performance to logs/performance/
    daily_perf = db.get_performance_history(days=9999) # Get all days
    if not daily_perf.empty:
        perf_filename = f"backtest_daily_performance_{start_date}_to_{end_date}.csv"
        perf_filepath = os.path.join(Config.OUTPUT_DIR_PERF, perf_filename)
        daily_perf.to_csv(perf_filepath, index=False)
        print(f"  Daily Performance: {perf_filepath}")

    # Export final entry decisions copy to logs/summary/
    if os.path.exists(Config.ENTRY_LOG_FILE):
        summary_filename = f"backtest_entry_decisions_{start_date}_to_{end_date}.csv"
        summary_filepath = os.path.join(Config.OUTPUT_DIR_SUMMARY, summary_filename)
        try:
            shutil.copy(Config.ENTRY_LOG_FILE, summary_filepath)
            print(f"  Entry Decisions Summary: {summary_filepath}")
        except Exception as e:
            logging.error(f"Failed to copy final entry decision log: {e}")
            print(f"{Fore.RED}  Failed to copy final entry decision log: {e}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}  Entry decision log file not found at: {Config.ENTRY_LOG_FILE}{Style.RESET_ALL}")
    # --- End Fix ---

    # (Entry decision summary printing remains the same)
    print(f"\n{'=' * 80}")
    print(f"{Fore.CYAN}ENTRY DECISION SUMMARY{Style.RESET_ALL}")
    print(f"{'=' * 80}")
    summary = strategy.entry_logger.get_summary(days=9999) # Get summary for all days
    if summary:
        entry_summary_data = [
            ["Total Trading Days", summary['total_days']], ["Days with Entry", summary['approved_days']],
            ["Days Skipped", summary['rejected_days']], ["Entry Rate", f"{summary['approval_rate']:.1f}%"],
            ["Avg VIX", f"{summary['avg_vix']:.2f}"],
        ]
        if 'avg_premium' in summary and not pd.isna(summary['avg_premium']):
            entry_summary_data.append(["Avg Combined Premium", f"Rs.{summary['avg_premium']:.2f}"])
        print(tabulate(entry_summary_data, headers=["Metric", "Value"], tablefmt="grid"))
    else:
        print(f"{Fore.YELLOW}No entry decisions recorded{Style.RESET_ALL}")
    print(f"\n{Fore.GREEN}Runtime Entry Decision Log: {Config.ENTRY_LOG_FILE}{Style.RESET_ALL}")
    strategy.entry_logger.print_recent(days=20)

    """
    Add this code to your run.py at the END of backtest_main() function
    Right before the final "Backtest completed successfully!" message
    """

    # Add this RIGHT BEFORE the final success message in backtest_main():

    # ═══════════════════════════════════════════════════════════
    # STRATEGY USAGE SUMMARY (NEW)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print(f"{Fore.CYAN}STRATEGY DEPLOYMENT SUMMARY{Style.RESET_ALL}")
    print(f"{'=' * 80}")

    # Print strategy usage from the strategy object
    strategy.print_strategy_usage_summary()

    # Calculate strategy effectiveness
    total_strategies_used = sum(strategy.strategy_usage.values())
    if total_strategies_used > 0:
        strategy_data = []
        for strat_name, count in strategy.strategy_usage.items():
            if count > 0 and strat_name != 'skipped':
                pct = (count / total_strategies_used) * 100
                strategy_data.append([
                    strat_name.replace('_', ' ').title(),
                    count,
                    f"{pct:.1f}%"
                ])

        if strategy_data:
            print(tabulate(strategy_data, headers=["Strategy", "Times Used", "% of Total"], tablefmt="grid"))

        # Calculate adaptive rate
        active_strategies = sum(v for k, v in strategy.strategy_usage.items() if k != 'skipped')
        skipped = strategy.strategy_usage.get('skipped', 0)
        total_days = total_strategies_used

        print(f"\n{Fore.CYAN}Adaptive System Performance:{Style.RESET_ALL}")
        print(f"  Trading Days: {total_days}")
        print(f"  Strategies Deployed: {active_strategies} ({active_strategies / total_days * 100:.1f}%)")
        print(f"  Days Skipped: {skipped} ({skipped / total_days * 100:.1f}%)")
        print(
            f"  Unique Strategies Used: {len([k for k, v in strategy.strategy_usage.items() if v > 0 and k != 'skipped'])}")

    print(f"{'=' * 80}")

    # Existing code continues...
    print(f"\n{Fore.GREEN}Backtest completed successfully!{Style.RESET_ALL}\n")
    db.close()

    print(f"\n{Fore.GREEN}Backtest completed successfully!{Style.RESET_ALL}\n")
    db.close()


def main():
    # Setup logging (uses the paths defined in Config)
    setup_logging()

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
        # (Backtest mode logic remains the same)
        print(f"\n{Fore.CYAN}BACKTEST MODE{Style.RESET_ALL}")
        start_date = input("Enter start date (YYYY-MM-DD): ").strip()
        end_date = input("Enter end date (YYYY-MM-DD): ").strip()
        try: pd.to_datetime(start_date); pd.to_datetime(end_date)
        except ValueError: print(f"{Fore.RED}Invalid date format. Use YYYY-MM-DD{Style.RESET_ALL}"); return
        refresh_input = input("Force refresh cached data? (yes/no, default: no): ").strip().lower()
        force_refresh = refresh_input == "yes"
        backtest_main(broker, start_date, end_date, force_refresh)
        return

    # --- Live/Paper Trading Mode ---
    # (Logic remains the same, ensure logging works correctly)
    if mode == "2":
        confirm = input(f"{Fore.YELLOW}LIVE TRADING selected. Confirm (yes/no)? {Style.RESET_ALL}").lower()
        if confirm != "yes": print(f"{Fore.YELLOW}Live trading cancelled.{Style.RESET_ALL}"); return
        Config.PAPER_TRADING = False
    if Utils.is_holiday(): print(f"{Fore.YELLOW}Today is a holiday. Exiting.{Style.RESET_ALL}"); return
    if not broker.authenticate(): print(f"{Fore.RED}Broker auth failed. Exiting.{Style.RESET_ALL}"); return

    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    notifier.send_alert(f"<b>System Started</b>\nMode: {'Paper' if Config.PAPER_TRADING else 'Live'}\nCapital: Rs.{Config.CAPITAL:,}", "INFO")
    print(f"\n{Fore.GREEN}System started! Mode: {'PAPER' if Config.PAPER_TRADING else 'LIVE'}. Press Ctrl+C to stop.{Style.RESET_ALL}\n")

    try:
        while True:
            # (Live/Paper trading loop remains largely the same)
            # Ensure market hours check works if needed for live
            # if not Config.PAPER_TRADING and not Utils.is_market_hours():
            #     print(f"{Fore.YELLOW}Outside market hours. Waiting...{Style.RESET_ALL}", end='\r')
            #     time.sleep(60)
            #     continue

            current_sim_time = datetime.now() # Use real time for live/paper
            strategy.run_cycle(current_sim_time)
            dashboard.render(strategy.market_data, trade_manager)
            time.sleep(Config.UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Shutting down...{Style.RESET_ALL}")
        if trade_manager.active_trades:
            print(f"Closing {len(trade_manager.active_trades)} open positions...")
            exit_ts = datetime.now()
            trade_manager.close_all_positions("MANUAL_SHUTDOWN", exit_ts)
        metrics = trade_manager.get_performance_metrics()
        print(f"\n{Fore.CYAN}Session Summary:{Style.RESET_ALL}")
        # (Print summary metrics)
        print(f"Total Trades: {metrics.total_trades}, Win Rate: {metrics.win_rate:.1f}%, P&L: Rs.{metrics.total_pnl:,.2f}")
        notifier.send_alert("System shutdown", "INFO")
        db.close()
    except Exception as e:
        print(f"{Fore.RED}Fatal error: {e}{Style.RESET_ALL}")
        logging.error(f"Fatal error: {e}", exc_info=True)
        notifier.send_alert(f"Fatal error: {e}", "ERROR")
        db.close()

if __name__ == "__main__":
    main()