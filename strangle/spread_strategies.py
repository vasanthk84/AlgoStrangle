"""
Vertical Spread Strategy Implementations - PRODUCTION READY
✅ Live symbol generation using broker API
✅ Proper error handling for symbol lookup failures
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
    Implements vertical spread strategies with live symbol support
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

    def _get_live_symbol_and_price(self, strike: float, option_type: str,
                                   expiry: date) -> Optional[Tuple[str, float]]:
        """
        Helper to get live symbol and price
        Returns: (symbol, price) or None
        """
        if self.broker.backtest_data is not None:
            # Backtest mode
            symbol = Utils.prepare_option_symbol(strike, option_type, expiry)
            price = self.broker.get_quote(symbol)
            return (symbol, price)

        # Live mode
        instrument = self.broker.find_live_option_symbol(strike, option_type, expiry)
        if instrument is None:
            logging.error(f"Failed to find live symbol: {strike} {option_type} {expiry}")
            return None

        symbol = f"NFO:{instrument['tradingsymbol']}"
        price = self.broker.get_quote(symbol)

        if price <= 0:
            logging.error(f"Invalid price for {symbol}: {price}")
            return None

        # Subscribe for updates
        self.broker.subscribe_instruments([instrument['instrument_token']])

        return (symbol, price)

    def execute_short_put_spread(self, market_data: MarketData, qty: int,
                                 entry_timestamp: Optional[datetime] = None) -> bool:
        """
        Short Put Vertical Spread (Bullish Income) - PRODUCTION READY
        """
        spot = market_data.nifty_spot
        vix = market_data.india_vix

        logging.info(f"EXECUTING SHORT PUT SPREAD: Spot={spot:.2f}, VIX={vix:.2f}")

        expiry, dte = self._get_expiry_and_dte(entry_timestamp)

        if dte > Config.MAX_DTE_TO_ENTER or dte < Config.MIN_DTE_TO_HOLD:
            logging.warning(f"DTE {dte} out of range")
            return False

        atm = round(spot / 50) * 50
        sell_distance = 300
        sell_strike = atm - sell_distance
        spread_width = 200
        buy_strike = sell_strike - spread_width

        # 🆕 Get live symbols and prices
        sell_info = self._get_live_symbol_and_price(sell_strike, "PE", expiry)
        if sell_info is None:
            logging.error("Failed to get sell PE symbol/price")
            return False

        buy_info = self._get_live_symbol_and_price(buy_strike, "PE", expiry)
        if buy_info is None:
            logging.error("Failed to get buy PE symbol/price")
            return False

        sell_symbol, sell_price = sell_info
        buy_symbol, buy_price = buy_info

        net_credit = sell_price - buy_price

        # Validate spread quality
        if net_credit < 30:
            logging.warning(f"Net credit too low: {net_credit:.2f}")
            return False

        if net_credit > spread_width * 0.6:
            logging.warning(f"Credit too high: {net_credit:.2f}/{spread_width}")
            return False

        sell_delta = abs(self.greeks_calc.calculate_delta(spot, sell_strike, dte, vix, "PE"))
        buy_delta = abs(self.greeks_calc.calculate_delta(spot, buy_strike, dte, vix, "PE"))

        logging.info(
            f"PUT SPREAD: Sell {sell_strike}@{sell_price:.2f} (Δ={sell_delta:.1f}), "
            f"Buy {buy_strike}@{buy_price:.2f} (Δ={buy_delta:.1f}), "
            f"Credit={net_credit:.2f}"
        )

        # Execute orders
        lot_size = self.broker.get_lot_size("NIFTY")
        ts = entry_timestamp or datetime.now()

        sell_order_id = self.broker.place_order(sell_symbol, qty, Direction.SELL, sell_price)
        buy_order_id = self.broker.place_order(buy_symbol, qty, Direction.BUY, buy_price)

        if not sell_order_id or not buy_order_id:
            logging.error("Failed to execute spread orders")
            return False

        # Create trades
        sell_trade = Trade(sell_order_id, sell_symbol, qty, Direction.SELL, sell_price,
                          ts, "PE", lot_size, sell_strike, expiry, spot)
        buy_trade = Trade(buy_order_id, buy_symbol, qty, Direction.BUY, buy_price,
                         ts, "PE", lot_size, buy_strike, expiry, spot)

        sell_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_strike, dte, vix, "PE")
        buy_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_strike, dte, vix, "PE")
        sell_trade.update_price(sell_price, sell_greeks)
        buy_trade.update_price(buy_price, buy_greeks)

        self.trade_manager.add_trade(sell_trade)
        self.trade_manager.add_trade(buy_trade)

        self.trade_manager.add_trade_pair(
            sell_trade.trade_id,
            buy_trade.trade_id,
            net_credit,
            ts,
            qty,
            profit_target=net_credit * 0.5,
            stop_loss=spread_width - net_credit
        )

        logging.info(f"✓ SHORT PUT SPREAD EXECUTED: {sell_trade.trade_id}|{buy_trade.trade_id}")
        return True

    def execute_short_call_spread(self, market_data: MarketData, qty: int,
                                  entry_timestamp: Optional[datetime] = None) -> bool:
        """
        Short Call Vertical Spread (Bearish Income) - PRODUCTION READY
        """
        spot = market_data.nifty_spot
        vix = market_data.india_vix

        logging.info(f"EXECUTING SHORT CALL SPREAD: Spot={spot:.2f}, VIX={vix:.2f}")

        expiry, dte = self._get_expiry_and_dte(entry_timestamp)

        if dte > Config.MAX_DTE_TO_ENTER or dte < Config.MIN_DTE_TO_HOLD:
            logging.warning(f"DTE {dte} out of range")
            return False

        atm = round(spot / 50) * 50
        sell_distance = 300
        sell_strike = atm + sell_distance
        spread_width = 200
        buy_strike = sell_strike + spread_width

        # 🆕 Get live symbols and prices
        sell_info = self._get_live_symbol_and_price(sell_strike, "CE", expiry)
        if sell_info is None:
            logging.error("Failed to get sell CE symbol/price")
            return False

        buy_info = self._get_live_symbol_and_price(buy_strike, "CE", expiry)
        if buy_info is None:
            logging.error("Failed to get buy CE symbol/price")
            return False

        sell_symbol, sell_price = sell_info
        buy_symbol, buy_price = buy_info

        net_credit = sell_price - buy_price

        if net_credit < 30:
            logging.warning(f"Net credit too low: {net_credit:.2f}")
            return False

        if net_credit > spread_width * 0.6:
            logging.warning(f"Credit too high: {net_credit:.2f}/{spread_width}")
            return False

        sell_delta = self.greeks_calc.calculate_delta(spot, sell_strike, dte, vix, "CE")
        buy_delta = self.greeks_calc.calculate_delta(spot, buy_strike, dte, vix, "CE")

        logging.info(
            f"CALL SPREAD: Sell {sell_strike}@{sell_price:.2f} (Δ={sell_delta:.1f}), "
            f"Buy {buy_strike}@{buy_price:.2f} (Δ={buy_delta:.1f}), "
            f"Credit={net_credit:.2f}"
        )

        lot_size = self.broker.get_lot_size("NIFTY")
        ts = entry_timestamp or datetime.now()

        sell_order_id = self.broker.place_order(sell_symbol, qty, Direction.SELL, sell_price)
        buy_order_id = self.broker.place_order(buy_symbol, qty, Direction.BUY, buy_price)

        if not sell_order_id or not buy_order_id:
            logging.error("Failed to execute spread orders")
            return False

        sell_trade = Trade(sell_order_id, sell_symbol, qty, Direction.SELL, sell_price,
                          ts, "CE", lot_size, sell_strike, expiry, spot)
        buy_trade = Trade(buy_order_id, buy_symbol, qty, Direction.BUY, buy_price,
                         ts, "CE", lot_size, buy_strike, expiry, spot)

        sell_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_strike, dte, vix, "CE")
        buy_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_strike, dte, vix, "CE")
        sell_trade.update_price(sell_price, sell_greeks)
        buy_trade.update_price(buy_price, buy_greeks)

        self.trade_manager.add_trade(sell_trade)
        self.trade_manager.add_trade(buy_trade)

        self.trade_manager.add_trade_pair(
            sell_trade.trade_id,
            buy_trade.trade_id,
            net_credit,
            ts,
            qty,
            profit_target=net_credit * 0.5,
            stop_loss=spread_width - net_credit
        )

        logging.info(f"✓ SHORT CALL SPREAD EXECUTED: {sell_trade.trade_id}|{buy_trade.trade_id}")
        return True

    def execute_iron_condor(self, market_data: MarketData, qty: int,
                           entry_timestamp: Optional[datetime] = None) -> bool:
        """
        Iron Condor (Neutral, Defined Risk) - PRODUCTION READY
        """
        spot = market_data.nifty_spot
        vix = market_data.india_vix

        logging.info(f"EXECUTING IRON CONDOR: Spot={spot:.2f}, VIX={vix:.2f}")

        expiry, dte = self._get_expiry_and_dte(entry_timestamp)

        if dte > Config.MAX_DTE_TO_ENTER or dte < Config.MIN_DTE_TO_HOLD:
            logging.warning(f"DTE {dte} out of range")
            return False

        atm = round(spot / 50) * 50
        spread_width = 200

        sell_call_strike = atm + 300
        buy_call_strike = sell_call_strike + spread_width
        sell_put_strike = atm - 300
        buy_put_strike = sell_put_strike - spread_width

        # 🆕 Get all four symbols and prices
        sell_call_info = self._get_live_symbol_and_price(sell_call_strike, "CE", expiry)
        if sell_call_info is None:
            return False

        buy_call_info = self._get_live_symbol_and_price(buy_call_strike, "CE", expiry)
        if buy_call_info is None:
            return False

        sell_put_info = self._get_live_symbol_and_price(sell_put_strike, "PE", expiry)
        if sell_put_info is None:
            return False

        buy_put_info = self._get_live_symbol_and_price(buy_put_strike, "PE", expiry)
        if buy_put_info is None:
            return False

        sell_call_symbol, sell_call_price = sell_call_info
        buy_call_symbol, buy_call_price = buy_call_info
        sell_put_symbol, sell_put_price = sell_put_info
        buy_put_symbol, buy_put_price = buy_put_info

        call_credit = sell_call_price - buy_call_price
        put_credit = sell_put_price - buy_put_price
        total_credit = call_credit + put_credit

        if total_credit < 50:
            logging.warning(f"Total credit too low: {total_credit:.2f}")
            return False

        if call_credit < 20 or put_credit < 20:
            logging.warning(f"Individual credit too low: CE={call_credit:.2f}, PE={put_credit:.2f}")
            return False

        logging.info(
            f"IRON CONDOR: Call Spread Credit={call_credit:.2f}, "
            f"Put Spread Credit={put_credit:.2f}, Total={total_credit:.2f}"
        )

        lot_size = self.broker.get_lot_size("NIFTY")
        ts = entry_timestamp or datetime.now()

        # Execute all four orders
        sell_call_id = self.broker.place_order(sell_call_symbol, qty, Direction.SELL, sell_call_price)
        buy_call_id = self.broker.place_order(buy_call_symbol, qty, Direction.BUY, buy_call_price)
        sell_put_id = self.broker.place_order(sell_put_symbol, qty, Direction.SELL, sell_put_price)
        buy_put_id = self.broker.place_order(buy_put_symbol, qty, Direction.BUY, buy_put_price)

        if not all([sell_call_id, buy_call_id, sell_put_id, buy_put_id]):
            logging.error("Failed to execute iron condor orders")
            return False

        # Create all trades
        sell_call_trade = Trade(sell_call_id, sell_call_symbol, qty, Direction.SELL, sell_call_price,
                                ts, "CE", lot_size, sell_call_strike, expiry, spot)
        buy_call_trade = Trade(buy_call_id, buy_call_symbol, qty, Direction.BUY, buy_call_price,
                               ts, "CE", lot_size, buy_call_strike, expiry, spot)
        sell_put_trade = Trade(sell_put_id, sell_put_symbol, qty, Direction.SELL, sell_put_price,
                               ts, "PE", lot_size, sell_put_strike, expiry, spot)
        buy_put_trade = Trade(buy_put_id, buy_put_symbol, qty, Direction.BUY, buy_put_price,
                              ts, "PE", lot_size, buy_put_strike, expiry, spot)

        # Update greeks
        sell_call_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_call_strike, dte, vix, "CE")
        buy_call_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_call_strike, dte, vix, "CE")
        sell_put_greeks = self.greeks_calc.calculate_all_greeks(spot, sell_put_strike, dte, vix, "PE")
        buy_put_greeks = self.greeks_calc.calculate_all_greeks(spot, buy_put_strike, dte, vix, "PE")

        sell_call_trade.update_price(sell_call_price, sell_call_greeks)
        buy_call_trade.update_price(buy_call_price, buy_call_greeks)
        sell_put_trade.update_price(sell_put_price, sell_put_greeks)
        buy_put_trade.update_price(buy_put_price, buy_put_greeks)

        # Add all trades
        self.trade_manager.add_trade(sell_call_trade)
        self.trade_manager.add_trade(buy_call_trade)
        self.trade_manager.add_trade(sell_put_trade)
        self.trade_manager.add_trade(buy_put_trade)

        # Register pairs
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

        logging.info(f"✓ IRON CONDOR EXECUTED")
        return True