"""
run.py - ENHANCED with Trade Reconciliation
🆕 Now checks database for active trades on startup
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

from historical_data_manager import HistoricalDataManager

from strangle import (
    Config,
    Utils,
    DatabaseManager,
    NotificationManager,
    BrokerInterface,
    TradeManager,
    ShortStrangleStrategy,
    ConsoleDashboard,
    Trade,
    Direction
)

# Create directories
os.makedirs(Config.LOG_DIR_MAIN, exist_ok=True)
os.makedirs(Config.LOG_DIR_CSV, exist_ok=True)
os.makedirs(Config.LOG_DIR_AUDIT, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_DATA, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_TRADES, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_PERF, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR_SUMMARY, exist_ok=True)


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


def reconcile_active_trades_from_db(db: DatabaseManager, trade_manager: TradeManager,
                                    broker: BrokerInterface) -> int:
    """
    🆕 NEW: Reconcile active trades from database on startup

    Returns: Number of trades restored
    """
    try:
        # Get all trades from database
        all_trades = db.get_all_trades()

        if all_trades.empty:
            logging.info("No trades found in database")
            return 0

        # Filter for trades without exit_time (still active)
        active_trades_df = all_trades[all_trades['exit_time'].isna()]

        if active_trades_df.empty:
            logging.info("No active trades found in database")
            return 0

        logging.info(f"Found {len(active_trades_df)} active trades in database")

        restored_count = 0

        for _, row in active_trades_df.iterrows():
            try:
                # Parse trade data
                trade_id = row['trade_id']
                symbol = row['symbol']
                qty = int(row['qty'])
                direction = Direction.SELL if row['direction'] == 'SELL' else Direction.BUY
                entry_price = float(row['entry_price'])
                entry_time = pd.to_datetime(row['entry_time'])
                option_type = row['option_type']
                strike_price = float(row['strike_price'])

                # Get expiry and spot at entry
                # Note: You may need to adjust this based on your database schema
                expiry = entry_time.date() + pd.Timedelta(days=7)  # Estimate
                spot_at_entry = strike_price  # Estimate

                # Create Trade object
                trade = Trade(
                    trade_id=trade_id,
                    symbol=symbol,
                    qty=qty,
                    direction=direction,
                    price=entry_price,
                    timestamp=entry_time,
                    option_type=option_type,
                    lot_size=broker.get_lot_size(symbol),
                    strike_price=strike_price,
                    expiry=expiry,
                    spot_at_entry=spot_at_entry
                )

                # Add to trade manager WITHOUT incrementing trade count
                trade_manager.active_trades[trade_id] = trade

                # Get current price
                current_price = broker.get_quote(symbol)
                if current_price > 0:
                    trade.update_price(current_price)

                restored_count += 1

                logging.info(
                    f"✓ Restored trade: {symbol} | Entry: ₹{entry_price:.2f} | "
                    f"Current: ₹{current_price:.2f}"
                )

            except Exception as e:
                logging.error(f"Failed to restore trade {row.get('trade_id', 'unknown')}: {e}")
                continue

        if restored_count > 0:
            print(f"\n{Fore.GREEN}{'=' * 80}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}✓ RESTORED {restored_count} ACTIVE TRADES FROM DATABASE{Style.RESET_ALL}")
            print(f"{Fore.GREEN}{'=' * 80}{Style.RESET_ALL}\n")

            # Show restored trades
            for trade_id, trade in trade_manager.active_trades.items():
                pnl = trade.get_pnl()
                pnl_pct = trade.get_pnl_pct()
                color = Fore.GREEN if pnl >= 0 else Fore.RED

                print(
                    f"  {trade.option_type} {trade.strike_price:.0f} | "
                    f"Entry: ₹{trade.entry_price:.2f} → Current: ₹{trade.current_price:.2f} | "
                    f"P&L: {color}₹{pnl:+,.2f} ({pnl_pct:+.1f}%){Style.RESET_ALL}"
                )

            print(f"\n{Fore.YELLOW}Continuing to monitor these positions...{Style.RESET_ALL}\n")
            time.sleep(3)  # Give user time to see

        return restored_count

    except Exception as e:
        logging.error(f"Failed to reconcile trades from database: {e}", exc_info=True)
        return 0


def backtest_main(broker: BrokerInterface, start_date: str, end_date: str, force_refresh: bool = False):
    """Backtest mode - unchanged"""
    setup_logging()

    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  ENHANCED SHORT STRANGLE NIFTY OPTIONS BACKTEST  {Style.RESET_ALL}
{Fore.CYAN}  Period: {start_date} to {end_date}  {Style.RESET_ALL}
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
""")

    if not broker.authenticate():
        print(f"{Fore.RED}Authentication failed. Exiting backtest.{Style.RESET_ALL}")
        return

    data_manager = HistoricalDataManager(broker.kite, Config.BACKTEST_CACHE_DIR)

    def calculate_strikes(spot: float, vix: float, current_date: date) -> Tuple[float, float, date]:
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

    try:
        backtest_data = data_manager.prepare_backtest_data(
            start_date, end_date, calculate_strikes, force_refresh
        )

        output_filename = f"backtest_data_{start_date}_to_{end_date}.csv"
        output_file_path = os.path.join(Config.OUTPUT_DIR_DATA, output_filename)
        backtest_data.to_csv(output_file_path, index=False)
        print(f"{Fore.GREEN}Backtest data saved to: {output_file_path}{Style.RESET_ALL}")

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
                print(f"  Progress: {progress}% | Time: {current_time.strftime('%H:%M')}", end='\r')
                last_progress = progress

        print()
        metrics = trade_manager.get_performance_metrics()
        db.save_daily_performance(current_date.strftime('%Y-%m-%d'), metrics)

    # Final summary (existing code)
    print(f"\n{Fore.GREEN}Backtest completed successfully!{Style.RESET_ALL}\n")
    db.close()


