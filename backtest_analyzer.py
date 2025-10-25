"""
backtest_analyzer.py
Analyze and visualize backtest results
"""

import pandas as pd
import numpy as np
from pathlib import Path
from colorama import Fore, Style
from tabulate import tabulate
import sqlite3
from datetime import datetime


class BacktestAnalyzer:
    def __init__(self, db_file: str = "trades_database.db"):
        self.db_file = db_file
        self.trades_df = None
        self.daily_perf_df = None
        self.load_data()
    
    def load_data(self):
        """Load data from database"""
        try:
            conn = sqlite3.connect(self.db_file)
            self.trades_df = pd.read_sql_query("SELECT * FROM trades", conn)
            self.daily_perf_df = pd.read_sql_query("SELECT * FROM daily_performance", conn)
            conn.close()
            
            if not self.trades_df.empty:
                self.trades_df['entry_time'] = pd.to_datetime(self.trades_df['entry_time'])
                self.trades_df['exit_time'] = pd.to_datetime(self.trades_df['exit_time'])
            
            if not self.daily_perf_df.empty:
                self.daily_perf_df['date'] = pd.to_datetime(self.daily_perf_df['date'])
                self.daily_perf_df = self.daily_perf_df.sort_values('date')
            
            print(f"{Fore.GREEN}Loaded {len(self.trades_df)} trades and {len(self.daily_perf_df)} days of performance data{Style.RESET_ALL}")
        
        except Exception as e:
            print(f"{Fore.RED}Error loading data: {e}{Style.RESET_ALL}")
    
    def overall_statistics(self):
        """Calculate and display overall statistics"""
        if self.trades_df.empty:
            print(f"{Fore.YELLOW}No trades found in database{Style.RESET_ALL}")
            return
        
        print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}OVERALL STATISTICS{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")
        
        completed_trades = self.trades_df[self.trades_df['pnl'].notna()]
        
        total_trades = len(completed_trades)
        winning_trades = len(completed_trades[completed_trades['pnl'] > 0])
        losing_trades = len(completed_trades[completed_trades['pnl'] < 0])
        
        total_pnl = completed_trades['pnl'].sum()
        avg_win = completed_trades[completed_trades['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = completed_trades[completed_trades['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
        
        largest_win = completed_trades['pnl'].max()
        largest_loss = completed_trades['pnl'].min()
        
        # By option type
        ce_trades = completed_trades[completed_trades['option_type'] == 'CE']
        pe_trades = completed_trades[completed_trades['option_type'] == 'PE']
        
        stats_data = [
            ["Total Trades", total_trades],
            ["Winning Trades", f"{winning_trades} ({winning_trades/total_trades*100:.1f}%)"],
            ["Losing Trades", f"{losing_trades} ({losing_trades/total_trades*100:.1f}%)"],
            ["", ""],
            ["Total P&L", f"₹{total_pnl:,.2f}"],
            ["Average Win", f"₹{avg_win:,.2f}"],
            ["Average Loss", f"₹{avg_loss:,.2f}"],
            ["Largest Win", f"₹{largest_win:,.2f}"],
            ["Largest Loss", f"₹{largest_loss:,.2f}"],
            ["", ""],
            ["CE Trades", len(ce_trades)],
            ["CE P&L", f"₹{ce_trades['pnl'].sum():,.2f}"],
            ["PE Trades", len(pe_trades)],
            ["PE P&L", f"₹{pe_trades['pnl'].sum():,.2f}"],
        ]
        
        print(tabulate(stats_data, headers=["Metric", "Value"], tablefmt="grid"))
    
    def monthly_breakdown(self):
        """Monthly performance breakdown"""
        if self.trades_df.empty:
            return
        
        print(f"\n{Fore.CYAN}MONTHLY BREAKDOWN{Style.RESET_ALL}\n")
        
        completed_trades = self.trades_df[self.trades_df['pnl'].notna()].copy()
        completed_trades['month'] = completed_trades['entry_time'].dt.to_period('M')
        
        monthly_stats = []
        for month, group in completed_trades.groupby('month'):
            total = len(group)
            wins = len(group[group['pnl'] > 0])
            pnl = group['pnl'].sum()
            
            monthly_stats.append([
                str(month),
                total,
                wins,
                f"{wins/total*100:.1f}%",
                f"₹{pnl:,.2f}"
            ])
        
        print(tabulate(monthly_stats, 
                      headers=["Month", "Trades", "Wins", "Win Rate", "P&L"],
                      tablefmt="grid"))
    
    def strike_analysis(self):
        """Analyze performance by strike distance"""
        if self.trades_df.empty:
            return
        
        print(f"\n{Fore.CYAN}STRIKE ANALYSIS{Style.RESET_ALL}\n")
        
        completed_trades = self.trades_df[self.trades_df['pnl'].notna()].copy()
        
        # Group by strike ranges
        completed_trades['strike_bucket'] = pd.cut(
            completed_trades['strike_price'], 
            bins=[0, 20000, 21000, 22000, 23000, 24000, 100000],
            labels=['<20k', '20k-21k', '21k-22k', '22k-23k', '23k-24k', '>24k']
        )
        
        strike_stats = []
        for bucket, group in completed_trades.groupby('strike_bucket'):
            total = len(group)
            wins = len(group[group['pnl'] > 0])
            pnl = group['pnl'].sum()
            
            strike_stats.append([
                str(bucket),
                total,
                f"{wins/total*100:.1f}%" if total > 0 else "N/A",
                f"₹{pnl:,.2f}"
            ])
        
        print(tabulate(strike_stats,
                      headers=["Strike Range", "Trades", "Win Rate", "P&L"],
                      tablefmt="grid"))
    
    def rolled_positions_analysis(self):
        """Analyze rolled positions performance"""
        if self.trades_df.empty:
            return
        
        print(f"\n{Fore.CYAN}ROLLED POSITIONS ANALYSIS{Style.RESET_ALL}\n")
        
        rolled = self.trades_df[self.trades_df['rolled_from'].notna()]
        
        if rolled.empty:
            print("No rolled positions found")
            return
        
        print(f"Total Rolled Positions: {len(rolled)}")
        print(f"Rolled CE: {len(rolled[rolled['option_type'] == 'CE'])}")
        print(f"Rolled PE: {len(rolled[rolled['option_type'] == 'PE'])}")
        
        if not rolled[rolled['pnl'].notna()].empty:
            rolled_pnl = rolled[rolled['pnl'].notna()]['pnl'].sum()
            print(f"Total P&L from Rolled Positions: ₹{rolled_pnl:,.2f}")
    
    def daily_performance_chart(self):
        """Display daily performance"""
        if self.daily_perf_df.empty:
            return
        
        print(f"\n{Fore.CYAN}DAILY PERFORMANCE{Style.RESET_ALL}\n")
        
        # Calculate cumulative P&L
        self.daily_perf_df['cumulative_pnl'] = self.daily_perf_df['total_pnl'].cumsum()
        
        # Show last 10 days
        recent = self.daily_perf_df.tail(10)
        
        daily_data = []
        for _, row in recent.iterrows():
            daily_data.append([
                row['date'].strftime('%Y-%m-%d'),
                row['total_trades'],
                f"{row['win_trades']}/{row['total_trades']}",
                f"₹{row['total_pnl']:,.2f}",
                f"₹{row['cumulative_pnl']:,.2f}"
            ])
        
        print(tabulate(daily_data,
                      headers=["Date", "Trades", "W/L", "Daily P&L", "Cumulative P&L"],
                      tablefmt="grid"))
    
    def risk_metrics(self):
        """Calculate risk metrics"""
        if self.daily_perf_df.empty:
            return
        
        print(f"\n{Fore.CYAN}RISK METRICS{Style.RESET_ALL}\n")
        
        daily_pnl = self.daily_perf_df['total_pnl'].values
        
        # Calculate metrics
        total_return = daily_pnl.sum()
        num_days = len(daily_pnl)
        avg_daily_return = daily_pnl.mean()
        std_daily_return = daily_pnl.std()
        
        # Max drawdown
        cumulative = np.cumsum(daily_pnl)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max
        max_drawdown = abs(np.min(drawdown))
        
        # Sharpe ratio (annualized)
        sharpe = (avg_daily_return / std_daily_return) * np.sqrt(252) if std_daily_return > 0 else 0
        
        # Win/Loss days
        winning_days = len([p for p in daily_pnl if p > 0])
        losing_days = len([p for p in daily_pnl if p < 0])
        
        # Profit factor
        profits = [p for p in daily_pnl if p > 0]
        losses = [abs(p) for p in daily_pnl if p < 0]
        profit_factor = sum(profits) / sum(losses) if losses else 0
        
        risk_data = [
            ["Total Return", f"₹{total_return:,.2f}"],
            ["Trading Days", num_days],
            ["Avg Daily Return", f"₹{avg_daily_return:,.2f}"],
            ["Std Dev (Daily)", f"₹{std_daily_return:,.2f}"],
            ["", ""],
            ["Max Drawdown", f"₹{max_drawdown:,.2f}"],
            ["Sharpe Ratio", f"{sharpe:.2f}"],
            ["Profit Factor", f"{profit_factor:.2f}"],
            ["", ""],
            ["Winning Days", f"{winning_days} ({winning_days/num_days*100:.1f}%)"],
            ["Losing Days", f"{losing_days} ({losing_days/num_days*100:.1f}%)"],
        ]
        
        print(tabulate(risk_data, headers=["Metric", "Value"], tablefmt="grid"))
    
    def best_worst_trades(self):
        """Show best and worst trades"""
        if self.trades_df.empty:
            return
        
        print(f"\n{Fore.CYAN}BEST & WORST TRADES{Style.RESET_ALL}\n")
        
        completed = self.trades_df[self.trades_df['pnl'].notna()].copy()
        
        # Best 5 trades
        print(f"{Fore.GREEN}Top 5 Winning Trades:{Style.RESET_ALL}")
        best = completed.nlargest(5, 'pnl')
        best_data = []
        for _, trade in best.iterrows():
            best_data.append([
                trade['symbol'],
                trade['option_type'],
                trade['entry_time'].strftime('%Y-%m-%d'),
                f"₹{trade['entry_price']:.2f}",
                f"₹{trade['exit_price']:.2f}",
                f"₹{trade['pnl']:,.2f}"
            ])
        print(tabulate(best_data, 
                      headers=["Symbol", "Type", "Date", "Entry", "Exit", "P&L"],
                      tablefmt="simple"))
        
        # Worst 5 trades
        print(f"\n{Fore.RED}Top 5 Losing Trades:{Style.RESET_ALL}")
        worst = completed.nsmallest(5, 'pnl')
        worst_data = []
        for _, trade in worst.iterrows():
            worst_data.append([
                trade['symbol'],
                trade['option_type'],
                trade['entry_time'].strftime('%Y-%m-%d'),
                f"₹{trade['entry_price']:.2f}",
                f"₹{trade['exit_price']:.2f}",
                f"₹{trade['pnl']:,.2f}"
            ])
        print(tabulate(worst_data,
                      headers=["Symbol", "Type", "Date", "Entry", "Exit", "P&L"],
                      tablefmt="simple"))
    
    def export_summary_report(self, filename: str = None):
        """Export detailed summary report"""
        if filename is None:
            filename = f"backtest_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("BACKTEST ANALYSIS REPORT\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            # Add all analysis sections
            if not self.trades_df.empty:
                completed = self.trades_df[self.trades_df['pnl'].notna()]
                f.write(f"Total Trades: {len(completed)}\n")
                f.write(f"Total P&L: ₹{completed['pnl'].sum():,.2f}\n")
                f.write(f"Win Rate: {len(completed[completed['pnl'] > 0])/len(completed)*100:.1f}%\n")
            
            if not self.daily_perf_df.empty:
                f.write(f"\nTrading Days: {len(self.daily_perf_df)}\n")
                f.write(f"Avg Daily P&L: ₹{self.daily_perf_df['total_pnl'].mean():,.2f}\n")
        
        print(f"\n{Fore.GREEN}Report exported to: {filename}{Style.RESET_ALL}")
    
    def run_full_analysis(self):
        """Run complete analysis"""
        print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}BACKTEST RESULTS ANALYSIS{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
        
        self.overall_statistics()
        self.monthly_breakdown()
        self.daily_performance_chart()
        self.risk_metrics()
        self.strike_analysis()
        self.rolled_positions_analysis()
        self.best_worst_trades()
        
        print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")


def main():
    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  BACKTEST RESULTS ANALYZER  {Style.RESET_ALL}
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
""")
    
    db_file = input("Enter database file path (default: trades_database.db): ").strip()
    if not db_file:
        db_file = "trades_database.db"
    
    if not Path(db_file).exists():
        print(f"{Fore.RED}Database file not found: {db_file}{Style.RESET_ALL}")
        return
    
    analyzer = BacktestAnalyzer(db_file)
    
    print("\nSelect analysis option:")
    print("1. Full Analysis Report")
    print("2. Overall Statistics Only")
    print("3. Monthly Breakdown")
    print("4. Risk Metrics")
    print("5. Best/Worst Trades")
    print("6. Export Summary Report")
    print("7. Exit")
    
    choice = input("\nEnter choice (1-7): ").strip()
    
    if choice == "1":
        analyzer.run_full_analysis()
    elif choice == "2":
        analyzer.overall_statistics()
    elif choice == "3":
        analyzer.monthly_breakdown()
    elif choice == "4":
        analyzer.risk_metrics()
    elif choice == "5":
        analyzer.best_worst_trades()
    elif choice == "6":
        filename = input("Enter filename (or press Enter for default): ").strip()
        analyzer.export_summary_report(filename if filename else None)
    elif choice == "7":
        print(f"{Fore.GREEN}Goodbye!{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}Invalid choice{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
