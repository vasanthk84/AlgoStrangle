"""
Greeks Calculator using Black-Scholes Model
FIXED: Added get_option_price method
"""

import math
from typing import Tuple
from datetime import datetime, date

try:
    from scipy.stats import norm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("WARNING: scipy not available. Using approximation for norm.cdf")

from .config import Config
from .models import Greeks


class GreeksCalculator:
    """Calculate option Greeks using Black-Scholes model"""

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Cumulative distribution function for standard normal distribution"""
        if SCIPY_AVAILABLE:
            return norm.cdf(x)
        else:
            # Approximation using error function
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Probability density function for standard normal distribution"""
        if SCIPY_AVAILABLE:
            return norm.pdf(x)
        else:
            return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

    @staticmethod
    def calculate_d1_d2(spot: float, strike: float, dte: int,
                       volatility: float, risk_free_rate: float = None) -> Tuple[float, float]:
        """
        Calculate d1 and d2 for Black-Scholes formula
        volatility is expected as a percentage (e.g., 20.0)
        """
        if dte <= 0 or volatility <= 0 or spot <= 0 or strike <= 0:
            return 0.0, 0.0

        if risk_free_rate is None:
            risk_free_rate = Config.RISK_FREE_RATE

        T = dte / 365.0
        sigma = volatility / 100.0  # Convert percentage to decimal

        try:
            d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            return d1, d2
        except (ValueError, ZeroDivisionError):
            return 0.0, 0.0

    # --- NEW: Added Black-Scholes Price Calculation ---
    @staticmethod
    def get_option_price(spot: float, strike: float, dte: int,
                         volatility: float, option_type: str,
                         risk_free_rate: float = None) -> float:
        """
        Calculate option price using Black-Scholes
        volatility is expected as a percentage (e.g., 20.0)
        """
        if risk_free_rate is None:
            risk_free_rate = Config.RISK_FREE_RATE

        d1, d2 = GreeksCalculator.calculate_d1_d2(spot, strike, dte, volatility, risk_free_rate)

        if d1 == 0.0 and d2 == 0.0:
            # Handle edge case where d1/d2 calculation failed
            return 0.0

        T = dte / 365.0

        try:
            if option_type.upper() == "CE":
                price = (spot * GreeksCalculator._norm_cdf(d1) - strike * math.exp(-risk_free_rate * T) * GreeksCalculator._norm_cdf(d2))
            else:  # PE
                price = (strike * math.exp(-risk_free_rate * T) * GreeksCalculator._norm_cdf(-d2) - spot * GreeksCalculator._norm_cdf(-d1))
            return max(0.0, price) # Price cannot be negative
        except (ValueError, OverflowError):
            return 0.0

    @staticmethod
    def calculate_delta(spot: float, strike: float, dte: int,
                       volatility: float, option_type: str) -> float:
        """
        Calculate option delta
        Returns: Delta in range 0-100 for CE, -100-0 for PE
        """
        d1, _ = GreeksCalculator.calculate_d1_d2(spot, strike, dte, volatility)

        if option_type.upper() == "CE":
            delta = GreeksCalculator._norm_cdf(d1) * 100
        else:  # PE
            delta = (GreeksCalculator._norm_cdf(d1) - 1) * 100

        return delta

    @staticmethod
    def calculate_gamma(spot: float, strike: float, dte: int,
                       volatility: float) -> float:
        """Calculate option gamma (same for CE and PE)"""
        d1, _ = GreeksCalculator.calculate_d1_d2(spot, strike, dte, volatility)

        if dte <= 0 or spot <= 0 or volatility <= 0:
            return 0.0

        T = dte / 365.0
        sigma = volatility / 100.0

        try:
            gamma = GreeksCalculator._norm_pdf(d1) / (spot * sigma * math.sqrt(T))
            return gamma
        except (ValueError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def calculate_theta(spot: float, strike: float, dte: int,
                       volatility: float, option_type: str,
                       risk_free_rate: float = None) -> float:
        """
        Calculate option theta (time decay per day)
        Returns: Daily theta (negative for long positions)
        """
        if risk_free_rate is None:
            risk_free_rate = Config.RISK_FREE_RATE

        d1, d2 = GreeksCalculator.calculate_d1_d2(spot, strike, dte, volatility, risk_free_rate)

        if dte <= 0:
            return 0.0

        T = dte / 365.0
        sigma = volatility / 100.0

        try:
            term1 = -(spot * GreeksCalculator._norm_pdf(d1) * sigma) / (2 * math.sqrt(T))

            if option_type.upper() == "CE":
                term2 = -risk_free_rate * strike * math.exp(-risk_free_rate * T) * GreeksCalculator._norm_cdf(d2)
                theta = (term1 + term2) / 365.0  # Daily theta
            else:  # PE
                term2 = risk_free_rate * strike * math.exp(-risk_free_rate * T) * GreeksCalculator._norm_cdf(-d2)
                theta = (term1 + term2) / 365.0  # Daily theta

            return theta
        except (ValueError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def calculate_vega(spot: float, strike: float, dte: int,
                      volatility: float) -> float:
        """Calculate option vega (sensitivity to 1% change in volatility)"""
        d1, _ = GreeksCalculator.calculate_d1_d2(spot, strike, dte, volatility)

        if dte <= 0:
            return 0.0

        T = dte / 365.0

        try:
            vega = spot * GreeksCalculator._norm_pdf(d1) * math.sqrt(T) / 100.0  # Per 1% change in IV
            return vega
        except (ValueError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def calculate_all_greeks(spot: float, strike: float, dte: int,
                            volatility: float, option_type: str) -> Greeks:
        """
        Calculate all Greeks for an option

        Args:
            spot: Current spot price
            strike: Strike price
            dte: Days to expiry
            volatility: Implied volatility (as percentage, e.g., 20 for 20%)
            option_type: "CE" or "PE"

        Returns:
            Greeks object with delta, gamma, theta, vega
        """
        delta = GreeksCalculator.calculate_delta(spot, strike, dte, volatility, option_type)
        gamma = GreeksCalculator.calculate_gamma(spot, strike, dte, volatility)
        theta = GreeksCalculator.calculate_theta(spot, strike, dte, volatility, option_type)
        vega = GreeksCalculator.calculate_vega(spot, strike, dte, volatility)

        return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega)

    @staticmethod
    def get_dte(expiry: date, current_date: date = None) -> int:
        """
        Calculate days to expiry

        Args:
            expiry: Expiry date
            current_date: Current date (default: today)

        Returns:
            Days to expiry (minimum 0)
        """
        if current_date is None:
            current_date = datetime.now().date()

        if isinstance(expiry, datetime):
            expiry = expiry.date()
        if isinstance(current_date, datetime):
            current_date = current_date.date()

        dte = (expiry - current_date).days
        return max(0, dte)