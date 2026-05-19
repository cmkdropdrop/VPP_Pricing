"""Intrinsic-value pricing: full-horizon perfect-foresight dispatch.

This is the classic approach -- each asset sees the complete price curve
and optimises its dispatch with full information.  The portfolio value
equals the probability-weighted sum of per-scenario cashflows.

Strengths:
    * Upper bound on achievable value (perfect foresight).
    * Deterministic, fast, reproducible.

Limitations:
    * Overestimates realisable value because real operators never have
      perfect foresight over the full delivery period.
"""

from __future__ import annotations

from dataclasses import dataclass

from vpp_pricing.diagnostics import (
    market_price_diagnostics,
    portfolio_dispatch_diagnostics,
)
from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.risk import (
    cashflow_distribution_diagnostics,
    cashflow_risk_metrics,
    normalized_probabilities,
)


@dataclass
class IntrinsicPricing:
    """Perfect-foresight intrinsic value."""

    @property
    def name(self) -> str:
        return "intrinsic"

    def price(
        self,
        portfolio: VirtualPowerPlant,
        markets: list[MarketData],
        *,
        risk_aversion: float = 0.0,
        alpha: float = 0.05,
    ) -> PricingResult:
        if not markets:
            raise ValueError("at least one market scenario is required")

        scenario_results = tuple(portfolio.dispatch(m) for m in markets)
        probs = normalized_probabilities([m.probability for m in markets], len(markets))
        cashflows = [r.total_cashflow_eur for r in scenario_results]
        metrics = cashflow_risk_metrics(
            cashflows,
            probs,
            risk_aversion=risk_aversion,
            alpha=alpha,
        )

        return PricingResult(
            method_name=self.name,
            portfolio_name=portfolio.name,
            expected_value_eur=metrics.expected_value_eur,
            cashflow_at_risk_eur=metrics.cashflow_at_risk_eur,
            conditional_value_at_risk_eur=metrics.conditional_value_at_risk_eur,
            risk_adjusted_value_eur=metrics.risk_adjusted_value_eur,
            scenario_results=scenario_results,
            parameters={
                "risk_aversion": risk_aversion,
                "alpha": alpha,
            },
            diagnostics={
                "num_scenarios": len(markets),
                "scenario_cashflows_eur": [round(c, 2) for c in cashflows],
                "scenario_probabilities": [round(p, 6) for p in probs],
                **metrics.diagnostics(),
                **cashflow_distribution_diagnostics(cashflows, probs),
                **market_price_diagnostics(markets),
                **portfolio_dispatch_diagnostics(scenario_results, probs),
            },
        )
