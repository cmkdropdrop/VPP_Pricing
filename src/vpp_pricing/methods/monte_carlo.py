"""Monte-Carlo extrinsic pricing via simulated price paths.

Given one or more base price scenarios, this method generates additional
price paths by adding correlated noise (geometric Brownian motion style
perturbation around the base curve).  The portfolio is dispatched
against each simulated path and the distribution of outcomes is used
to estimate expected value and risk metrics.

This estimates path-dependent optionality and tail risk.  With the default
full-path dispatch policy it is an upper-bound sensitivity, not an executable
trading strategy.

Strengths:
    * Captures optionality sensitivity and tail dispersion.
    * Produces a full distribution of outcomes, not just point estimates.
    * Configurable via number of paths, volatility, and seed.

Limitations:
    * Default dispatch is still perfect-foresight within each simulated path.
    * Price model is simplistic (log-normal perturbation); for production
      use, replace with calibrated stochastic models.
    * Slower than deterministic methods due to many dispatch evaluations.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import ceil, exp, floor, sqrt

from vpp_pricing.diagnostics import (
    market_price_diagnostics,
    portfolio_dispatch_diagnostics,
)
from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.methods.rolling_intrinsic import dispatch_with_rolling_battery_policy
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.risk import (
    cashflow_distribution_diagnostics,
    cashflow_risk_metrics,
    normalized_probabilities,
)


def _simulate_paths(
    base_market: MarketData,
    num_paths: int,
    volatility: float,
    rng: random.Random,
    mean_reversion: float = 0.7,
) -> list[MarketData]:
    """Generate price paths as log-normal perturbations of the base curve.

    The shock process is AR(1): shock_t = rho * shock_{t-1} + eps_t,
    where eps_t ~ N(0, volatility * sqrt(dt)).  The drift correction
    uses the exact variance Var(shock_t) = sigma_eps^2 * (1 - rho^{2t}) / (1 - rho^2)
    so that E[multiplier_t] = 1 for each step (unbiased paths).
    """
    dt = base_market.timestep_hours
    rho = mean_reversion
    sigma_eps_sq = volatility**2 * dt  # Var(innovation)
    # Precompute denominator for AR(1) variance; falls back to step count
    # when rho is effectively zero (independent shocks).
    rho_sq = rho * rho
    ar1_var_denom = 1.0 - rho_sq if abs(rho) < 1.0 - 1e-12 else 0.0
    paths: list[MarketData] = []

    for i in range(num_paths):
        prices: list[float] = []
        cumulative_shock = 0.0
        for step, base_price in enumerate(base_market.prices_eur_per_mwh):
            innovation = rng.gauss(0, volatility * sqrt(dt))
            cumulative_shock = rho * cumulative_shock + innovation

            # Exact AR(1) variance at this step for unbiased drift correction
            if ar1_var_denom > 0:
                shock_var = sigma_eps_sq * (1.0 - rho_sq ** (step + 1)) / ar1_var_denom
            else:
                shock_var = sigma_eps_sq * (step + 1)

            if base_price > 0:
                sim_price = base_price * exp(
                    cumulative_shock - 0.5 * shock_var
                )
            else:
                # Zero and negative prices cannot use a log-normal multiplier.
                # Use an additive, zero-mean shock with a EUR/MWh scale floor so
                # prices around -20 do not lose all simulated dispersion.
                price_scale = max(abs(base_price), 20.0)
                sim_price = base_price + cumulative_shock * price_scale
            prices.append(round(sim_price, 4))

        paths.append(
            MarketData(
                timestamps=base_market.timestamps,
                prices_eur_per_mwh=tuple(prices),
                timestep_hours=base_market.timestep_hours,
                name=f"mc_{base_market.name}_{i:04d}",
                probability=1.0,
            )
        )
    return paths


def _allocate_paths(probabilities: list[float], num_paths: int) -> list[int]:
    """Allocate an exact path count by largest remainder for positive weights."""
    if num_paths <= 0:
        raise ValueError("num_paths must be positive")
    positive_count = sum(1 for probability in probabilities if probability > 0)
    if num_paths < positive_count:
        raise ValueError(
            "num_paths must be at least the number of positive-probability "
            "base scenarios"
        )

    raw_counts = [p * num_paths for p in probabilities]
    counts = [
        max(1, int(floor(raw))) if probability > 0 else 0
        for raw, probability in zip(raw_counts, probabilities)
    ]

    while sum(counts) > num_paths:
        eligible = [idx for idx, count in enumerate(counts) if count > 1]
        if not eligible:
            break
        idx = min(
            eligible,
            key=lambda i: (raw_counts[i] - floor(raw_counts[i]), raw_counts[i]),
        )
        counts[idx] -= 1

    while sum(counts) < num_paths:
        idx = max(
            range(len(counts)),
            key=lambda i: (raw_counts[i] - counts[i], probabilities[i]),
        )
        counts[idx] += 1

    return counts


@dataclass
class MonteCarloPricing:
    """Monte-Carlo simulation over synthetic price paths.

    Parameters
    ----------
    mean_reversion : float
        AR(1) coefficient for the shock process (0 = independent shocks,
        values near 1 = highly persistent shocks).  Controls the
        autocorrelation of simulated price deviations from the base curve.
    """

    num_paths: int = 200
    volatility: float = 0.15
    seed: int | None = 42
    mean_reversion: float = 0.7
    dispatch_window_hours: float | None = None

    @property
    def name(self) -> str:
        return "monte_carlo"

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
        if self.num_paths <= 0:
            raise ValueError("num_paths must be positive")
        if self.volatility < 0:
            raise ValueError("volatility must not be negative")
        if not 0 <= self.mean_reversion < 1:
            raise ValueError("mean_reversion must be in [0, 1)")
        if self.dispatch_window_hours is not None and self.dispatch_window_hours <= 0:
            raise ValueError("dispatch_window_hours must be positive when set")

        rng = random.Random(self.seed)
        base_probs = normalized_probabilities(
            [m.probability for m in markets], len(markets)
        )
        path_counts = _allocate_paths(base_probs, self.num_paths)

        # Generate simulated paths from all base scenarios
        all_paths: list[MarketData] = []
        for base, base_prob, path_count in zip(markets, base_probs, path_counts):
            if path_count == 0:
                continue
            path_probability = base_prob / path_count
            all_paths.extend(
                MarketData(
                    timestamps=path.timestamps,
                    prices_eur_per_mwh=path.prices_eur_per_mwh,
                    timestep_hours=path.timestep_hours,
                    name=path.name,
                    probability=path_probability,
                )
                for path in _simulate_paths(
                    base, path_count, self.volatility, rng, self.mean_reversion
                )
            )

        # Dispatch against every path
        if self.dispatch_window_hours is None:
            results = tuple(portfolio.dispatch(m) for m in all_paths)
            dispatch_policy = "intrinsic_per_path"
            window_by_path: list[int] | None = None
        else:
            window_by_path = [
                max(1, ceil(self.dispatch_window_hours / path.timestep_hours))
                for path in all_paths
            ]
            results = tuple(
                dispatch_with_rolling_battery_policy(portfolio, path, window)
                for path, window in zip(all_paths, window_by_path)
            )
            dispatch_policy = "rolling_intrinsic_per_path"

        cashflows = [r.total_cashflow_eur for r in results]
        probs = normalized_probabilities(
            [m.probability for m in all_paths], len(all_paths)
        )
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
            scenario_results=results,
            parameters={
                "risk_aversion": risk_aversion,
                "alpha": alpha,
                "num_paths": len(all_paths),
                "volatility": self.volatility,
                "mean_reversion": self.mean_reversion,
                "seed": self.seed,
                "dispatch_policy": dispatch_policy,
                "dispatch_window_hours": self.dispatch_window_hours,
            },
            diagnostics={
                "num_paths_total": len(all_paths),
                "dispatch_policy": dispatch_policy,
                "dispatch_window_intervals": (
                    sorted(set(window_by_path)) if window_by_path is not None else None
                ),
                "base_scenario_probabilities": {
                    market.name: round(probability, 6)
                    for market, probability in zip(markets, base_probs)
                },
                "path_count_by_base_scenario": {
                    market.name: count
                    for market, count in zip(markets, path_counts)
                },
                **metrics.diagnostics(),
                **cashflow_distribution_diagnostics(cashflows, probs),
                **market_price_diagnostics(markets, prefix="base_market"),
                **market_price_diagnostics(all_paths, prefix="simulated_market"),
                **portfolio_dispatch_diagnostics(results, probs),
            },
        )
