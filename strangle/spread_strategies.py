"""
Vertical Spread Strategy Implementations
Save as: strangle/spread_strategies.py
"""

from typing import Optional, Tuple
from datetime import datetime, date, timedelta
import logging
import pandas as pd

from .config import Config
from .models import Trade, Direction, MarketData
from .broker import BrokerInterface
from .trade_manager import TradeManager
from .greeks_calculator import GreeksCalculator
from .utils import Utils


class SpreadStrategies:
    """
    Implements vertical spread strategies:
    - Short Put Spread (bullish income)
    - Short Call Spread (bearish income)
    - Iron Condor (neutral, defined risk)
    """
    
    def __init__(self, broker: BrokerInterface, trade_manager: TradeManager,
                 greeks_calc: GreeksCalculator):
        self.broker = broker
        self.trade_manager = trade_manager
        self.greeks_calc = greeks_calc
    
    def _get_expiry_and_dte(self, entry_timestamp: Optional[datetime] = None) -> Tuple[date, int]:
        """Calculate next Tuesday expiry and DTE"""
        current = entry_timestamp or datetime.now()
        days_until_tuesday = (1 - current.weekday()) % 7
        if days_until_tuesday == 0 and current.time() >= datetime.strptime("15:30:00", "%H:%M:%S").time():
            days_until_tuesday = 7
        expiry = (current + timedelta(days=days_until_tuesday)).date()
        dte = self.greeks_calc.get_dte(expiry, current.date())
        return expiry, dte
    
    def execute_short_put_spread(self, market_data: MarketData, qty: int,
                                 entry_timestamp: Optional[datetime] = None) -> bool:
        """
        Short Put Vertical Spread (Bullish Income Strategy)
        
        Strategy: Sell higher strike put, buy lower strike put
        - Max profit: Net credit received
        - Max loss: (Strike difference - Net credit) * qty
        - Best in: Bullish/neutral markets, moderate IV
        
        Example:
        - Spot: 25,000
        - Sell 24,800 PE @ 80
        - Buy 24,600 PE @ 40
        - Net credit: 40 points
        - Max loss: (200 - 40) = 160 points
        - Risk/Reward: 4:1 (160 risk for 40 reward)
        """
        spot = market_data.nifty_spot
        vix = market_data.india_vix
        
        logging.info(f"EXECUTING SHORT PUT SPREAD: Spot={spot:.2f}, VIX={vix:.2f}")
        
        # Get expiry and DTE
        expiry, dte = self._get_expiry_and_dte(entry_timestamp)
        
        if dte > Config.MAX_DTE_TO_ENTER or dte < Config.MIN_DTE_TO_HOLD:
            logging.warning(f"DTE {dte} out of range")
            return False
        
        # Strike selection for put spread
        atm = round(spot / 50) * 50
        
        # Sell put: Go below spot (delta ~20-25)
        sell_distance = 300  # Start 300 points below ATM
        sell_strike = atm - sell_distance
        
        # Buy put: Go 200 points further down (protection)
        spread_width = 200
        buy_strike = sell_strike - spread_width
        
        # Get symbols and prices
        sell_symbol = Utils.prepare_option_symbol(sell_strike, "PE", expiry)
        buy_symbol = Utils.prepare_option_symbol(buy_strike, "PE", expiry)
        
        sell_price = self.broker.get_quote(sell_symbol)
        buy_price = self.broker.get_quote(buy_symbol)
        
        if sell_price <= 0 or buy_price <= 0:
            logging.error(f"Invalid prices: Sell={sell_price}, Buy={buy_price}")
            return False
        
        net_credit = sell_price - buy_price
        
        # Validate spread quality
        if net_credit < 30:  # Minimum credit threshold
            logging.warning(f"Net credit too low: {net_credit:.2f}")
            return False
        
        if net_credit > spread_width * 0.6:  # Credit >60% of width = too risky
            logging.warning(f"Credit too high relative to width: {net_credit:.2f}/{spread_width}")
            return False
        
        # Calculate deltas
        sell_delta = abs(self.greeks_calc.calculate_delta(spot, sell_strike, dte, vix, "PE"))
        buy_delta = abs(self.greeks_calc.calculate_delta(spot, buy_strike, dte, vix, "PE"))
        
        logging.info(
            f"PUT SPREAD SETUP:\n"
            f"  Sell: {sell_strike} PE @ {sell_price:.2f} (Δ={sell_delta:.1f})\n"
            f"  Buy:  {buy_strike} PE @ {buy_price:.2f} (Δ={buy_delta:.1f})\n"
            f"  Net Credit: {net_credit:.2f}\n"
            f"  Max Risk: {spread_width - net_credit:.2f}\n"
            f"  Risk/Reward: {(spread_width-net_credit)/net_credit:.2f}:1"
        )
        
        # Execute orders
        lot_size = self.broker.get_lot_size("NIFTY")
        ts = entry_timestamp or datetime.now()
        
        # Sell put (short)
        sell_order_id = self.broker.place_order(sell_symbol, qty, Direction.SELL, sell_price)
        
        # Buy put (long, protection)
        buy_order_id = self.broker.place_order(buy_symbol, qty, Direction.BUY, buy_price)
        
        if not sell_order_id or not buy_order_id:
            logging.error("Failed to execute spread")
            return False
        
        # Create trades
        sell_trade = Trade(sell_order_id, sell_symbol, qty, Direction.SELL, sell_price,
                          ts, "PE", lot_size, sell_strike, expiry, spot)
        buy_trade = Trade(buy_order_id, buy_symbol, qty, Direction.BUY, buy_price,
                         ts, "PE", lot_size, buy_strike, expiry, spot)
        
        # Update greeks
        sell_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_strike, dte, vix, "PE")
        buy_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_strike, dte, vix, "PE")
        sell_trade.update_price(sell_price, sell_greeks)
        buy_trade.update_price(buy_price, buy_greeks)
        
        # Add to manager
        self.trade_manager.add_trade(sell_trade)
        self.trade_manager.add_trade(buy_trade)
        
        # Register as pair
        self.trade_manager.add_trade_pair(
            sell_trade.trade_id,
            buy_trade.trade_id,
            net_credit,
            ts,
            qty,
            profit_target=net_credit * 0.5,  # 50% profit target
            stop_loss=spread_width - net_credit  # Max loss = width - credit
        )
        
        logging.info(f"SHORT PUT SPREAD EXECUTED: {sell_trade.trade_id}|{buy_trade.trade_id}")
        return True
    
    def execute_short_call_spread(self, market_data: MarketData, qty: int,
                                  entry_timestamp: Optional[datetime] = None) -> bool:
        """
        Short Call Vertical Spread (Bearish Income Strategy)
        
        Strategy: Sell lower strike call, buy higher strike call
        - Max profit: Net credit received
        - Max loss: (Strike difference - Net credit) * qty
        - Best in: Bearish/neutral markets, moderate IV
        
        Example:
        - Spot: 25,000
        - Sell 25,200 CE @ 80
        - Buy 25,400 CE @ 40
        - Net credit: 40 points
        - Max loss: (200 - 40) = 160 points
        """
        spot = market_data.nifty_spot
        vix = market_data.india_vix
        
        logging.info(f"EXECUTING SHORT CALL SPREAD: Spot={spot:.2f}, VIX={vix:.2f}")
        
        # Get expiry and DTE
        expiry, dte = self._get_expiry_and_dte(entry_timestamp)
        
        if dte > Config.MAX_DTE_TO_ENTER or dte < Config.MIN_DTE_TO_HOLD:
            logging.warning(f"DTE {dte} out of range")
            return False
        
        # Strike selection for call spread
        atm = round(spot / 50) * 50
        
        # Sell call: Go above spot (delta ~20-25)
        sell_distance = 300
        sell_strike = atm + sell_distance
        
        # Buy call: Go 200 points further up (protection)
        spread_width = 200
        buy_strike = sell_strike + spread_width
        
        # Get symbols and prices
        sell_symbol = Utils.prepare_option_symbol(sell_strike, "CE", expiry)
        buy_symbol = Utils.prepare_option_symbol(buy_strike, "CE", expiry)
        
        sell_price = self.broker.get_quote(sell_symbol)
        buy_price = self.broker.get_quote(buy_symbol)
        
        if sell_price <= 0 or buy_price <= 0:
            logging.error(f"Invalid prices: Sell={sell_price}, Buy={buy_price}")
            return False
        
        net_credit = sell_price - buy_price
        
        # Validate spread quality
        if net_credit < 30:
            logging.warning(f"Net credit too low: {net_credit:.2f}")
            return False
        
        if net_credit > spread_width * 0.6:
            logging.warning(f"Credit too high relative to width: {net_credit:.2f}/{spread_width}")
            return False
        
        # Calculate deltas
        sell_delta = self.greeks_calc.calculate_delta(spot, sell_strike, dte, vix, "CE")
        buy_delta = self.greeks_calc.calculate_delta(spot, buy_strike, dte, vix, "CE")
        
        logging.info(
            f"CALL SPREAD SETUP:\n"
            f"  Sell: {sell_strike} CE @ {sell_price:.2f} (Δ={sell_delta:.1f})\n"
            f"  Buy:  {buy_strike} CE @ {buy_price:.2f} (Δ={buy_delta:.1f})\n"
            f"  Net Credit: {net_credit:.2f}\n"
            f"  Max Risk: {spread_width - net_credit:.2f}\n"
            f"  Risk/Reward: {(spread_width-net_credit)/net_credit:.2f}:1"
        )
        
        # Execute orders
        lot_size = self.broker.get_lot_size("NIFTY")
        ts = entry_timestamp or datetime.now()
        
        # Sell call (short)
        sell_order_id = self.broker.place_order(sell_symbol, qty, Direction.SELL, sell_price)
        
        # Buy call (long, protection)
        buy_order_id = self.broker.place_order(buy_symbol, qty, Direction.BUY, buy_price)
        
        if not sell_order_id or not buy_order_id:
            logging.error("Failed to execute spread")
            return False
        
        # Create trades
        sell_trade = Trade(sell_order_id, sell_symbol, qty, Direction.SELL, sell_price,
                          ts, "CE", lot_size, sell_strike, expiry, spot)
        buy_trade = Trade(buy_order_id, buy_symbol, qty, Direction.BUY, buy_price,
                         ts, "CE", lot_size, buy_strike, expiry, spot)
        
        # Update greeks
        sell_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_strike, dte, vix, "CE")
        buy_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_strike, dte, vix, "CE")
        sell_trade.update_price(sell_price, sell_greeks)
        buy_trade.update_price(buy_price, buy_greeks)
        
        # Add to manager
        self.trade_manager.add_trade(sell_trade)
        self.trade_manager.add_trade(buy_trade)
        
        # Register as pair
        self.trade_manager.add_trade_pair(
            sell_trade.trade_id,
            buy_trade.trade_id,
            net_credit,
            ts,
            qty,
            profit_target=net_credit * 0.5,
            stop_loss=spread_width - net_credit
        )
        
        logging.info(f"SHORT CALL SPREAD EXECUTED: {sell_trade.trade_id}|{buy_trade.trade_id}")
        return True
    
    def execute_iron_condor(self, market_data: MarketData, qty: int,
                           entry_timestamp: Optional[datetime] = None) -> bool:
        """
        Iron Condor (Neutral Strategy with Defined Risk)
        
        Strategy: Sell both call and put spreads
        - Call spread: Sell call, buy higher call
        - Put spread: Sell put, buy lower put
        - Max profit: Net credit from both spreads
        - Max loss: Larger of (call width - call credit) or (put width - put credit)
        - Best in: Range-bound markets, elevated IV
        
        Example:
        - Spot: 25,000
        - Sell 25,300 CE @ 60, Buy 25,500 CE @ 30 → Credit 30
        - Sell 24,700 PE @ 60, Buy 24,500 PE @ 30 → Credit 30
        - Total credit: 60
        - Max risk: 200 - 30 = 170 (on either side)
        """
        spot = market_data.nifty_spot
        vix = market_data.india_vix
        
        logging.info(f"EXECUTING IRON CONDOR: Spot={spot:.2f}, VIX={vix:.2f}")
        
        # Get expiry and DTE
        expiry, dte = self._get_expiry_and_dte(entry_timestamp)
        
        if dte > Config.MAX_DTE_TO_ENTER or dte < Config.MIN_DTE_TO_HOLD:
            logging.warning(f"DTE {dte} out of range")
            return False
        
        atm = round(spot / 50) * 50
        spread_width = 200
        
        # Call spread (above spot)
        sell_call_strike = atm + 300
        buy_call_strike = sell_call_strike + spread_width
        
        # Put spread (below spot)
        sell_put_strike = atm - 300
        buy_put_strike = sell_put_strike - spread_width
        
        # Get symbols
        sell_call_symbol = Utils.prepare_option_symbol(sell_call_strike, "CE", expiry)
        buy_call_symbol = Utils.prepare_option_symbol(buy_call_strike, "CE", expiry)
        sell_put_symbol = Utils.prepare_option_symbol(sell_put_strike, "PE", expiry)
        buy_put_symbol = Utils.prepare_option_symbol(buy_put_strike, "PE", expiry)
        
        # Get prices
        sell_call_price = self.broker.get_quote(sell_call_symbol)
        buy_call_price = self.broker.get_quote(buy_call_symbol)
        sell_put_price = self.broker.get_quote(sell_put_symbol)
        buy_put_price = self.broker.get_quote(buy_put_symbol)
        
        # Validate all prices
        if any(p <= 0 for p in [sell_call_price, buy_call_price, sell_put_price, buy_put_price]):
            logging.error(f"Invalid prices for iron condor: CE_sell={sell_call_price}, CE_buy={buy_call_price}, PE_sell={sell_put_price}, PE_buy={buy_put_price}")
            return False
        
        call_credit = sell_call_price - buy_call_price
        put_credit = sell_put_price - buy_put_price
        total_credit = call_credit + put_credit
        
        # Validate
        if total_credit < 50:
            logging.warning(f"Total credit too low: {total_credit:.2f}")
            return False
        
        if call_credit < 20 or put_credit < 20:
            logging.warning(f"Individual spread credit too low: CE={call_credit:.2f}, PE={put_credit:.2f}")
            return False
        
        max_risk = spread_width - max(call_credit, put_credit)
        
        # Calculate deltas for all legs
        sell_call_delta = self.greeks_calc.calculate_delta(spot, sell_call_strike, dte, vix, "CE")
        buy_call_delta = self.greeks_calc.calculate_delta(spot, buy_call_strike, dte, vix, "CE")
        sell_put_delta = abs(self.greeks_calc.calculate_delta(spot, sell_put_strike, dte, vix, "PE"))
        buy_put_delta = abs(self.greeks_calc.calculate_delta(spot, buy_put_strike, dte, vix, "PE"))
        
        logging.info(
            f"IRON CONDOR SETUP:\n"
            f"  Call Spread: Sell {sell_call_strike} (Δ={sell_call_delta:.1f}) @ {sell_call_price:.2f}\n"
            f"               Buy {buy_call_strike} (Δ={buy_call_delta:.1f}) @ {buy_call_price:.2f}\n"
            f"               Credit: {call_credit:.2f}\n"
            f"  Put Spread:  Sell {sell_put_strike} (Δ={sell_put_delta:.1f}) @ {sell_put_price:.2f}\n"
            f"               Buy {buy_put_strike} (Δ={buy_put_delta:.1f}) @ {buy_put_price:.2f}\n"
            f"               Credit: {put_credit:.2f}\n"
            f"  Total Credit: {total_credit:.2f}\n"
            f"  Max Risk: {max_risk:.2f}\n"
            f"  Risk/Reward: {max_risk/total_credit:.2f}:1"
        )
        
        # Execute all four legs
        lot_size = self.broker.get_lot_size("NIFTY")
        ts = entry_timestamp or datetime.now()
        
        sell_call_id = self.broker.place_order(sell_call_symbol, qty, Direction.SELL, sell_call_price)
        buy_call_id = self.broker.place_order(buy_call_symbol, qty, Direction.BUY, buy_call_price)
        sell_put_id = self.broker.place_order(sell_put_symbol, qty, Direction.SELL, sell_put_price)
        buy_put_id = self.broker.place_order(buy_put_symbol, qty, Direction.BUY, buy_put_price)
        
        if not all([sell_call_id, buy_call_id, sell_put_id, buy_put_id]):
            logging.error("Failed to execute iron condor - one or more orders failed")
            return False
        
        # Create trades for all four legs
        sell_call_trade = Trade(sell_call_id, sell_call_symbol, qty, Direction.SELL, sell_call_price,
                                ts, "CE", lot_size, sell_call_strike, expiry, spot)
        buy_call_trade = Trade(buy_call_id, buy_call_symbol, qty, Direction.BUY, buy_call_price,
                               ts, "CE", lot_size, buy_call_strike, expiry, spot)
        sell_put_trade = Trade(sell_put_id, sell_put_symbol, qty, Direction.SELL, sell_put_price,
                               ts, "PE", lot_size, sell_put_strike, expiry, spot)
        buy_put_trade = Trade(buy_put_id, buy_put_symbol, qty, Direction.BUY, buy_put_price,
                              ts, "PE", lot_size, buy_put_strike, expiry, spot)
        
        # Update greeks for all trades
        sell_call_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_call_strike, dte, vix, "CE")
        buy_call_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_call_strike, dte, vix, "CE")
        sell_put_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_put_strike, dte, vix, "PE")
        buy_put_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_put_strike, dte, vix, "PE")
        
        sell_call_trade.update_price(sell_call_price, sell_call_greeks)
        buy_call_trade.update_price(buy_call_price, buy_call_greeks)
        sell_put_trade.update_price(sell_put_price, sell_put_greeks)
        buy_put_trade.update_price(buy_put_price, buy_put_greeks)
        
        # Add all trades to manager
        self.trade_manager.add_trade(sell_call_trade)
        self.trade_manager.add_trade(buy_call_trade)
        self.trade_manager.add_trade(sell_put_trade)
        self.trade_manager.add_trade(buy_put_trade)
        
        # Register as two pairs (call spread + put spread)
        self.trade_manager.add_trade_pair(
            sell_call_trade.trade_id,
            buy_call_trade.trade_id,
            call_credit,
            ts,
            qty,
            profit_target=call_credit * 0.5,
            stop_loss=spread_width - call_credit
        )
        
        self.trade_manager.add_trade_pair(
            sell_put_trade.trade_id,
            buy_put_trade.trade_id,
            put_credit,
            ts,
            qty,
            profit_target=put_credit * 0.5,
            stop_loss=spread_width - put_credit
        )
        
        logging.info(
            f"IRON CONDOR EXECUTED: "
            f"Call spread {sell_call_trade.trade_id}|{buy_call_trade.trade_id}, "
            f"Put spread {sell_put_trade.trade_id}|{buy_put_trade.trade_id}"
        )
        return True
