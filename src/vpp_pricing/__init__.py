"""VPP Pricing Research Toolkit.

A framework for modelling Virtual Power Plants and comparing pricing
methodologies: intrinsic value, rolling intrinsic, and Monte-Carlo
extrinsic valuation, plus GAN-based scenario generation.
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
from vpp_pricing.market import MarketData, load_market_csv, validate_market_scenarios
from vpp_pricing.methods import (
    GANPricing,
    IntrinsicPricing,
    MonteCarloPricing,
    PricingMethod,
    PricingResult,
    RollingIntrinsicPricing,
    get_method,
)
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.pricing import PriceQuote, price_portfolio
from vpp_pricing.practical import (
    PracticalPricingApproach,
    approach_for_method,
    get_practical_approach,
    list_practical_approaches,
)
from vpp_pricing.risk import (
    CashflowRiskMetrics,
    cashflow_risk_metrics,
    effective_sample_size,
    lower_tail_support,
)
from vpp_pricing.validation import (
    ValidationIssue,
    ValidationReport,
    validate_portfolio_and_markets,
)

__all__ = [
    "BatteryStorage",
    "CashflowRiskMetrics",
    "ComparisonResult",
    "DispatchableGenerator",
    "FixedLoad",
    "FlexibleLoad",
    "GANPricing",
    "IntrinsicPricing",
    "MarketData",
    "MonteCarloPricing",
    "PriceQuote",
    "PracticalPricingApproach",
    "PricingMethod",
    "PricingResult",
    "RenewableAsset",
    "RollingIntrinsicPricing",
    "VirtualPowerPlant",
    "ValidationIssue",
    "ValidationReport",
    "compare_methods",
    "create_asset",
    "cashflow_risk_metrics",
    "effective_sample_size",
    "approach_for_method",
    "get_method",
    "get_practical_approach",
    "list_practical_approaches",
    "load_market_csv",
    "lower_tail_support",
    "price_portfolio",
    "validate_portfolio_and_markets",
    "validate_market_scenarios",
]

__version__ = "0.4.0"
