"""Protocol and result types for pricing methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from vpp_pricing.market import MarketData
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import PortfolioDispatch


@dataclass(frozen=True)
class PricingResult:
    """Unified output of any pricing method."""

    method_name: str
    portfolio_name: str
    expected_value_eur: float
    cashflow_at_risk_eur: float
    conditional_value_at_risk_eur: float
    risk_adjusted_value_eur: float
    scenario_results: tuple[PortfolioDispatch, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def num_scenarios(self) -> int:
        return len(self.scenario_results)

    def to_dict(self, include_timeseries: bool = True) -> dict[str, Any]:
        return {
            "method": self.method_name,
            "portfolio_name": self.portfolio_name,
            "expected_value_eur": round(self.expected_value_eur, 2),
            "cashflow_at_risk_eur": round(self.cashflow_at_risk_eur, 2),
            "conditional_value_at_risk_eur": round(self.conditional_value_at_risk_eur, 2),
            "risk_adjusted_value_eur": round(self.risk_adjusted_value_eur, 2),
            "parameters": self.parameters,
            "diagnostics": self.diagnostics,
            "num_scenarios": self.num_scenarios,
            "scenarios": [
                s.to_dict(include_timeseries=include_timeseries)
                for s in self.scenario_results
            ],
        }


class PricingMethod(Protocol):
    """Interface that every pricing approach must implement."""

    @property
    def name(self) -> str:
        """Short identifier, e.g. 'intrinsic', 'rolling_intrinsic', 'monte_carlo'."""
        ...

    def price(
        self,
        portfolio: VirtualPowerPlant,
        markets: list[MarketData],
        *,
        risk_aversion: float = 0.0,
        alpha: float = 0.05,
    ) -> PricingResult:
        """Run the pricing method and return a unified result."""
        ...
