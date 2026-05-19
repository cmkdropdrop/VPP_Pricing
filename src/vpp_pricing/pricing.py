"""High-level pricing API -- backwards-compatible wrapper around methods.

The original ``price_portfolio`` function is preserved for callers that
don't need to choose a method explicitly.  Internally it delegates to
:class:`IntrinsicPricing`.

For research use, prefer ``vpp_pricing.methods`` and
``vpp_pricing.comparison`` directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import PortfolioDispatch


@dataclass(frozen=True)
class PriceQuote:
    """Legacy result type -- wraps a PricingResult for backward compat."""

    portfolio_name: str
    expected_cashflow_eur: float
    cashflow_at_risk_eur: float
    conditional_value_at_risk_eur: float
    risk_adjusted_value_eur: float
    risk_aversion: float
    alpha: float
    scenario_results: tuple[PortfolioDispatch, ...]

    def to_dict(self, include_timeseries: bool = True) -> dict[str, Any]:
        return {
            "portfolio_name": self.portfolio_name,
            "expected_cashflow_eur": round(self.expected_cashflow_eur, 6),
            "cashflow_at_risk_eur": round(self.cashflow_at_risk_eur, 6),
            "conditional_value_at_risk_eur": round(
                self.conditional_value_at_risk_eur, 6
            ),
            "risk_adjusted_value_eur": round(self.risk_adjusted_value_eur, 6),
            "risk_aversion": self.risk_aversion,
            "alpha": self.alpha,
            "scenarios": [
                result.to_dict(include_timeseries=include_timeseries)
                for result in self.scenario_results
            ],
        }


def price_portfolio(
    portfolio: VirtualPowerPlant,
    markets: Iterable[MarketData],
    *,
    risk_aversion: float = 0.0,
    alpha: float = 0.05,
) -> PriceQuote:
    """Run intrinsic pricing and return a legacy PriceQuote.

    This preserves the original API.  For multi-method comparisons use
    :func:`vpp_pricing.comparison.compare_methods`.
    """
    market_list = list(markets)
    result = IntrinsicPricing().price(
        portfolio, market_list, risk_aversion=risk_aversion, alpha=alpha
    )
    return PriceQuote(
        portfolio_name=result.portfolio_name,
        expected_cashflow_eur=result.expected_value_eur,
        cashflow_at_risk_eur=result.cashflow_at_risk_eur,
        conditional_value_at_risk_eur=result.conditional_value_at_risk_eur,
        risk_adjusted_value_eur=result.risk_adjusted_value_eur,
        risk_aversion=risk_aversion,
        alpha=alpha,
        scenario_results=result.scenario_results,
    )
