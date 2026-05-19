from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from vpp_pricing.market import MarketData
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import PortfolioDispatch


@dataclass(frozen=True)
class PriceQuote:
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
    if risk_aversion < 0:
        raise ValueError("risk_aversion must not be negative")
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")

    market_list = list(markets)
    scenario_results = tuple(portfolio.dispatch(market) for market in market_list)
    if not scenario_results:
        raise ValueError("at least one market scenario is required")

    probabilities = _normalized_probabilities([m.probability for m in market_list])

    cashflows = [result.total_cashflow_eur for result in scenario_results]
    expected = sum(p * value for p, value in zip(probabilities, cashflows))
    car = _weighted_quantile(cashflows, probabilities, alpha)
    cvar = _weighted_cvar(cashflows, probabilities, alpha)
    downside = max(0.0, expected - cvar)
    risk_adjusted = expected - risk_aversion * downside

    return PriceQuote(
        portfolio_name=portfolio.name,
        expected_cashflow_eur=expected,
        cashflow_at_risk_eur=car,
        conditional_value_at_risk_eur=cvar,
        risk_adjusted_value_eur=risk_adjusted,
        risk_aversion=risk_aversion,
        alpha=alpha,
        scenario_results=scenario_results,
    )


def _normalized_probabilities(probabilities: list[float | None]) -> list[float]:
    numeric = [float(p) if p is not None else 0.0 for p in probabilities]
    total = sum(numeric)
    if total <= 0:
        return [1.0 / len(numeric) for _ in numeric]
    return [p / total for p in numeric]


def _weighted_quantile(values: list[float], probabilities: list[float], alpha: float) -> float:
    ordered = sorted(zip(values, probabilities), key=lambda item: item[0])
    cumulative = 0.0
    for value, probability in ordered:
        cumulative += probability
        if cumulative >= alpha:
            return value
    return ordered[-1][0]


def _weighted_cvar(values: list[float], probabilities: list[float], alpha: float) -> float:
    ordered = sorted(zip(values, probabilities), key=lambda item: item[0])
    remaining = alpha
    weighted_sum = 0.0
    used_probability = 0.0
    for value, probability in ordered:
        take = min(probability, remaining)
        if take <= 0:
            break
        weighted_sum += value * take
        used_probability += take
        remaining -= take
    if used_probability <= 0:
        return ordered[0][0]
    return weighted_sum / used_probability
