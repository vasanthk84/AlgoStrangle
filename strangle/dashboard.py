"""
Console Dashboard - COMPLETE FIXED VERSION
✅ Dynamic Greek status (adjusts to VIX in real-time)
✅ Black Swan detection (VIX > 30)
✅ Daily Theta Income with explanation
✅ Correct P&L display
✅ ALL dashboard classes included
"""

import os
import sys
import time
from colorama import Fore, Style, init
from datetime import datetime

from .models import MarketData
from .trade_manager import TradeManager

init(autoreset=True)


class ConsoleDashboard:
    def __init__(self):
        self.last_update = 0
        self.update_interval = 1.0
        self.is_first_render = True

        self._clear_screen()
        self._print_header()

    def _clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def _print_header(self):
        print(f"{Fore.CYAN}{'=' * 110}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  NIFTY OPTIONS TRADING SYSTEM - DYNAMIC GREEKS MONITOR{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 110}{Style.RESET_ALL}\n")

    def _move_to_data_start(self):
        sys.stdout.write('\033[4;0H')
        sys.stdout.flush()

    def _clear_to_end(self):
        sys.stdout.write('\033[J')
        sys.stdout.flush()

    def _get_delta_status(self, delta: float, vix: float = None) -> tuple:
        """DYNAMIC Delta Status - Adjusts thresholds based on VIX"""
        abs_delta = abs(delta)

        if vix is None or vix < 15:
            safe_threshold = 15
            caution_threshold = 30
        elif vix < 20:
            safe_threshold = 12
            caution_threshold = 25
        elif vix < 30:
            safe_threshold = 10
            caution_threshold = 20
        else:
            safe_threshold = 5
            caution_threshold = 10

        if abs_delta < safe_threshold:
            return Fore.GREEN, "✅"
        elif abs_delta < caution_threshold:
            return Fore.YELLOW, "⚠️"
        else:
            return Fore.RED, "🛑"

    def _get_theta_status(self, theta: float, dte: int = None) -> tuple:
        """DYNAMIC Theta Status"""
        abs_theta = abs(theta)

        if dte is not None and dte < 7:
            excellent_threshold = 3.0
            moderate_threshold = 1.5
        else:
            excellent_threshold = 2.0
            moderate_threshold = 1.0

        if abs_theta > excellent_threshold:
            return Fore.GREEN, "💰"
        elif abs_theta > moderate_threshold:
            return Fore.YELLOW, "⏱️"
        else:
            return Fore.RED, "⚠️"

    def _get_gamma_status(self, gamma: float, vix: float = None) -> tuple:
        """DYNAMIC Gamma Status"""
        if vix is not None and vix > 30:
            safe_threshold = 0.5
            caution_threshold = 1.0
        elif vix is not None and vix > 20:
            safe_threshold = 0.8
            caution_threshold = 1.5
        else:
            safe_threshold = 1.0
            caution_threshold = 2.0

        if gamma < safe_threshold:
            return Fore.GREEN, "✅"
        elif gamma < caution_threshold:
            return Fore.YELLOW, "⚠️"
        else:
            if vix is not None and vix > 30:
                return Fore.RED, "🚨"
            else:
                return Fore.RED, "🛑"

    def render(self, market_data: MarketData, trade_manager: TradeManager):
        """Render dashboard with dynamic Greeks and correct P&L"""
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        if not self.is_first_render:
            self._move_to_data_start()
            self._clear_to_end()

        output_lines = []

        # Market data line
        pnl_color = Fore.GREEN if trade_manager.daily_pnl >= 0 else Fore.RED

        market_line = (
            f"{Fore.YELLOW}[{market_data.timestamp.strftime('%H:%M:%S')}]{Style.RESET_ALL} "
            f"NIFTY: {Fore.WHITE}{market_data.nifty_spot:.2f}{Style.RESET_ALL} | "
            f"VIX: {Fore.WHITE}{market_data.india_vix:.2f}{Style.RESET_ALL} | "
            f"IV: {Fore.WHITE}{market_data.iv_rank:.1f}%{Style.RESET_ALL} | "
            f"Trades: {Fore.WHITE}{len(trade_manager.active_trades)}{Style.RESET_ALL} | "
            f"P&L: {pnl_color}{trade_manager.daily_pnl:+,.2f}{Style.RESET_ALL}"
        )
        output_lines.append(market_line)

        # Active positions table
        if trade_manager.active_trades:
            output_lines.append("")
            output_lines.append(f"{Fore.CYAN}Active Positions with Live Greeks:{Style.RESET_ALL}")

            header = (
                f"  {Fore.CYAN}Type Strike   Entry  Current  P&L%    P&L       "
                f"Delta    Theta   Gamma  Status{Style.RESET_ALL}"
            )
            output_lines.append(header)
            output_lines.append(f"  {Fore.CYAN}{'─' * 100}{Style.RESET_ALL}")

            total_delta = 0.0
            total_theta = 0.0
            total_gamma = 0.0

            for trade in trade_manager.active_trades.values():
                pnl = trade.get_pnl()
                pnl_pct = trade.get_pnl_pct()
                row_color = Fore.GREEN if pnl >= 0 else Fore.RED

                if trade.greeks:
                    delta = trade.greeks.delta
                    theta = trade.greeks.theta
                    gamma = trade.greeks.gamma

                    total_delta += delta
                    total_theta += theta
                    total_gamma += gamma

                    delta_color, delta_icon = self._get_delta_status(delta, market_data.india_vix)
                    theta_color, theta_icon = self._get_theta_status(theta)
                    gamma_color, gamma_icon = self._get_gamma_status(gamma, market_data.india_vix)

                    greeks_display = (
                        f"{delta_color}{delta:+6.1f}{Style.RESET_ALL}  "
                        f"{theta_color}{theta:+6.2f}{Style.RESET_ALL}  "
                        f"{gamma_color}{gamma:5.2f}{Style.RESET_ALL}  "
                        f"{delta_icon}{theta_icon}{gamma_icon}"
                    )
                else:
                    greeks_display = "  N/A       N/A     N/A    ⚫"

                pos_line = (
                    f"  {trade.option_type:4s} "
                    f"{trade.strike_price:6.0f}  "
                    f"{trade.entry_price:6.2f}  "
                    f"{trade.current_price:6.2f}  "
                    f"{row_color}{pnl_pct:+5.1f}%{Style.RESET_ALL}  "
                    f"{row_color}{pnl:+9,.2f}{Style.RESET_ALL}  "
                    f"{greeks_display}"
                )
                output_lines.append(pos_line)

            output_lines.append(f"  {Fore.CYAN}{'─' * 100}{Style.RESET_ALL}")

            # Combined metrics
            delta_balance = "BALANCED ✅" if abs(total_delta) < 10 else "DIRECTIONAL ⚠️" if abs(total_delta) < 20 else "SKEWED 🛑"
            delta_color = Fore.GREEN if abs(total_delta) < 10 else Fore.YELLOW if abs(total_delta) < 20 else Fore.RED

            lot_size = 75
            total_lots = sum(t.qty for t in trade_manager.active_trades.values())
            daily_theta_income = abs(total_theta) * lot_size * total_lots
            theta_color = Fore.GREEN if daily_theta_income > 300 else Fore.YELLOW

            combined_line = (
                f"  {Fore.WHITE}Combined:{Style.RESET_ALL} "
                f"Net Delta: {delta_color}{total_delta:+.1f}{Style.RESET_ALL} ({delta_balance}) | "
                f"Daily Θ Income: {theta_color}₹{daily_theta_income:,.2f}/day{Style.RESET_ALL} 💰 | "
                f"Total Γ: {total_gamma:.2f}"
            )
            output_lines.append(combined_line)

            # Theta explanation
            theta_explanation = (
                f"  {Fore.CYAN}ℹ️  Daily Θ Income:{Style.RESET_ALL} "
                f"If market stays stable, you'll collect ~₹{daily_theta_income:,.0f} from time decay EACH DAY"
            )
            output_lines.append(theta_explanation)

        else:
            output_lines.append("")
            output_lines.append(f"{Fore.YELLOW}No active positions{Style.RESET_ALL}")

        # Greeks legend with market regime
        output_lines.append("")
        output_lines.append(f"{Fore.CYAN}Greeks Status (DYNAMIC - Adjusts to Market Conditions):{Style.RESET_ALL}")

        regime_line = f"  Current VIX: {market_data.india_vix:.1f} → "
        if market_data.india_vix < 15:
            regime_line += f"{Fore.GREEN}Normal Market{Style.RESET_ALL} (Standard thresholds)"
        elif market_data.india_vix < 20:
            regime_line += f"{Fore.YELLOW}Elevated Volatility{Style.RESET_ALL} (Tighter risk controls)"
        elif market_data.india_vix < 30:
            regime_line += f"{Fore.RED}High Volatility{Style.RESET_ALL} (STRICT risk limits active)"
        else:
            regime_line += f"{Fore.RED}🚨 BLACK SWAN EVENT{Style.RESET_ALL} (MAXIMUM caution - consider hedging!)"

        output_lines.append(regime_line)
        output_lines.append("")
        output_lines.append(
            f"  {Fore.GREEN}✅ Safe{Style.RESET_ALL}  "
            f"{Fore.YELLOW}⚠️ Caution{Style.RESET_ALL}  "
            f"{Fore.RED}🛑 Danger{Style.RESET_ALL}  "
            f"{Fore.RED}🚨 CRITICAL{Style.RESET_ALL}"
        )
        output_lines.append("")
        output_lines.append(f"  Delta (Δ): Directional exposure (thresholds adjust with VIX)")
        output_lines.append(f"  Theta (Θ): Daily time decay income for sellers 💰")
        output_lines.append(f"  Gamma (Γ): Risk acceleration (spikes near ATM/expiry)")

        # Daily summary
        output_lines.append("")
        summary_line = (
            f"{Fore.CYAN}Daily Summary:{Style.RESET_ALL} "
            f"Trades: {trade_manager.total_trades} | "
            f"CE: {Fore.GREEN if trade_manager.ce_pnl >= 0 else Fore.RED}"
            f"{trade_manager.ce_pnl:+,.2f}{Style.RESET_ALL} | "
            f"PE: {Fore.GREEN if trade_manager.pe_pnl >= 0 else Fore.RED}"
            f"{trade_manager.pe_pnl:+,.2f}{Style.RESET_ALL} | "
            f"Total: {pnl_color}{trade_manager.daily_pnl:+,.2f}{Style.RESET_ALL}"
        )
        output_lines.append(summary_line)

        # Footer
        output_lines.append("")
        output_lines.append(f"{Fore.CYAN}{'─' * 110}{Style.RESET_ALL}")
        output_lines.append(f"{Fore.YELLOW}Press Ctrl+C to stop gracefully{Style.RESET_ALL}")

        print('\n'.join(output_lines), flush=True)

        self.last_update = current_time
        self.is_first_render = False


