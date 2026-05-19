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

from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import PortfolioDispatch


def _normalized_probabilities(probs: list[float]) -> list[float]:
    total = sum(probs)
    if total <= 0:
        return [1.0 / len(probs)] * len(probs)
    return [p / total for p in probs]


def _weighted_quantile(
    values: list[float], probs: list[float], alpha: float
) -> float:
    ordered = sorted(zip(values, probs), key=lambda x: x[0])
    cumulative = 0.0
    for value, prob in ordered:
        cumulative += prob
        if cumulative >= alpha:
            return value
    return ordered[-1][0]


def _weighted_cvar(
    values: list[float], probs: list[float], alpha: float
) -> float:
    ordered = sorted(zip(values, probs), key=lambda x: x[0])
    remaining = alpha
    weighted_sum = 0.0
    used = 0.0
    for value, prob in ordered:
        take = min(prob, remaining)
        if take <= 0:
            break
        weighted_sum += value * take
        used += take
        remaining -= take
    return weighted_sum / used if used > 0 else ordered[0][0]


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
        probs = _normalized_probabilities([m.probability for m in markets])
        cashflows = [r.total_cashflow_eur for r in scenario_results]

        expected = sum(p * v for p, v in zip(probs, cashflows))
        car = _weighted_quantile(cashflows, probs, alpha)
        cvar = _weighted_cvar(cashflows, probs, alpha)
        downside = max(0.0, expected - cvar)
        risk_adj = expected - risk_aversion * downside

        return PricingResult(
            method_name=self.name,
            portfolio_name=portfolio.name,
            expected_value_eur=expected,
            cashflow_at_risk_eur=car,
            conditional_value_at_risk_eur=cvar,
            risk_adjusted_value_eur=risk_adj,
            scenario_results=scenario_results,
            parameters={
                "risk_aversion": risk_aversion,
                "alpha": alpha,
            },
            diagnostics={
                "num_scenarios": len(markets),
                "scenario_cashflows_eur": [round(c, 2) for c in cashflows],
            },
        )
