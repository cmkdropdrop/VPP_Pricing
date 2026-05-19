"""Monte-Carlo extrinsic pricing via simulated price paths.

Given one or more base price scenarios, this method generates additional
price paths by adding correlated noise (geometric Brownian motion style
perturbation around the base curve).  The portfolio is dispatched
against each simulated path and the distribution of outcomes is used
to estimate expected value and risk metrics.

This captures *extrinsic* value -- the option value that arises from
the ability to react to price uncertainty, which the intrinsic method
ignores.

Strengths:
    * Captures optionality and extrinsic value.
    * Produces a full distribution of outcomes, not just point estimates.
    * Configurable via number of paths, volatility, and seed.

Limitations:
    * Dispatch is still perfect-foresight within each simulated path.
    * Price model is simplistic (log-normal perturbation); for production
      use, replace with calibrated stochastic models.
    * Slower than deterministic methods due to many dispatch evaluations.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import exp, log, sqrt
from statistics import mean, stdev

from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import PortfolioDispatch


def _simulate_paths(
    base_market: MarketData,
    num_paths: int,
    volatility: float,
    rng: random.Random,
) -> list[MarketData]:
    """Generate price paths as log-normal perturbations of the base curve."""
    dt = base_market.timestep_hours
    paths: list[MarketData] = []

    for i in range(num_paths):
        prices: list[float] = []
        cumulative_shock = 0.0
        for t, base_price in enumerate(base_market.prices_eur_per_mwh):
            # Mean-reverting noise: shock decays, fresh innovation each step
            innovation = rng.gauss(0, volatility * sqrt(dt))
            cumulative_shock = 0.7 * cumulative_shock + innovation
            if base_price > 0:
                sim_price = base_price * exp(cumulative_shock - 0.5 * volatility**2 * dt)
            else:
                # Handle zero/negative base prices additively
                sim_price = base_price + cumulative_shock * 20.0
            prices.append(round(sim_price, 4))

        paths.append(
            MarketData(
                timestamps=base_market.timestamps,
                prices_eur_per_mwh=tuple(prices),
                timestep_hours=base_market.timestep_hours,
                name=f"mc_{base_market.name}_{i:04d}",
                probability=1.0 / num_paths,
            )
        )
    return paths


@dataclass
class MonteCarloPricing:
    """Monte-Carlo simulation over synthetic price paths."""

    num_paths: int = 200
    volatility: float = 0.15
    seed: int | None = 42

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

        rng = random.Random(self.seed)

        # Generate simulated paths from all base scenarios
        all_paths: list[MarketData] = []
        paths_per_base = max(1, self.num_paths // len(markets))
        for base in markets:
            all_paths.extend(
                _simulate_paths(base, paths_per_base, self.volatility, rng)
            )

        # Re-normalise probabilities
        equal_prob = 1.0 / len(all_paths)
        normalised = [
            MarketData(
                timestamps=p.timestamps,
                prices_eur_per_mwh=p.prices_eur_per_mwh,
                timestep_hours=p.timestep_hours,
                name=p.name,
                probability=equal_prob,
            )
            for p in all_paths
        ]

        # Dispatch against every path
        results = tuple(portfolio.dispatch(m) for m in normalised)
        cashflows = [r.total_cashflow_eur for r in results]
        probs = [equal_prob] * len(results)

        expected = mean(cashflows)

        sorted_cf = sorted(cashflows)
        n_tail = max(1, int(alpha * len(sorted_cf)))
        car = sorted_cf[n_tail - 1]
        cvar = mean(sorted_cf[:n_tail])

        downside = max(0.0, expected - cvar)
        risk_adj = expected - risk_aversion * downside

        return PricingResult(
            method_name=self.name,
            portfolio_name=portfolio.name,
            expected_value_eur=expected,
            cashflow_at_risk_eur=car,
            conditional_value_at_risk_eur=cvar,
            risk_adjusted_value_eur=risk_adj,
            scenario_results=results,
            parameters={
                "risk_aversion": risk_aversion,
                "alpha": alpha,
                "num_paths": len(all_paths),
                "volatility": self.volatility,
                "seed": self.seed,
            },
            diagnostics={
                "num_paths_total": len(all_paths),
                "cashflow_mean_eur": round(expected, 2),
                "cashflow_std_eur": round(stdev(cashflows), 2) if len(cashflows) > 1 else 0.0,
                "cashflow_min_eur": round(min(cashflows), 2),
                "cashflow_max_eur": round(max(cashflows), 2),
                "cashflow_p5_eur": round(sorted_cf[n_tail - 1], 2),
                "cashflow_p95_eur": round(sorted_cf[-n_tail], 2),
            },
        )