class ConsoleDashboardCompact:
    """Compact version - fits more on smaller terminals"""
    def __init__(self):
        self.last_update = 0
        self._clear_screen()
        self._print_header()

    def _clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def _print_header(self):
        print(f"{Fore.CYAN}{'=' * 90}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  NIFTY OPTIONS - DYNAMIC GREEKS MONITOR{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 90}{Style.RESET_ALL}\n")

    def _move_to_data_start(self):
        sys.stdout.write('\033[4;0H')
        sys.stdout.flush()

    def _clear_to_end(self):
        sys.stdout.write('\033[J')
        sys.stdout.flush()

    def render(self, market_data: MarketData, trade_manager: TradeManager):
        current_time = time.time()
        if current_time - self.last_update < 1:
            return

        self._move_to_data_start()
        self._clear_to_end()

        output_lines = []

        # Market line
        pnl_color = Fore.GREEN if trade_manager.daily_pnl >= 0 else Fore.RED
        market_line = (
            f"[{market_data.timestamp.strftime('%H:%M:%S')}] "
            f"NIFTY:{market_data.nifty_spot:.0f} VIX:{market_data.india_vix:.1f} "
            f"Trades:{len(trade_manager.active_trades)} "
            f"P&L:{pnl_color}{trade_manager.daily_pnl:+,.0f}{Style.RESET_ALL}"
        )
        output_lines.append(market_line)

        # Positions
        if trade_manager.active_trades:
            output_lines.append("")
            output_lines.append(f"{Fore.CYAN}Pos   Strike  Entry  Curr   P&L%    Δ     Θ    Status{Style.RESET_ALL}")
            output_lines.append(f"{Fore.CYAN}{'─' * 70}{Style.RESET_ALL}")

            for trade in trade_manager.active_trades.values():
                pnl_pct = trade.get_pnl_pct()
                color = Fore.GREEN if pnl_pct >= 0 else Fore.RED

                if trade.greeks:
                    delta = trade.greeks.delta
                    theta = trade.greeks.theta
                    status = "✅" if abs(delta) < 15 else "⚠️" if abs(delta) < 30 else "🛑"

                    pos_line = (
                        f"{trade.option_type:4s} "
                        f"{trade.strike_price:6.0f} "
                        f"{trade.entry_price:5.1f} "
                        f"{trade.current_price:5.1f} "
                        f"{color}{pnl_pct:+5.1f}%{Style.RESET_ALL} "
                        f"{delta:+5.1f} "
                        f"{theta:+5.2f} "
                        f"{status}"
                    )
                else:
                    pos_line = (
                        f"{trade.option_type:4s} "
                        f"{trade.strike_price:6.0f} "
                        f"{trade.entry_price:5.1f} "
                        f"{trade.current_price:5.1f} "
                        f"{color}{pnl_pct:+5.1f}%{Style.RESET_ALL} "
                        f"  N/A   N/A  ⚫"
                    )

                output_lines.append(pos_line)

        output_lines.append("")
        output_lines.append(f"{Fore.CYAN}{'─' * 70}{Style.RESET_ALL}")

        print('\n'.join(output_lines), flush=True)
        self.last_update = current_time


