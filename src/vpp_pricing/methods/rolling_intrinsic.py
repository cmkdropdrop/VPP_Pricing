"""Rolling-intrinsic pricing: limited look-ahead dispatch.

Instead of giving each asset the full price curve, this method reveals
prices in a sliding window.  At each step the asset optimises over the
next ``window_hours`` intervals and commits only the first interval.
The window then rolls forward.

This models a more realistic operator who re-optimises periodically
with a finite forecast horizon.

Strengths:
    * More realistic than full-horizon intrinsic -- captures forecast
      uncertainty implicitly through the limited window.
    * Deterministic given the window size.
    * Reveals how much value is lost versus perfect foresight.

Limitations:
    * Still uses known prices within the window (no forecast error).
    * Battery dispatch is still myopic beyond the window edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt

from vpp_pricing.assets import BatteryStorage
from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.risk import (
    cashflow_distribution_diagnostics,
    cashflow_risk_metrics,
    normalized_probabilities,
)
from vpp_pricing.results import AssetDispatch, PortfolioDispatch


def _terminal_soc(battery: BatteryStorage) -> float:
    return (
        battery.initial_soc_mwh
        if battery.terminal_soc_mwh is None
        else battery.terminal_soc_mwh
    )


def _state_grid(
    battery: BatteryStorage,
    *,
    current_soc: float,
    terminal_soc: float,
) -> tuple[float, ...]:
    base = [
        battery.capacity_mwh * i / (battery.grid_points - 1)
        for i in range(battery.grid_points)
    ]
    base.extend([0.0, battery.capacity_mwh, current_soc, terminal_soc])
    unique = sorted({round(min(max(v, 0.0), battery.capacity_mwh), 10) for v in base})
    return tuple(unique)


def _can_reach_soc(
    battery: BatteryStorage,
    *,
    current_soc: float,
    target_soc: float,
    intervals_remaining: int,
    timestep_hours: float,
) -> bool:
    if intervals_remaining < 0:
        return False
    charge_eff = sqrt(battery.round_trip_efficiency)
    discharge_eff = sqrt(battery.round_trip_efficiency)
    max_charge_delta = (
        intervals_remaining * battery.power_mw * timestep_hours * charge_eff
    )
    max_discharge_delta = (
        intervals_remaining * battery.power_mw * timestep_hours / discharge_eff
    )
    return (
        target_soc <= current_soc + max_charge_delta + 1e-9
        and target_soc >= current_soc - max_discharge_delta - 1e-9
    )


def _optimise_battery_window(
    battery: BatteryStorage,
    market: MarketData,
    *,
    start: int,
    window_intervals: int,
    current_soc: float,
) -> tuple[float, float, float]:
    """Return first-step power, cashflow, and next SOC from a rolling DP."""
    if battery.capacity_mwh <= 0:
        raise ValueError("capacity_mwh must be positive")
    if battery.power_mw < 0:
        raise ValueError("power_mw must not be negative")
    if not 0 < battery.round_trip_efficiency <= 1:
        raise ValueError("round_trip_efficiency must be in (0, 1]")
    if battery.grid_points < 2:
        raise ValueError("grid_points must be at least 2")

    terminal_soc = _terminal_soc(battery)
    if current_soc < -1e-9 or current_soc > battery.capacity_mwh + 1e-9:
        raise ValueError("current battery SOC must be within [0, capacity_mwh]")
    if terminal_soc < -1e-9 or terminal_soc > battery.capacity_mwh + 1e-9:
        raise ValueError("terminal battery SOC must be within [0, capacity_mwh]")

    end = min(start + window_intervals, market.intervals)
    states = _state_grid(
        battery,
        current_soc=current_soc,
        terminal_soc=terminal_soc,
    )
    initial_idx = min(range(len(states)), key=lambda i: abs(states[i] - current_soc))
    terminal_idx = min(range(len(states)), key=lambda i: abs(states[i] - terminal_soc))
    charge_efficiency = sqrt(battery.round_trip_efficiency)
    discharge_efficiency = sqrt(battery.round_trip_efficiency)

    neg_inf = float("-inf")
    dp = [neg_inf for _ in states]
    dp[initial_idx] = 0.0
    parents: list[list[tuple[int, float, float] | None]] = []

    for local_step, price in enumerate(market.prices_eur_per_mwh[start:end]):
        absolute_step = start + local_step
        next_dp = [neg_inf for _ in states]
        step_parent: list[tuple[int, float, float] | None] = [None for _ in states]
        for current_idx, value in enumerate(dp):
            if value == neg_inf:
                continue
            for next_idx, next_soc in enumerate(states):
                if not _can_reach_soc(
                    battery,
                    current_soc=next_soc,
                    target_soc=terminal_soc,
                    intervals_remaining=market.intervals - absolute_step - 1,
                    timestep_hours=market.timestep_hours,
                ):
                    continue
                transition = battery._transition(
                    current_soc=states[current_idx],
                    next_soc=next_soc,
                    price=price,
                    timestep_hours=market.timestep_hours,
                    charge_efficiency=charge_efficiency,
                    discharge_efficiency=discharge_efficiency,
                )
                if transition is None:
                    continue
                power_mw, cashflow_eur = transition
                candidate = value + cashflow_eur
                if candidate > next_dp[next_idx] + 1e-12:
                    next_dp[next_idx] = candidate
                    step_parent[next_idx] = (current_idx, power_mw, cashflow_eur)
        dp = next_dp
        parents.append(step_parent)

    candidate_indices: range | tuple[int, ...]
    if end == market.intervals:
        candidate_indices = (terminal_idx,)
    else:
        candidate_indices = range(len(states))

    best_idx = max(candidate_indices, key=lambda idx: dp[idx])
    if dp[best_idx] == neg_inf:
        raise ValueError("rolling battery dispatch has no feasible path")

    idx = best_idx
    reversed_path: list[tuple[float, float, float]] = []
    for local_step in range(len(parents) - 1, -1, -1):
        parent = parents[local_step][idx]
        if parent is None:
            raise RuntimeError("rolling battery path reconstruction failed")
        previous_idx, power_mw, cashflow_eur = parent
        reversed_path.append((power_mw, cashflow_eur, states[idx]))
        idx = previous_idx

    power_mw, cashflow_eur, next_soc = reversed_path[-1]
    return power_mw, cashflow_eur, next_soc


def _rolling_dispatch_battery(
    battery: BatteryStorage, market: MarketData, window_intervals: int
) -> AssetDispatch:
    """Dispatch a battery with rolling look-ahead optimisation."""
    soc = battery.initial_soc_mwh

    power_out: list[float] = []
    cashflow_out: list[float] = []

    for t in range(market.intervals):
        power_mw, cashflow_eur, next_soc = _optimise_battery_window(
            battery,
            market,
            start=t,
            window_intervals=window_intervals,
            current_soc=soc,
        )
        power_out.append(power_mw)
        cashflow_out.append(cashflow_eur)
        soc = next_soc

    return AssetDispatch(
        asset_name=battery.name,
        asset_type="battery",
        power_mw=tuple(power_out),
        cashflow_eur=tuple(cashflow_out),
        metadata={
            "capacity_mwh": battery.capacity_mwh,
            "power_mw": battery.power_mw,
            "round_trip_efficiency": battery.round_trip_efficiency,
            "initial_soc_mwh": battery.initial_soc_mwh,
            "terminal_soc_mwh": round(soc, 6),
            "window_hours": window_intervals * market.timestep_hours,
            "window_intervals": window_intervals,
        },
    )


def _rolling_dispatch_portfolio(
    portfolio: VirtualPowerPlant, market: MarketData, window_intervals: int
) -> PortfolioDispatch:
    """Dispatch the portfolio with rolling battery decisions."""
    dispatches: list[AssetDispatch] = []
    for asset in portfolio.assets:
        if isinstance(asset, BatteryStorage):
            dispatches.append(
                _rolling_dispatch_battery(asset, market, window_intervals)
            )
        else:
            dispatches.append(asset.dispatch(market))

    return PortfolioDispatch(
        portfolio_name=portfolio.name,
        market_name=market.name,
        timestamps=market.timestamps,
        prices_eur_per_mwh=market.prices_eur_per_mwh,
        timestep_hours=market.timestep_hours,
        asset_dispatches=tuple(dispatches),
    )


@dataclass
class RollingIntrinsicPricing:
    """Rolling look-ahead intrinsic value with configurable window."""

    window_hours: float = 6.0

    @property
    def name(self) -> str:
        return "rolling_intrinsic"

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
        if self.window_hours <= 0:
            raise ValueError("window_hours must be positive")

        window_by_market = [
            max(1, ceil(self.window_hours / m.timestep_hours)) for m in markets
        ]
        results = tuple(
            _rolling_dispatch_portfolio(portfolio, market, window)
            for market, window in zip(markets, window_by_market)
        )
        probs = normalized_probabilities([m.probability for m in markets], len(markets))
        cashflows = [r.total_cashflow_eur for r in results]
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
                "window_hours": self.window_hours,
                "window_intervals_by_scenario": window_by_market,
            },
            diagnostics={
                "num_scenarios": len(markets),
                "scenario_cashflows_eur": [round(c, 2) for c in cashflows],
                "scenario_probabilities": [round(p, 6) for p in probs],
                **metrics.diagnostics(),
                **cashflow_distribution_diagnostics(cashflows, probs),
            },
        )
