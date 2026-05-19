"""Side-by-side comparison of pricing methods.

This module runs multiple pricing approaches against the same portfolio
and market data, then collects the results into a structured comparison
that highlights differences in valuation, risk metrics, and dispatch
behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingMethod, PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant


@dataclass(frozen=True)
class ComparisonResult:
    """Collected outputs from running multiple pricing methods."""

    portfolio_name: str
    num_scenarios: int
    results: dict[str, PricingResult]

    @property
    def method_names(self) -> list[str]:
        return list(self.results.keys())

    def summary_table(self) -> list[dict[str, Any]]:
        """Return a list of dicts suitable for tabular display."""
        rows = []
        for name, res in self.results.items():
            rows.append({
                "method": name,
                "expected_value_eur": round(res.expected_value_eur, 2),
                "CaR_eur": round(res.cashflow_at_risk_eur, 2),
                "CVaR_eur": round(res.conditional_value_at_risk_eur, 2),
                "risk_adj_eur": round(res.risk_adjusted_value_eur, 2),
                "num_scenarios": res.num_scenarios,
            })
        return rows

    def to_dict(self, include_timeseries: bool = False) -> dict[str, Any]:
        return {
            "portfolio_name": self.portfolio_name,
            "num_base_scenarios": self.num_scenarios,
            "methods": {
                name: res.to_dict(include_timeseries=include_timeseries)
                for name, res in self.results.items()
            },
            "summary": self.summary_table(),
        }


def compare_methods(
    portfolio: VirtualPowerPlant,
    markets: list[MarketData],
    methods: list[PricingMethod],
    *,
    risk_aversion: float = 0.0,
    alpha: float = 0.05,
) -> ComparisonResult:
    """Run each method against the same inputs and collect results."""
    results: dict[str, PricingResult] = {}
    for method in methods:
        results[method.name] = method.price(
            portfolio, markets, risk_aversion=risk_aversion, alpha=alpha
        )

    return ComparisonResult(
        portfolio_name=portfolio.name,
        num_scenarios=len(markets),
        results=results,
    )