class ConsoleDashboardMinimal:
    """Single-line minimal dashboard"""
    def __init__(self):
        self.last_update = 0
        print("\n" + "=" * 100)
        print("NIFTY OPTIONS TRADING - MINIMAL MODE")
        print("=" * 100 + "\n")

    def render(self, market_data: MarketData, trade_manager: TradeManager):
        current_time = time.time()
        if current_time - self.last_update < 1:
            return

        pnl_color = Fore.GREEN if trade_manager.daily_pnl >= 0 else Fore.RED

        status = (
            f"[{market_data.timestamp.strftime('%H:%M:%S')}] "
            f"NIFTY: {market_data.nifty_spot:.2f} | "
            f"VIX: {market_data.india_vix:.2f} | "
            f"Trades: {len(trade_manager.active_trades)} | "
            f"P&L: {pnl_color}{trade_manager.daily_pnl:+,.2f}{Style.RESET_ALL}"
        ).ljust(100)

        print(f"\r{status}", end='', flush=True)
        self.last_update = current_time


def create_dashboard(mode="full"):
    """
    Factory function to create dashboard

    Args:
        mode: "full", "compact", or "minimal"
    """
    if mode == "compact":
        return ConsoleDashboardCompact()
    elif mode == "minimal":
        return ConsoleDashboardMinimal()
    else:
        try:
            sys.stdout.write('\033[0m')
            sys.stdout.flush()
            return ConsoleDashboard()
        except:
            return ConsoleDashboardMinimal()