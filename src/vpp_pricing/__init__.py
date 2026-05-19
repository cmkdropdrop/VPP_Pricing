"""VPP Pricing Research Toolkit.

A framework for modelling Virtual Power Plants and comparing pricing
methodologies: intrinsic value, rolling intrinsic, and Monte-Carlo
extrinsic valuation.
"""

from vpp_pricing.assets import (
    BatteryStorage,
    DispatchableGenerator,
    FixedLoad,
    FlexibleLoad,
    RenewableAsset,
    create_asset,
)
from vpp_pricing.comparison import ComparisonResult, compare_methods
from vpp_pricing.market import MarketData, load_market_csv
from vpp_pricing.methods import (
    IntrinsicPricing,
    MonteCarloPricing,
    PricingMethod,
    PricingResult,
    RollingIntrinsicPricing,
    get_method,
)
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.pricing import PriceQuote, price_portfolio

__all__ = [
    "BatteryStorage",
    "ComparisonResult",
    "DispatchableGenerator",
    "FixedLoad",
    "FlexibleLoad",
    "IntrinsicPricing",
    "MarketData",
    "MonteCarloPricing",
    "PriceQuote",
    "PricingMethod",
    "PricingResult",
    "RenewableAsset",
    "RollingIntrinsicPricing",
    "VirtualPowerPlant",
    "compare_methods",
    "create_asset",
    "get_method",
    "load_market_csv",
    "price_portfolio",
]

__version__ = "0.2.0"
