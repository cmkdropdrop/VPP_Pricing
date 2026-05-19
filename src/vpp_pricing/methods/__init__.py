"""Pricing methods for VPP valuation research."""

from vpp_pricing.methods.base import PricingMethod, PricingResult
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.methods.rolling_intrinsic import RollingIntrinsicPricing
from vpp_pricing.methods.monte_carlo import MonteCarloPricing

__all__ = [
    "PricingMethod",
    "PricingResult",
    "IntrinsicPricing",
    "MonteCarloPricing",
    "RollingIntrinsicPricing",
]

REGISTRY: dict[str, type[PricingMethod]] = {
    "intrinsic": IntrinsicPricing,
    "rolling_intrinsic": RollingIntrinsicPricing,
    "monte_carlo": MonteCarloPricing,
}


def get_method(name: str, **kwargs) -> PricingMethod:
    """Instantiate a pricing method by name."""
    if name not in REGISTRY:
        raise ValueError(
            f"Unknown pricing method {name!r}. "
            f"Available: {sorted(REGISTRY)}"
        )
    return REGISTRY[name](**kwargs)
