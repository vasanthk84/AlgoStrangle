"""
run.py - Entry point for Short Strangle NIFTY Options Trading System
Enhanced Short Strangle NIFTY Options Trading System with Production-Quality Backtesting
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


def backtest_main(broker: BrokerInterface, start_date: str, end_date: str, force_refresh: bool = False):
    # Configure logging with UTF-8 encoding
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

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

    # Initialize historical data manager
    data_manager = HistoricalDataManager(broker.kite, Config.BACKTEST_CACHE_DIR)

    # Define strike calculator function
    def calculate_strikes(spot: float, vix: float, current_date: date) -> Tuple[float, float, date]:
        """Calculate CE/PE strikes and expiry based on spot and VIX"""
        if vix > Config.VIX_THRESHOLD:
            otm_distance = Config.OTM_DISTANCE_HIGH_VIX
        else:
            otm_distance = Config.OTM_DISTANCE_NORMAL

        ce_strike = round(spot / 50) * 50 + otm_distance
        pe_strike = round(spot / 50) * 50 - otm_distance

        # NEW SEBI RULES: Weekly expiry on TUESDAY (weekday 1), not Thursday
        # Calculate next Tuesday expiry
        current = pd.to_datetime(current_date)
        days_until_tuesday = (1 - current.weekday()) % 7  # Tuesday is weekday 1
        if days_until_tuesday == 0 and current.time() >= pd.Timestamp('15:30').time():
            # If today is Tuesday after market close, get next Tuesday
            days_until_tuesday = 7
        expiry = (current + pd.Timedelta(days=days_until_tuesday)).date()

        return ce_strike, pe_strike, expiry

    print(f"{Fore.YELLOW}Downloading and preparing historical data...{Style.RESET_ALL}")
    print(f"Cache mode: {'REFRESH' if force_refresh else 'USE EXISTING'}")

    try:
        # Prepare backtest data
        backtest_data = data_manager.prepare_backtest_data(
            start_date, end_date, calculate_strikes, force_refresh
        )

        # Save to CSV for inspection
        output_file = "backtest_data_production.csv"
        backtest_data.to_csv(output_file, index=False)
        print(f"{Fore.GREEN}Backtest data saved to: {output_file}{Style.RESET_ALL}")
        print(f"Total data points: {len(backtest_data)}")
        print(f"Date range: {backtest_data['timestamp'].min()} to {backtest_data['timestamp'].max()}")

    except Exception as e:
        print(f"{Fore.RED}Failed to prepare backtest data: {e}{Style.RESET_ALL}")
        logging.error(f"Backtest data preparation failed: {e}", exc_info=True)
        return

    # Initialize trading components
    Config.PAPER_TRADING = True
    broker.backtest_data = backtest_data
    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    print(f"\n{Fore.CYAN}Starting backtest simulation...{Style.RESET_ALL}\n")

    # Run backtest day by day
    trading_days = pd.date_range(start_date, end_date, freq='D')
    total_days = len([d for d in trading_days if not Utils.is_holiday(d.date())])
    current_day = 0

    for current_date in trading_days:
        if Utils.is_holiday(current_date.date()):
            continue

        current_day += 1
        daily_data = backtest_data[backtest_data['timestamp'].dt.date == current_date.date()]
        if daily_data.empty:
            continue

        print(
            f"\n{Fore.YELLOW}[Day {current_day}/{total_days}] Trading Day: {current_date.strftime('%Y-%m-%d')}{Style.RESET_ALL}")

        # Reset daily state
        strategy.reset_daily_state()

        # Simulate intraday trading with progress indicator
        total_ticks = len(daily_data)
        last_progress = 0

        for idx, index in enumerate(daily_data.index):
            broker.current_index = index
            current_time = daily_data.loc[index, 'timestamp']

            strategy.run_cycle(current_time)

            # Show progress every 10%
            progress = int((idx / total_ticks) * 100)
            if progress >= last_progress + 10:
                print(f"  Progress: {progress}% | Time: {current_time.strftime('%H:%M')} | "
                      f"VIX: {strategy.market_data.india_vix:.2f} | "
                      f"Active Trades: {len(trade_manager.active_trades)}", end='\r')
                last_progress = progress

        print()  # New line after progress

        # End of day summary
        metrics = trade_manager.get_performance_metrics()
        db.save_daily_performance(current_date.strftime('%Y-%m-%d'), metrics)

        # Log daily results
        day_summary = (
            f"DAY SUMMARY: Trades={metrics.total_trades}, "
            f"Daily P&L=Rs.{trade_manager.daily_pnl:,.2f}, "
            f"CE=Rs.{metrics.ce_pnl:,.2f}, PE=Rs.{metrics.pe_pnl:,.2f}, "
            f"Entry Checks={strategy.entry_checks_today}"
        )
        logging.info(day_summary)
        print(f"  {day_summary}")

        # Reset daily metrics for next day
        trade_manager.reset_daily_metrics()

    # Final backtest summary
    print(f"\n{'=' * 80}")
    print(f"{Fore.CYAN}BACKTEST SUMMARY - {start_date} to {end_date}{Style.RESET_ALL}")
    print(f"{'=' * 80}")

    final_metrics = trade_manager.get_performance_metrics()
    cumulative_pnl = sum(trade_manager.daily_pnl_history)

    summary_data = [
        ["Total Trades", final_metrics.total_trades],
        ["Win Trades", final_metrics.win_trades],
        ["Win Rate", f"{final_metrics.win_rate:.1f}%"],
        ["Cumulative P&L", f"Rs.{cumulative_pnl:,.2f}"],
        ["Max Drawdown", f"Rs.{final_metrics.max_drawdown:,.2f}"],
        ["Profit Factor", f"{final_metrics.profit_factor:.2f}"],
        ["Sharpe Ratio", f"{final_metrics.sharpe_ratio:.2f}"],
        ["Rolled Positions", final_metrics.rolled_positions],
        ["Trading Days", len(trade_manager.daily_pnl_history)],
        ["Avg Daily P&L",
         f"Rs.{cumulative_pnl / len(trade_manager.daily_pnl_history):,.2f}" if trade_manager.daily_pnl_history else "N/A"]
    ]
    print(tabulate(summary_data, headers=["Metric", "Value"], tablefmt="grid"))

    # Show P&L distribution
    if trade_manager.daily_pnl_history:
        print(f"\n{Fore.CYAN}Daily P&L Distribution:{Style.RESET_ALL}")
        daily_pnl_array = np.array(trade_manager.daily_pnl_history)
        print(f"  Min Daily P&L: Rs.{np.min(daily_pnl_array):,.2f}")
        print(f"  Max Daily P&L: Rs.{np.max(daily_pnl_array):,.2f}")
        print(f"  Median Daily P&L: Rs.{np.median(daily_pnl_array):,.2f}")
        print(f"  Std Dev: Rs.{np.std(daily_pnl_array):,.2f}")

        winning_days = len([p for p in daily_pnl_array if p > 0])
        total_days = len(daily_pnl_array)
        print(f"  Winning Days: {winning_days}/{total_days} ({winning_days / total_days * 100:.1f}%)")

    # Export detailed results
    print(f"\n{Fore.GREEN}Exported Files:{Style.RESET_ALL}")
    print(f"  Database: {Config.DB_FILE}")
    print(f"  Backtest Data: backtest_data_production.csv")
    print(f"  Log File: {Config.LOG_FILE}")

    # Export trades to CSV
    all_trades = db.get_all_trades()
    if not all_trades.empty:
        trades_file = f"backtest_trades_{start_date}_to_{end_date}.csv"
        all_trades.to_csv(trades_file, index=False)
        print(f"  All Trades: {trades_file}")

    # Export daily performance
    daily_perf = db.get_performance_history(days=1000)
    if not daily_perf.empty:
        perf_file = f"backtest_daily_performance_{start_date}_to_{end_date}.csv"
        daily_perf.to_csv(perf_file, index=False)
        print(f"  Daily Performance: {perf_file}")

    print(f"\n{Fore.GREEN}Backtest completed successfully!{Style.RESET_ALL}\n")

    db.close()


def main():
    # Configure logging with UTF-8 encoding
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

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
        print(f"\n{Fore.CYAN}BACKTEST MODE{Style.RESET_ALL}")
        start_date = input("Enter start date (YYYY-MM-DD): ").strip()
        end_date = input("Enter end date (YYYY-MM-DD): ").strip()

        # Validate dates
        try:
            pd.to_datetime(start_date)
            pd.to_datetime(end_date)
        except ValueError:
            print(f"{Fore.RED}Invalid date format. Please use YYYY-MM-DD{Style.RESET_ALL}")
            return

        # Ask about cache refresh
        refresh_input = input("Force refresh cached data? (yes/no, default: no): ").strip().lower()
        force_refresh = refresh_input == "yes"

        backtest_main(broker, start_date, end_date, force_refresh)
        return

    if mode == "2":
        confirm = input(
            f"{Fore.YELLOW}You selected LIVE TRADING. This will place real orders. Confirm (yes/no)? {Style.RESET_ALL}"
        ).lower()
        if confirm != "yes":
            print(f"{Fore.YELLOW}Live trading cancelled. Exiting.{Style.RESET_ALL}")
            return
        Config.PAPER_TRADING = False

    if Utils.is_holiday():
        print(f"{Fore.YELLOW}Today is a holiday. Exiting.{Style.RESET_ALL}")
        return

    if not broker.authenticate():
        print(f"{Fore.RED}Broker authentication failed. Exiting.{Style.RESET_ALL}")
        return

    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    notifier.send_alert(
        f"<b>System Started</b>\nMode: {'Paper' if Config.PAPER_TRADING else 'Live'}\nCapital: Rs.{Config.CAPITAL:,}",
        "INFO"
    )

    print(f"\n{Fore.GREEN}Trading system started successfully!{Style.RESET_ALL}")
    print(f"Mode: {'PAPER TRADING' if Config.PAPER_TRADING else 'LIVE TRADING'}")
    print(f"Press Ctrl+C to stop\n")

    try:
        while True:
            if not Config.PAPER_TRADING and not Utils.is_market_hours():
                print(f"{Fore.YELLOW}Outside market hours. Waiting...{Style.RESET_ALL}")
                time.sleep(60)
                continue

            strategy.run_cycle()
            dashboard.render(strategy.market_data, trade_manager)
            time.sleep(Config.UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Shutting down gracefully...{Style.RESET_ALL}")

        # Close any open positions
        if trade_manager.active_trades:
            print(f"Closing {len(trade_manager.active_trades)} open positions...")
            for trade_id in list(trade_manager.active_trades.keys()):
                trade = trade_manager.active_trades[trade_id]
                exit_price = broker.get_quote(trade.symbol)
                if exit_price > 0:
                    trade_manager.close_trade(trade_id, exit_price)

        # Save final metrics
        metrics = trade_manager.get_performance_metrics()
        print(f"\n{Fore.CYAN}Session Summary:{Style.RESET_ALL}")
        print(f"Total Trades: {metrics.total_trades}")
        print(f"Win Rate: {metrics.win_rate:.1f}%")
        print(f"Total P&L: Rs.{metrics.total_pnl:,.2f}")

        notifier.send_alert("System shutdown", "INFO")
        db.close()

    except Exception as e:
        print(f"{Fore.RED}Fatal error: {e}{Style.RESET_ALL}")
        logging.error(f"Fatal error: {e}", exc_info=True)
        notifier.send_alert(f"Fatal error: {e}", "ERROR")
        db.close()


if __name__ == "__main__":
    main()
