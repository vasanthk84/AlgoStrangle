"""
Notification management for the Short Strangle Trading System
"""

import logging
from typing import Any
import requests

from .config import Config


class NotificationManager:
    def __init__(self):
        self.bot_token = Config.TELEGRAM_BOT_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID

    def send_alert(self, message: str, level: str):
        if self.bot_token == "your_telegram_bot_token":
            return  # Skip if not configured
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

    def send_daily_summary(self, metrics: Any):
        message = (
            f"<b>Daily Summary</b>\n"
            f"Total Trades: {metrics.total_trades}\n"
            f"Win Rate: {metrics.win_rate:.1f}%\n"
            f"Total P&L: Rs.{metrics.total_pnl:,.2f}\n"
            f"CE P&L: Rs.{metrics.ce_pnl:,.2f}\n"
            f"PE P&L: Rs.{metrics.pe_pnl:,.2f}\n"
            f"Profit Factor: {metrics.profit_factor:.2f}"
        )
        self.send_alert(message, "INFO")