def main():
    setup_logging()

    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  ENHANCED SHORT STRANGLE NIFTY OPTIONS TRADING SYSTEM  {Style.RESET_ALL}
{Fore.CYAN}  Version 4.1 - With Trade Reconciliation  {Style.RESET_ALL}
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
""")

    if Config.DRY_RUN_MODE:
        print(f"{Fore.YELLOW}╔{'═' * 78}╗{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}║         DRY RUN MODE ENABLED                                                 ║{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}╠{'═' * 78}╣{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}║  ✓ Orders will be SIMULATED (not sent to broker)                            ║{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}║  ✓ System will track positions as if real                                    ║{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}║  ✓ P&L calculated using live market prices                                   ║{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}╚{'═' * 78}╝{Style.RESET_ALL}\n")

    print("\nSelect Trading Mode:")
    print("1. Paper Trading (Default)")
    print("2. Live Trading")
    print("3. Backtest Mode")
    mode = input("Enter choice (1/2/3): ").strip() or "1"

    broker = BrokerInterface()

    if mode == "3":
        start_date = input("Enter start date (YYYY-MM-DD): ").strip()
        end_date = input("Enter end date (YYYY-MM-DD): ").strip()
        try:
            pd.to_datetime(start_date)
            pd.to_datetime(end_date)
        except ValueError:
            print(f"{Fore.RED}Invalid date format{Style.RESET_ALL}")
            return
        refresh_input = input("Force refresh cached data? (yes/no, default: no): ").strip().lower()
        force_refresh = refresh_input == "yes"
        backtest_main(broker, start_date, end_date, force_refresh)
        return

    # ═══════════════════════════════════════════════════════════════════
    # LIVE/PAPER TRADING MODE with RECONCILIATION
    # ═══════════════════════════════════════════════════════════════════

    if mode == "2":
        confirm = input(f"{Fore.YELLOW}LIVE TRADING selected. Confirm (yes/no)? {Style.RESET_ALL}").lower()
        if confirm != "yes":
            print(f"{Fore.YELLOW}Live trading cancelled.{Style.RESET_ALL}")
            return
        Config.PAPER_TRADING = False

    if Utils.is_holiday():
        print(f"{Fore.YELLOW}Today is a holiday. Exiting.{Style.RESET_ALL}")
        return

    if not broker.authenticate():
        print(f"{Fore.RED}Broker auth failed. Exiting.{Style.RESET_ALL}")
        return

    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    # ═══════════════════════════════════════════════════════════════════
    # 🆕 NEW: TRADE RECONCILIATION ON STARTUP
    # ═══════════════════════════════════════════════════════════════════

    print(f"\n{Fore.CYAN}Checking for existing active trades...{Style.RESET_ALL}")
    restored_count = reconcile_active_trades_from_db(db, trade_manager, broker)

    if restored_count > 0:
        # Update market data for restored trades
        market_data = broker.get_market_data()
        trade_manager.update_active_trades(market_data)

        # Disable new entry if we have active trades
        strategy.entry_allowed_today = False
        logging.info("Entry disabled - monitoring existing trades")

    # ═══════════════════════════════════════════════════════════════════

    notifier.send_alert(
        f"<b>System Started</b>\nMode: {'Paper' if Config.PAPER_TRADING else 'Live'}\n"
        f"Capital: Rs.{Config.CAPITAL:,}\n"
        f"Active Trades: {len(trade_manager.active_trades)}",
        "INFO"
    )

    print(f"\n{Fore.GREEN}System started! Mode: {'PAPER' if Config.PAPER_TRADING else 'LIVE'}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Active Trades: {len(trade_manager.active_trades)}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Press Ctrl+C to stop gracefully{Style.RESET_ALL}\n")

    try:
        while True:
            current_sim_time = datetime.now()
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