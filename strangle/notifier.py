"""
Notification management for the Short Strangle Trading System
FIXED: Added full date (YYYY-MM-DD) to all trade signal timestamps.
"""

import logging
from typing import Any
import requests
from datetime import datetime
from colorama import Fore, Style


from .config import Config


class NotificationManager:
    def __init__(self):
        self.bot_token = Config.TELEGRAM_BOT_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID

    def send_alert(self, message: str, level: str):
        """Base alert method (existing)"""
        if self.bot_token == "your_telegram_bot_token":
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': f"{level}: {message}",
                'parse_mode': 'HTML'
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()
        except Exception as e:
            logging.error(f"Failed to send Telegram alert: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # NEW: Enhanced Trade Event Notifications
    # ═══════════════════════════════════════════════════════════════════════

    def notify_entry(self, strategy_name: str, ce_strike: float, pe_strike: float,
                     ce_price: float, pe_price: float, combined_premium: float,
                     qty: int, spot: float, vix: float, mode: str = "PAPER"):
        """Notification when trade is entered"""
        emoji = "📊" if mode == "PAPER" else "🔴"

        message = (
            f"{emoji} <b>TRADE ENTRY - {mode} MODE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Strategy:</b> {strategy_name}\n"
            f"<b>Spot:</b> ₹{spot:.2f} | <b>VIX:</b> {vix:.2f}\n"
            f"\n"
            f"<b>CALL SELL:</b> {ce_strike} CE @ ₹{ce_price:.2f}\n"
            f"<b>PUT SELL:</b> {pe_strike} PE @ ₹{pe_price:.2f}\n"
            f"\n"
            f"<b>Combined Premium:</b> ₹{combined_premium:.2f}\n"
            f"<b>Quantity:</b> {qty} lots ({qty * 75} qty)\n"
            f"<b>Max Profit:</b> ₹{combined_premium * qty * 75:,.2f}\n"
            f"<b>Max Risk:</b> Unlimited (manage with stops)\n"
            f"\n"
            # --- FIX: Added full date ---
            f"⏰ Entry Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"
        )

        self.send_alert(message, "🟢 ENTRY")

        # Also log to console with color
        print(f"\n{'=' * 60}")
        print(f"{Fore.GREEN}📊 TRADE ENTRY EXECUTED{Style.RESET_ALL}")
        print(f"{'=' * 60}")
        print(f"Strategy: {strategy_name}")
        print(f"CE: {ce_strike} @ ₹{ce_price:.2f}  |  PE: {pe_strike} @ ₹{pe_price:.2f}")
        print(f"Combined: ₹{combined_premium:.2f}  |  Lots: {qty}")
        print(f"{'=' * 60}\n")

    def notify_exit(self, reason: str, trade_symbol: str, entry_price: float,
                    exit_price: float, pnl: float, pnl_pct: float,
                    holding_time: str = None):
        """Notification when individual leg is closed"""
        emoji = "✅" if pnl > 0 else "❌"
        color = "green" if pnl > 0 else "red"

        message = (
            f"{emoji} <b>TRADE EXIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Symbol:</b> {trade_symbol}\n"
            f"<b>Reason:</b> {reason}\n"
            f"\n"
            f"<b>Entry:</b> ₹{entry_price:.2f}\n"
            f"<b>Exit:</b> ₹{exit_price:.2f}\n"
            f"<b>P&L:</b> ₹{pnl:+,.2f} ({pnl_pct:+.1f}%)\n"
        )

        if holding_time:
            message += f"<b>Holding Time:</b> {holding_time}\n"

        # --- FIX: Added full date ---
        message += f"\n⏰ Exit Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"

        self.send_alert(message, f"{emoji} EXIT")

        # Console notification
        color_code = Fore.GREEN if pnl > 0 else Fore.RED
        print(f"\n{color_code}{'=' * 60}{Style.RESET_ALL}")
        print(f"{color_code}{emoji} TRADE EXIT: {trade_symbol}{Style.RESET_ALL}")
        print(f"{color_code}P&L: ₹{pnl:+,.2f} ({pnl_pct:+.1f}%){Style.RESET_ALL}")
        print(f"{color_code}Reason: {reason}{Style.RESET_ALL}")
        print(f"{color_code}{'=' * 60}{Style.RESET_ALL}\n")

    def notify_stop_loss_triggered(self, symbol: str, current_price: float,
                                   entry_price: float, stop_type: str,
                                   delta: float = None):
        """Notification when stop loss is triggered"""
        message = (
            f"🛑 <b>STOP LOSS TRIGGERED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Type:</b> {stop_type}\n"
            f"\n"
            f"<b>Entry Price:</b> ₹{entry_price:.2f}\n"
            f"<b>Current Price:</b> ₹{current_price:.2f}\n"
            f"<b>Move:</b> {((current_price - entry_price) / entry_price * 100):+.1f}%\n"
        )

        if delta:
            message += f"<b>Current Delta:</b> {delta:.1f}\n"

        # --- FIX: Added full date ---
        message += f"\n⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"
        message += f"\n⚠️ Closing position immediately..."

        self.send_alert(message, "🛑 STOP LOSS")

        # Console alert
        print(f"\n{Fore.RED}{'=' * 60}{Style.RESET_ALL}")
        print(f"{Fore.RED}🛑 STOP LOSS TRIGGERED: {symbol}{Style.RESET_ALL}")
        print(f"{Fore.RED}Type: {stop_type}{Style.RESET_ALL}")
        print(f"{Fore.RED}{'=' * 60}{Style.RESET_ALL}\n")

    def notify_profit_target(self, pair_id: str, entry_combined: float,
                             current_combined: float, pnl: float, pnl_pct: float):
        """Notification when profit target is hit"""
        message = (
            f"🎯 <b>PROFIT TARGET HIT!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Pair:</b> {pair_id.split('|')[0][:15]}...\n"
            f"\n"
            f"<b>Entry Premium:</b> ₹{entry_combined:.2f}\n"
            f"<b>Current Premium:</b> ₹{current_combined:.2f}\n"
            f"<b>Premium Decay:</b> ₹{entry_combined - current_combined:.2f}\n"
            f"\n"
            f"<b>Total P&L:</b> ₹{pnl:+,.2f} ({pnl_pct:+.1f}%)\n"
            f"\n"
            # --- FIX: Added full date ---
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"✅ Closing both legs..."
        )

        self.send_alert(message, "🎯 TARGET")

        # Console celebration
        print(f"\n{Fore.GREEN}{'=' * 60}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}🎯 PROFIT TARGET HIT!{Style.RESET_ALL}")
        print(f"{Fore.GREEN}P&L: ₹{pnl:+,.2f} ({pnl_pct:+.1f}%){Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'=' * 60}{Style.RESET_ALL}\n")

    def notify_square_off(self, total_positions: int, total_pnl: float):
        """Notification for end-of-day square off"""
        emoji = "✅" if total_pnl >= 0 else "⚠️"

        message = (
            f"{emoji} <b>TIME SQUARE OFF</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            # --- FIX: Added full date ---
            f"<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"<b>Positions Closed:</b> {total_positions}\n"
            f"<b>Total P&L:</b> ₹{total_pnl:+,.2f}\n"
            f"\n"
            f"📊 Day's trading completed"
        )

        self.send_alert(message, f"{emoji} SQUARE OFF")

    def notify_system_start(self, mode: str, capital: float, vix: float, spot: float):
        """Enhanced system start notification"""
        emoji = "📊" if mode == "PAPER" else "🔴"

        message = (
            f"{emoji} <b>SYSTEM STARTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Mode:</b> {mode} TRADING\n"
            f"<b>Capital:</b> ₹{capital:,.0f}\n"
            f"\n"
            f"<b>Market Status:</b>\n"
            f"  • NIFTY: ₹{spot:.2f}\n"
            f"  • VIX: {vix:.2f}\n"
            f"\n"
            f"⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"🤖 Monitoring markets..."
        )

        self.send_alert(message, "🟢 START")

    def send_daily_summary(self, metrics: Any):
        """Enhanced daily summary with emojis"""
        emoji = "✅" if metrics.total_pnl >= 0 else "❌"

        message = (
            f"{emoji} <b>DAILY SUMMARY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Total Trades:</b> {metrics.total_trades}\n"
            f"<b>Win Rate:</b> {metrics.win_rate:.1f}%\n"
            f"<b>Winning Trades:</b> {metrics.win_trades}/{metrics.total_trades}\n"
            f"\n"
            f"<b>P&L Breakdown:</b>\n"
            f"  • Total: ₹{metrics.total_pnl:+,.2f}\n"
            f"  • CE Leg: ₹{metrics.ce_pnl:+,.2f}\n"
            f"  • PE Leg: ₹{metrics.pe_pnl:+,.2f}\n"
            f"\n"
            f"<b>Risk Metrics:</b>\n"
            f"  • Max Drawdown: ₹{metrics.max_drawdown:,.2f}\n"
            f"  • Profit Factor: {metrics.profit_factor:.2f}\n"
            f"  • Sharpe Ratio: {metrics.sharpe_ratio:.2f}\n"
            f"\n"
            f"<b>Positions:</b>\n"
            f"  • Rolled: {metrics.rolled_positions}\n"
        )

        self.send_alert(message, "📊 SUMMARY")