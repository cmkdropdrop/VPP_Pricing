"""Weighted cashflow distribution metrics for pricing outputs."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Iterable


@dataclass(frozen=True)
class CashflowRiskMetrics:
    expected_value_eur: float
    cashflow_at_risk_eur: float
    conditional_value_at_risk_eur: float
    risk_adjusted_value_eur: float
    standard_deviation_eur: float
    downside_to_cvar_eur: float

    def diagnostics(self) -> dict[str, float]:
        return {
            "cashflow_mean_eur": round(self.expected_value_eur, 2),
            "cashflow_std_eur": round(self.standard_deviation_eur, 2),
            "cashflow_downside_to_cvar_eur": round(self.downside_to_cvar_eur, 2),
        }


def normalized_probabilities(probabilities: Iterable[float], length: int) -> list[float]:
    """Return finite, non-negative probabilities that sum to one."""
    probs = [float(p) for p in probabilities]
    if len(probs) != length:
        raise ValueError(f"got {len(probs)} probabilities for {length} values")
    if length == 0:
        raise ValueError("at least one value is required")
    if any(not isfinite(p) or p < 0 for p in probs):
        raise ValueError("probabilities must be finite and non-negative")

    total = sum(probs)
    if total <= 0:
        return [1.0 / length for _ in range(length)]
    return [p / total for p in probs]


def validate_alpha(alpha: float) -> float:
    alpha = float(alpha)
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    return alpha


def weighted_mean(values: list[float], probabilities: list[float]) -> float:
    return sum(p * v for p, v in zip(probabilities, values))


def weighted_quantile(
    values: list[float], probabilities: list[float], quantile: float
) -> float:
    """Left-continuous weighted empirical quantile."""
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be in [0, 1]")
    ordered = sorted(zip(values, probabilities), key=lambda item: item[0])
    if quantile == 0:
        return ordered[0][0]

    cumulative = 0.0
    for value, probability in ordered:
        cumulative += probability
        if cumulative >= quantile:
            return value
    return ordered[-1][0]


def weighted_lower_cvar(
    values: list[float], probabilities: list[float], alpha: float
) -> float:
    """Expected value of the lower alpha tail with fractional boundary mass."""
    alpha = validate_alpha(alpha)
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

    return weighted_sum / used_probability if used_probability > 0 else ordered[0][0]


def cashflow_risk_metrics(
    cashflows: Iterable[float],
    probabilities: Iterable[float],
    *,
    risk_aversion: float = 0.0,
    alpha: float = 0.05,
) -> CashflowRiskMetrics:
    """Compute comparable risk metrics for a cashflow distribution."""
    values = [float(v) for v in cashflows]
    if not values:
        raise ValueError("at least one cashflow is required")
    if any(not isfinite(v) for v in values):
        raise ValueError("cashflows must be finite")
    if risk_aversion < 0:
        raise ValueError("risk_aversion must not be negative")

    alpha = validate_alpha(alpha)
    probs = normalized_probabilities(probabilities, len(values))
    expected = weighted_mean(values, probs)
    variance = weighted_mean([(v - expected) ** 2 for v in values], probs)
    car = weighted_quantile(values, probs, alpha)
    cvar = weighted_lower_cvar(values, probs, alpha)
    downside = max(0.0, expected - cvar)

    return CashflowRiskMetrics(
        expected_value_eur=expected,
        cashflow_at_risk_eur=car,
        conditional_value_at_risk_eur=cvar,
        risk_adjusted_value_eur=expected - risk_aversion * downside,
        standard_deviation_eur=sqrt(max(0.0, variance)),
        downside_to_cvar_eur=downside,
    )


def cashflow_distribution_diagnostics(
    cashflows: Iterable[float],
    probabilities: Iterable[float],
) -> dict[str, float]:
    """Return weighted distribution diagnostics for method result metadata."""
    values = [float(v) for v in cashflows]
    probs = normalized_probabilities(probabilities, len(values))
    expected = weighted_mean(values, probs)
    variance = weighted_mean([(v - expected) ** 2 for v in values], probs)
    return {
        "cashflow_min_eur": round(min(values), 2),
        "cashflow_p05_eur": round(weighted_quantile(values, probs, 0.05), 2),
        "cashflow_p50_eur": round(weighted_quantile(values, probs, 0.50), 2),
        "cashflow_p95_eur": round(weighted_quantile(values, probs, 0.95), 2),
        "cashflow_max_eur": round(max(values), 2),
        "cashflow_std_eur": round(sqrt(max(0.0, variance)), 2),
    }
