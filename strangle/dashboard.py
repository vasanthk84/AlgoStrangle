"""
Console dashboard for the Short Strangle Trading System
"""

import time
from colorama import Fore, Style
from tabulate import tabulate

from .models import MarketData
from .trade_manager import TradeManager


class ConsoleDashboard:
    def __init__(self):
        self.last_update = 0

    def render(self, market_data: MarketData, trade_manager: TradeManager):
        if time.time() - self.last_update < 1:
            return
        print(f"\n{'=' * 80}")
        print(f"{Fore.CYAN}ENHANCED SHORT STRANGLE NIFTY OPTIONS{Style.RESET_ALL}")
        print(f"{'=' * 80}")
        data = [
            ["NIFTY Spot", f"{market_data.nifty_spot:.2f}"],
            ["India VIX", f"{market_data.india_vix:.2f}"],
            ["IV Percentile", f"{market_data.iv_percentile:.1f}%"],
            ["Active Trades", len(trade_manager.active_trades)],
            ["Daily P&L", f"Rs.{trade_manager.daily_pnl:,.2f}"],
            ["CE Leg P&L", f"Rs.{trade_manager.ce_pnl:,.2f}"],
            ["PE Leg P&L", f"Rs.{trade_manager.pe_pnl:,.2f}"],
            ["Rolled Positions", trade_manager.rolled_positions]
        ]
        print(tabulate(data, headers=["Metric", "Value"], tablefmt="grid"))

        if trade_manager.active_trades:
            print(f"\n{Fore.CYAN}Active Positions:{Style.RESET_ALL}")
            pos_data = []
            for trade in trade_manager.active_trades.values():
                pos_data.append([
                    trade.option_type,
                    trade.symbol,
                    f"Rs.{trade.entry_price:.2f}",
                    f"Rs.{trade.current_price:.2f}",
                    f"{trade.get_pnl_pct():.1f}%",
                    f"Rs.{trade.get_pnl():,.2f}",
                    f"Rs.{trade.trailing_stop_price:.2f}" if trade.trailing_stop_price else "N/A"
                ])
            print(tabulate(pos_data, headers=["Type", "Symbol", "Entry", "Current", "P&L%", "P&L", "Trail Stop"],
                           tablefmt="grid"))

        self.last_update = time.time()
