"""Pricing methods for VPP valuation research."""

from vpp_pricing.methods.base import PricingMethod, PricingResult
from vpp_pricing.methods.gan import GANPricing
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.methods.rolling_intrinsic import RollingIntrinsicPricing
from vpp_pricing.methods.monte_carlo import MonteCarloPricing
from vpp_pricing.methods.reinforcement_learning import ReinforcementLearningPricing

__all__ = [
    "GANPricing",
    "PricingMethod",
    "PricingResult",
    "IntrinsicPricing",
    "MonteCarloPricing",
    "ReinforcementLearningPricing",
    "RollingIntrinsicPricing",
]

REGISTRY: dict[str, type[PricingMethod]] = {
    "gan": GANPricing,
    "intrinsic": IntrinsicPricing,
    "rolling_intrinsic": RollingIntrinsicPricing,
    "monte_carlo": MonteCarloPricing,
    "rl": ReinforcementLearningPricing,
}


def get_method(name: str, **kwargs) -> PricingMethod:
    """Instantiate a pricing method by name."""
    if name not in REGISTRY:
        raise ValueError(
            f"Unknown pricing method {name!r}. "
            f"Available: {sorted(REGISTRY)}"
        )
    return REGISTRY[name](**kwargs)
