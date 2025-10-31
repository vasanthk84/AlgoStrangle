"""
run.py - ENHANCED with Manual Trade Management + Monitor-Only Mode
🆕 NEW: Grace period after import to prevent immediate closure
🆕 NEW: Monitor-Only mode (no auto-exits, just tracking)
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
from typing import Set

from historical_data_manager import HistoricalDataManager
from backtest_analyzer import BacktestAnalyzer
from trade_import_manager import ManualTradeImporter, print_import_instructions

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
    """Reconcile active trades from database on startup"""
    try:
        all_trades = db.get_all_trades()

        if all_trades.empty:
            logging.info("No trades found in database")
            return 0

        active_trades_df = all_trades[all_trades['exit_time'].isna()]

        if active_trades_df.empty:
            logging.info("No active trades found in database")
            return 0

        logging.info(f"Found {len(active_trades_df)} active trades in database")

        restored_count = 0

        for _, row in active_trades_df.iterrows():
            try:
                trade_id = row['trade_id']
                symbol = row['symbol']
                qty = int(row['qty'])
                direction = Direction.SELL if row['direction'] == 'SELL' else Direction.BUY
                entry_price = float(row['entry_price'])
                entry_time = pd.to_datetime(row['entry_time'])
                option_type = row['option_type']
                strike_price = float(row['strike_price'])

                expiry = entry_time.date() + pd.Timedelta(days=7)
                spot_at_entry = strike_price

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

                trade_manager.active_trades[trade_id] = trade

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
            time.sleep(3)

        return restored_count

    except Exception as e:
        logging.error(f"Failed to reconcile trades from database: {e}", exc_info=True)
        return 0


def simulate_risk_management(trade_manager, strategy, sent_alerts: Set[str]):
    """
    Simulated risk management - shows what would happen without executing

    Args:
        trade_manager: TradeManager instance
        strategy: Strategy instance
        sent_alerts: Set to track which alerts were already shown
    """
    if not trade_manager.active_trades:
        return

    # Check grace period
    grace_active = False
    if trade_manager.last_entry_timestamp:
        time_since_entry = (
                                   strategy.market_data.timestamp - trade_manager.last_entry_timestamp
                           ).total_seconds() / 60

        if time_since_entry < trade_manager.entry_grace_period_minutes:
            grace_active = True

    print(f"\n{Fore.CYAN}{'─' * 100}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}📊 SIMULATED RISK MANAGEMENT (Monitor Mode){Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'─' * 100}{Style.RESET_ALL}")

    if grace_active:
        print(
            f"{Fore.YELLOW}⏰ Grace Period Active: {time_since_entry:.1f}/{trade_manager.entry_grace_period_minutes} min{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   (In real mode, no adjustments would execute yet){Style.RESET_ALL}\n")

    actions_detected = []

    # Check each trade
    for trade_id, trade in trade_manager.active_trades.items():
        if trade.current_price <= 0:
            continue

        # Calculate metrics
        loss_multiple = trade.get_loss_multiple()
        pnl = trade.get_pnl()
        pnl_pct = trade.get_pnl_pct()

        current_delta = abs(trade.greeks.delta) if trade.greeks else 0.0

        # Check HARD STOP (30%)
        if loss_multiple >= Config.HARD_STOP_MULTIPLIER:
            alert_key = f"{trade.trade_id}_hardstop"

            if alert_key not in sent_alerts:
                action = {
                    'type': 'HARD_STOP',
                    'trade': trade,
                    'reason': f"Loss {loss_multiple:.1%} >= {Config.HARD_STOP_MULTIPLIER:.1%}",
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'delta': current_delta
                }
                actions_detected.append(action)
                sent_alerts.add(alert_key)

        # Check ROLL TRIGGER (Delta 30)
        elif current_delta >= Config.ROLL_TRIGGER_DELTA:
            alert_key = f"{trade.trade_id}_roll"

            if alert_key not in sent_alerts:
                # Calculate roll economics
                roll_distance = Config.ROLL_DISTANCE
                if trade.option_type == "CE":
                    new_strike = trade.strike_price + roll_distance
                else:
                    new_strike = trade.strike_price - roll_distance

                # Try to get new symbol price
                new_price = 0.0
                new_symbol = ""
                roll_viable = False

                try:
                    if strategy.broker.backtest_data is None:
                        instrument = strategy.broker.find_live_option_symbol(
                            new_strike, trade.option_type, trade.expiry
                        )
                        if instrument:
                            new_symbol = f"NFO:{instrument['tradingsymbol']}"
                            new_price = strategy.broker.get_quote(new_symbol)
                            roll_viable = new_price >= Config.ROLL_MIN_CREDIT
                    else:
                        # Backtest mod
                        new_symbol = Utils.prepare_option_symbol(new_strike, trade.option_type, trade.expiry)
                        new_price = strategy.broker.greeks_calc.get_option_price(
                            strategy.market_data.nifty_spot, new_strike,
                            strategy.broker.greeks_calc.get_dte(trade.expiry, strategy.market_data.timestamp.date()),
                            strategy.market_data.india_vix, trade.option_type
                        )
                        roll_viable = new_price >= Config.ROLL_MIN_CREDIT
                except Exception as e:
                    pass

                action = {
                    'type': 'ROLL',
                    'trade': trade,
                    'reason': f"Delta {current_delta:.1f} >= {Config.ROLL_TRIGGER_DELTA}",
                    'old_strike': trade.strike_price,
                    'new_strike': new_strike,
                    'new_symbol': new_symbol,
                    'new_price': new_price,
                    'roll_viable': roll_viable,
                    'delta': current_delta
                }
                actions_detected.append(action)
                sent_alerts.add(alert_key)

        # Check WARNING levels
        elif current_delta >= Config.ROLL_WARNING_DELTA:
            alert_key = f"{trade.trade_id}_warning"

            if alert_key not in sent_alerts:
                action = {
                    'type': 'WARNING',
                    'trade': trade,
                    'reason': f"Delta {current_delta:.1f} approaching trigger ({Config.ROLL_TRIGGER_DELTA})",
                    'delta': current_delta
                }
                actions_detected.append(action)
                sent_alerts.add(alert_key)

    # Display detected actions
    if actions_detected:
        for action in actions_detected:
            trade = action['trade']

            if action['type'] == 'HARD_STOP':
                print(f"\n{Fore.RED}🛑 HARD STOP TRIGGERED{Style.RESET_ALL}")
                print(f"{Fore.RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")
                print(f"  Symbol: {trade.symbol}")
                print(f"  Strike: {trade.option_type} {trade.strike_price}")
                print(f"  Entry: ₹{trade.entry_price:.2f} → Current: ₹{trade.current_price:.2f}")
                print(f"  Loss: {Fore.RED}₹{action['pnl']:,.2f} ({action['pnl_pct']:.1f}%){Style.RESET_ALL}")
                print(f"  Delta: {action['delta']:.1f}")
                print(f"  Reason: {action['reason']}")
                print(f"\n  {Fore.RED}⚠️  IN REAL MODE: Would close this position immediately{Style.RESET_ALL}")
                print(f"  {Fore.YELLOW}💡 Action: Consider manually closing in Zerodha{Style.RESET_ALL}")

            elif action['type'] == 'ROLL':
                print(f"\n{Fore.YELLOW}🔄 ROLL OPPORTUNITY DETECTED{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")
                print(f"  Current: {trade.symbol}")
                print(f"  Strike: {trade.option_type} {action['old_strike']}")
                print(f"  Current Price: ₹{trade.current_price:.2f}")
                print(f"  Delta: {action['delta']:.1f} (trigger at {Config.ROLL_TRIGGER_DELTA})")
                print(f"  Reason: {action['reason']}")
                print()
                print(f"  Proposed Roll:")
                print(f"    Close: {trade.option_type} {action['old_strike']}")
                print(f"    Open:  {trade.option_type} {action['new_strike']}")

                if action['roll_viable']:
                    print(f"    New Symbol: {action['new_symbol']}")
                    print(f"    New Premium: {Fore.GREEN}₹{action['new_price']:.2f}{Style.RESET_ALL}")
                    print(
                        f"\n  {Fore.GREEN}✓ Roll Economics: VIABLE (Premium ≥ ₹{Config.ROLL_MIN_CREDIT}){Style.RESET_ALL}")
                    print(f"  {Fore.YELLOW}⚠️  IN REAL MODE: Would execute this roll automatically{Style.RESET_ALL}")
                    print(f"  {Fore.YELLOW}💡 Action: Consider rolling manually in Zerodha{Style.RESET_ALL}")
                else:
                    if action['new_price'] > 0:
                        print(f"    New Premium: {Fore.RED}₹{action['new_price']:.2f}{Style.RESET_ALL}")
                        print(
                            f"\n  {Fore.RED}✗ Roll Economics: NOT VIABLE (Premium < ₹{Config.ROLL_MIN_CREDIT}){Style.RESET_ALL}")
                        print(f"  {Fore.YELLOW}⚠️  IN REAL MODE: Would skip roll (premium too low){Style.RESET_ALL}")
                    else:
                        print(f"\n  {Fore.RED}✗ Roll Failed: New symbol not found or invalid price{Style.RESET_ALL}")

            elif action['type'] == 'WARNING':
                print(f"\n{Fore.YELLOW}⚠️  WARNING ZONE{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")
                print(f"  Symbol: {trade.symbol}")
                print(f"  Strike: {trade.option_type} {trade.strike_price}")
                print(f"  Delta: {action['delta']:.1f} (watch for {Config.ROLL_TRIGGER_DELTA})")
                print(f"  Reason: {action['reason']}")
                print(f"  {Fore.YELLOW}💡 Getting close to roll trigger - monitor closely{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}✓ All positions within safe limits{Style.RESET_ALL}")
        print(f"  No stops or rolls would be triggered")

    print(f"{Fore.CYAN}{'─' * 100}{Style.RESET_ALL}\n")


def backtest_main(broker: BrokerInterface, start_date: str, end_date: str, force_refresh: bool = False):
    """Backtest mode"""
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

    db_path = Config.DB_FILE
    if os.path.exists(db_path):
        logging.info(f"Clearing previous backtest data from {db_path}...")
        try:
            os.remove(db_path)
            logging.info(f"Successfully removed old database.")
        except Exception as e:
            logging.warning(f"Could not remove database file. Old data might be present. Error: {e}")

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
    if Config.TICK_SKIP_INTERVAL > 1:
        print(f"{Fore.YELLOW}Tick Skipping Enabled: Processing 1 tick every {Config.TICK_SKIP_INTERVAL} minutes.{Style.RESET_ALL}")

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
        broker.greeks_calc.clear_cache()

        total_ticks = len(daily_data)
        last_progress = 0

        for idx, index in enumerate(daily_data.index):
            if idx % Config.TICK_SKIP_INTERVAL != 0:
                continue

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

    print(f"\n{Fore.GREEN}Backtest simulation completed.{Style.RESET_ALL}")

    print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  FINAL BACKTEST SUMMARY - {start_date} to {end_date}  {Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")

    db.close()

    try:
        analyzer = BacktestAnalyzer(Config.DB_FILE)
        if analyzer.trades_df is not None and not analyzer.trades_df.empty:
            analyzer.overall_statistics()
            analyzer.daily_performance_chart()
            analyzer.risk_metrics()
            analyzer.print_all_trades_summary()

            trades_csv_path = os.path.join(Config.OUTPUT_DIR_TRADES, f"backtest_trades_{start_date}_to_{end_date}.csv")
            analyzer.trades_df.to_csv(trades_csv_path, index=False)
            print(f"\n{Fore.GREEN}✓ Final trades list exported to:{Style.RESET_ALL} {trades_csv_path}")

            daily_perf_csv_path = os.path.join(Config.OUTPUT_DIR_PERF, f"backtest_daily_performance_{start_date}_to_{end_date}.csv")
            analyzer.daily_perf_df.to_csv(daily_perf_csv_path, index=False)
            print(f"{Fore.GREEN}✓ Daily performance exported to:{Style.RESET_ALL} {daily_perf_csv_path}")

        else:
            print(f"{Fore.YELLOW}No trades were executed or found in the database for this period.{Style.RESET_ALL}")

    except Exception as e:
        print(f"{Fore.RED}Error generating final summary: {e}{Style.RESET_ALL}")
        logging.error(f"Failed to generate final summary: {e}", exc_info=True)


def manage_manual_trades_mode(broker: BrokerInterface):
    """
    🆕 Manage Mode - Import and monitor manually executed trades
    """
    print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  MANAGE MANUAL TRADES MODE{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")

    print_import_instructions()

    # Create template if doesn't exist
    importer = ManualTradeImporter()
    importer.create_template_if_missing()

    # Ask if user wants to proceed
    proceed = input(f"\n{Fore.YELLOW}Have you updated manual_trades.csv with your trades? (yes/no): {Style.RESET_ALL}").strip().lower()

    if proceed != "yes":
        print(f"{Fore.YELLOW}Please update manual_trades.csv first, then re-run the system.{Style.RESET_ALL}")
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # 🆕 ASK USER: Auto-adjustments or Monitor-Only mode?
    # ═══════════════════════════════════════════════════════════════════════════

    print(f"\n{Fore.CYAN}Select Management Mode:{Style.RESET_ALL}")
    print(f"1. {Fore.GREEN}Full Auto-Management{Style.RESET_ALL} (Stops, Rolls, Exits - with 5min grace period)")
    print(f"2. {Fore.YELLOW}Monitor Only{Style.RESET_ALL} (Dashboard + Greeks + Alerts, No Auto-Exits)")

    mgmt_mode = input(f"Enter choice (1/2, default: 1): ").strip() or "1"

    monitor_only = (mgmt_mode == "2")

    if monitor_only:
        print(f"\n{Fore.YELLOW}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}⚠️  MONITOR ONLY MODE{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   System will track P&L and Greeks but will NOT auto-close positions{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   You must manually square off trades in Zerodha{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   Alerts will be sent when stops/rolls are triggered{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   ℹ️  Repetitive warnings suppressed to reduce noise{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'=' * 80}{Style.RESET_ALL}\n")

        # Reduce logging verbosity in monitor mode
        logging.getLogger().setLevel(logging.ERROR)
    else:
        print(f"\n{Fore.GREEN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}✅ FULL AUTO-MANAGEMENT MODE{Style.RESET_ALL}")
        print(f"{Fore.GREEN}   5-minute grace period enabled (no stops during first 5 minutes){Style.RESET_ALL}")
        print(f"{Fore.GREEN}   System will apply stops, rolls, and exits automatically after grace period{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'=' * 80}{Style.RESET_ALL}\n")

    # Continue with authentication
    Config.PAPER_TRADING = False  # Manage mode uses live prices

    if not broker.authenticate():
        print(f"{Fore.RED}Broker auth failed. Exiting.{Style.RESET_ALL}")
        return

    db = DatabaseManager(Config.DB_FILE)
    notifier = NotificationManager()
    trade_manager = TradeManager(broker, db, notifier)
    strategy = ShortStrangleStrategy(broker, trade_manager, notifier)
    dashboard = ConsoleDashboard()

    # Import trades from CSV
    print(f"\n{Fore.CYAN}Importing trades from manual_trades.csv...{Style.RESET_ALL}")

    imported_trades = importer.import_trades(broker.get_lot_size("NIFTY"))

    if not imported_trades:
        print(f"{Fore.RED}No trades imported. Please check manual_trades.csv{Style.RESET_ALL}")
        return

    # Add imported trades to trade manager
    for trade in imported_trades:
        trade_manager.active_trades[trade.trade_id] = trade

        if trade.option_type == "CE":
            trade_manager.ce_trades += 1
        else:
            trade_manager.pe_trades += 1

    # Create trade pairs automatically (match CE and PE)
    ce_trades = [t for t in imported_trades if t.option_type == "CE"]
    pe_trades = [t for t in imported_trades if t.option_type == "PE"]

    for ce_trade in ce_trades:
        for pe_trade in pe_trades:
            # Match by same entry time (within 5 minutes)
            time_diff = abs((ce_trade.timestamp - pe_trade.timestamp).total_seconds())
            if time_diff < 300:  # 5 minutes
                combined_premium = ce_trade.entry_price + pe_trade.entry_price
                trade_manager.add_trade_pair(
                    ce_trade_id=ce_trade.trade_id,
                    pe_trade_id=pe_trade.trade_id,
                    entry_combined=combined_premium,
                    entry_time=ce_trade.timestamp,
                    lots=ce_trade.qty
                )
                logging.info(
                    f"✅ Created pair: {ce_trade.strike_price} CE + {pe_trade.strike_price} PE"
                )
                break

    # Update prices for imported trades
    market_data = broker.get_market_data()
    trade_manager.update_active_trades(market_data)

    # Display imported trades
    print(f"\n{Fore.GREEN}{'=' * 80}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}✅ IMPORTED {len(imported_trades)} MANUAL TRADES{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'=' * 80}{Style.RESET_ALL}\n")

    for trade in imported_trades:
        pnl = trade.get_pnl()
        pnl_pct = trade.get_pnl_pct()
        color = Fore.GREEN if pnl >= 0 else Fore.RED

        print(
            f"  {trade.option_type} {trade.strike_price:.0f} | "
            f"Entry: ₹{trade.entry_price:.2f} → Current: ₹{trade.current_price:.2f} | "
            f"P&L: {color}₹{pnl:+,.2f} ({pnl_pct:+.1f}%){Style.RESET_ALL}"
        )

    print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")

    if monitor_only:
        print(f"{Fore.CYAN}🔍 MONITOR MODE - System will:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Track positions in real-time{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Calculate Greeks (Delta, Theta, Gamma){Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Send Telegram alerts when thresholds hit{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ❌ Will NOT auto-close or adjust positions{Style.RESET_ALL}")
    else:
        print(f"{Fore.CYAN}🤖 AUTO-MANAGEMENT MODE - System will:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ⏰ Grace Period: 5 minutes (no stops during this time){Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Monitor positions in real-time{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Calculate Greeks (Delta, Theta, Gamma){Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Apply HARD STOP at 30% loss (after grace period){Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Roll positions when Delta hits 30{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Exit at 50% profit target{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Square off at 15:20 IST{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  ✅ Send Telegram alerts{Style.RESET_ALL}")

    print(f"{Fore.CYAN}  ❌ NO NEW TRADES will be initiated{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")

    # Disable new entry
    strategy.entry_allowed_today = False

    # ═══════════════════════════════════════════════════════════════════════════
    # 🆕 SET GRACE PERIOD for imported trades (prevent immediate closure)
    # ═══════════════════════════════════════════════════════════════════════════

    if not monitor_only:
        # Set last entry timestamp to NOW (triggers grace period)
        trade_manager.last_entry_timestamp = datetime.now()
        trade_manager._grace_logged = False

        print(f"{Fore.YELLOW}⏰ Grace Period Active: {trade_manager.entry_grace_period_minutes} minutes{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   No stops/adjustments will be applied during grace period{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   This gives you time to review imported positions{Style.RESET_ALL}\n")

    # Send notification
    notifier.send_alert(
        f"<b>Manage Mode Started</b>\n"
        f"Mode: {'📊 Monitor Only' if monitor_only else '🤖 Auto-Management'}\n"
        f"Imported: {len(imported_trades)} trades\n"
        f"CE Trades: {len(ce_trades)}\n"
        f"PE Trades: {len(pe_trades)}\n"
        f"Pairs: {len(trade_manager.active_pairs)}\n\n"
        f"{'Dashboard tracking active. No auto-exits.' if monitor_only else 'Auto-management active with 5min grace period.'}\n\n"
        f"{'You will NOT receive threshold alerts.' if monitor_only else 'You will receive alerts for all actions.'}",
        "INFO"
    )

    print(f"{Fore.YELLOW}Press Ctrl+C to stop gracefully{Style.RESET_ALL}\n")
    time.sleep(3)

    # Continue to monitoring loop
    try:
        # Track which alerts we've already sent (prevent spam)
        sent_alerts = set()

        while True:
            current_sim_time = datetime.now()

            if monitor_only:
                # Monitor only mode - skip risk management
                strategy.market_data = broker.get_market_data()
                strategy.market_data.iv_rank = strategy.calculate_iv_rank()

                if trade_manager.active_trades:
                    trade_manager.update_active_trades(strategy.market_data)

                    simulate_risk_management(trade_manager, strategy, sent_alerts)

                    # Check for alerts but don't execute or send notifications
                    # Just log once per session
                    for trade in trade_manager.active_trades.values():
                        alert_key = f"{trade.trade_id}_hardstop"

                        loss_multiple = trade.get_loss_multiple()
                        if loss_multiple >= Config.HARD_STOP_MULTIPLIER and alert_key not in sent_alerts:
                            # Log once, don't spam
                            logging.info(
                                f"ℹ️ INFO: {trade.symbol} above HARD STOP threshold "
                                f"({loss_multiple:.1%} loss) - Monitor mode active"
                            )
                            sent_alerts.add(alert_key)

                        # Check delta but don't log/alert for rolls
                        if trade.greeks:
                            delta_key = f"{trade.trade_id}_delta30"
                            if abs(trade.greeks.delta) >= Config.ROLL_TRIGGER_DELTA and delta_key not in sent_alerts:
                                logging.info(
                                    f"ℹ️ INFO: {trade.symbol} Delta={trade.greeks.delta:.1f} "
                                    f"- Monitor mode active"
                                )
                                sent_alerts.add(delta_key)
            else:
                # Full auto-management mode
                strategy.run_cycle(current_sim_time)

            dashboard.render(strategy.market_data, trade_manager)
            time.sleep(Config.UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Shutting down...{Style.RESET_ALL}")

        if not monitor_only and trade_manager.active_trades:
            print(f"Closing {len(trade_manager.active_trades)} open positions...")
            exit_ts = datetime.now()
            trade_manager.close_all_positions("MANUAL_SHUTDOWN", exit_ts)

        metrics = trade_manager.get_performance_metrics()
        print(f"\n{Fore.CYAN}Session Summary:{Style.RESET_ALL}")
        print(f"Total Trades: {metrics.total_trades}, Win Rate: {metrics.win_rate:.1f}%, P&L: ₹{metrics.total_pnl:,.2f}")

        # Send summary notification
        if monitor_only and trade_manager.active_trades:
            # Monitor mode - send final P&L summary
            total_pnl = sum(t.get_pnl() for t in trade_manager.active_trades.values())

            trade_summary = []
            for trade in trade_manager.active_trades.values():
                pnl = trade.get_pnl()
                pnl_pct = trade.get_pnl_pct()
                trade_summary.append(
                    f"{trade.option_type} {trade.strike_price:.0f}: "
                    f"₹{pnl:+,.2f} ({pnl_pct:+.1f}%)"
                )

            notifier.send_alert(
                f"<b>Monitor Mode - Session Ended</b>\n\n"
                f"Positions Still Open: {len(trade_manager.active_trades)}\n\n"
                f"{'<br>'.join(trade_summary)}\n\n"
                f"<b>Total P&L: ₹{total_pnl:+,.2f}</b>\n\n"
                f"⚠️ Remember to manually square off positions in Zerodha!",
                "INFO"
            )
        else:
            notifier.send_alert("System shutdown", "INFO")

        db.close()

    except Exception as e:
        print(f"{Fore.RED}Fatal error: {e}{Style.RESET_ALL}")
        logging.error(f"Fatal error: {e}", exc_info=True)
        notifier.send_alert(f"Fatal error: {e}", "ERROR")
        db.close()


def main():
    setup_logging()

    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  ENHANCED SHORT STRANGLE NIFTY OPTIONS TRADING SYSTEM  {Style.RESET_ALL}
{Fore.CYAN}  Version 4.3 - With Monitor-Only Mode  {Style.RESET_ALL}
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
    print("4. Manage Manual Trades (Monitor & Adjust)")
    mode = input("Enter choice (1/2/3/4): ").strip() or "1"

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

    if mode == "4":
        manage_manual_trades_mode(broker)
        return

    # Live/Paper Trading Mode
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

    print(f"\n{Fore.CYAN}Checking for existing active trades...{Style.RESET_ALL}")
    restored_count = reconcile_active_trades_from_db(db, trade_manager, broker)

    if restored_count > 0:
        market_data = broker.get_market_data()
        trade_manager.update_active_trades(market_data)
        strategy.entry_allowed_today = False
        logging.info("Entry disabled - monitoring existing trades")

    notifier.send_alert(
        f"<b>System Started</b>\nMode: {'Paper' if Config.PAPER_TRADING else 'Live'}\n"
        f"Capital: ₹{Config.CAPITAL:,}\n"
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
        print(f"Total Trades: {metrics.total_trades}, Win Rate: {metrics.win_rate:.1f}%, P&L: ₹{metrics.total_pnl:,.2f}")

        notifier.send_alert("System shutdown", "INFO")
        db.close()

    except Exception as e:
        print(f"{Fore.RED}Fatal error: {e}{Style.RESET_ALL}")
        logging.error(f"Fatal error: {e}", exc_info=True)
        notifier.send_alert(f"Fatal error: {e}", "ERROR")
        db.close()


if __name__ == "__main__":
    main()