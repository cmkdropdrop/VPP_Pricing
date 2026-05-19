"""Rolling-intrinsic pricing: limited look-ahead dispatch.

Instead of giving each asset the full price curve, this method reveals
prices in a sliding window.  At each step batteries and flexible loads
optimise over the next ``window_hours`` intervals and commit only the
first interval.  The window then rolls forward.

This models a more realistic operator who re-optimises periodically
with a finite forecast horizon.

Strengths:
    * More realistic than full-horizon intrinsic -- captures forecast
      uncertainty implicitly through the limited window.
    * Deterministic given the window size.
    * Reveals how much value is lost versus perfect foresight.

Limitations:
    * Still uses known prices within the window (no forecast error).
    * Battery and flexible-load dispatch is still myopic beyond the window edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt

from vpp_pricing.assets import BatteryStorage, FlexibleLoad
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

    throughput_mwh = sum(abs(power_mw) * market.timestep_hours for power_mw in power_out)
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
            "throughput_mwh": round(throughput_mwh, 6),
            "equivalent_cycles": round(
                throughput_mwh / (2.0 * battery.capacity_mwh), 6
            ),
        },
    )


def _optimise_flexible_load_window(
    load: FlexibleLoad,
    market: MarketData,
    *,
    start: int,
    window_intervals: int,
    remaining_energy_mwh: float,
) -> tuple[float, float, float]:
    """Return first-step power, cashflow, and remaining energy for a flex load."""
    if load.min_power_mw < 0 or load.max_power_mw < 0:
        raise ValueError("load power limits must not be negative")
    if load.min_power_mw > load.max_power_mw:
        raise ValueError("min_power_mw must be <= max_power_mw")

    dt = market.timestep_hours
    intervals_remaining = market.intervals - start
    if intervals_remaining <= 0:
        raise ValueError("start must be within the market horizon")

    min_total = load.min_power_mw * dt * intervals_remaining
    max_total = load.max_power_mw * dt * intervals_remaining
    if (
        remaining_energy_mwh < min_total - 1e-9
        or remaining_energy_mwh > max_total + 1e-9
    ):
        raise ValueError("remaining flexible-load energy is infeasible")

    end = min(start + window_intervals, market.intervals)
    window_len = end - start
    future_intervals = intervals_remaining - window_len

    min_window_energy = max(
        load.min_power_mw * dt * window_len,
        remaining_energy_mwh - load.max_power_mw * dt * future_intervals,
    )
    max_window_energy = min(
        load.max_power_mw * dt * window_len,
        remaining_energy_mwh - load.min_power_mw * dt * future_intervals,
    )
    if min_window_energy > max_window_energy + 1e-9:
        raise ValueError("rolling flexible-load window has no feasible plan")

    consumption = [load.min_power_mw for _ in range(window_len)]
    planned_energy = load.min_power_mw * dt * window_len
    prices = market.prices_eur_per_mwh[start:end]
    cheapest = sorted(range(window_len), key=lambda i: prices[i])

    required_extra = max(0.0, min_window_energy - planned_energy)
    for local_idx in cheapest:
        if required_extra <= 1e-9:
            break
        available = (load.max_power_mw - consumption[local_idx]) * dt
        add = min(available, required_extra)
        consumption[local_idx] += add / dt
        planned_energy += add
        required_extra -= add

    optional_extra = max(0.0, max_window_energy - planned_energy)
    for local_idx in cheapest:
        if optional_extra <= 1e-9 or prices[local_idx] >= 0.0:
            break
        available = (load.max_power_mw - consumption[local_idx]) * dt
        add = min(available, optional_extra)
        consumption[local_idx] += add / dt
        planned_energy += add
        optional_extra -= add

    first_consumption_mw = consumption[0]
    power_mw = -first_consumption_mw
    cashflow_eur = (
        market.prices_eur_per_mwh[start] * power_mw
        + load.value_eur_per_mwh * abs(power_mw)
    ) * dt
    next_remaining = remaining_energy_mwh - first_consumption_mw * dt
    return power_mw, cashflow_eur, next_remaining


def _rolling_dispatch_flexible_load(
    load: FlexibleLoad, market: MarketData, window_intervals: int
) -> AssetDispatch:
    """Dispatch a flexible load with rolling look-ahead optimisation."""
    dt = market.timestep_hours
    min_energy = load.min_power_mw * dt * market.intervals
    max_energy = load.max_power_mw * dt * market.intervals
    if load.energy_mwh < min_energy - 1e-9 or load.energy_mwh > max_energy + 1e-9:
        raise ValueError(
            f"energy_mwh={load.energy_mwh} is infeasible for bounds "
            f"[{min_energy}, {max_energy}]"
        )

    remaining = load.energy_mwh
    power_out: list[float] = []
    cashflow_out: list[float] = []

    for t in range(market.intervals):
        power_mw, cashflow_eur, remaining = _optimise_flexible_load_window(
            load,
            market,
            start=t,
            window_intervals=window_intervals,
            remaining_energy_mwh=remaining,
        )
        power_out.append(power_mw)
        cashflow_out.append(cashflow_eur)

    consumption = [-mw for mw in power_out]
    baseline_mw = load.energy_mwh / (dt * market.intervals)
    baseline_cost = sum(
        price * baseline_mw * dt for price in market.prices_eur_per_mwh
    )
    optimized_cost = sum(
        price * mw * dt for price, mw in zip(market.prices_eur_per_mwh, consumption)
    )
    gross_consumption_value = load.value_eur_per_mwh * load.energy_mwh

    return AssetDispatch(
        asset_name=load.name,
        asset_type="flexible_load",
        power_mw=tuple(power_out),
        cashflow_eur=tuple(cashflow_out),
        metadata={
            "energy_mwh": load.energy_mwh,
            "terminal_remaining_energy_mwh": round(remaining, 6),
            "window_hours": window_intervals * market.timestep_hours,
            "window_intervals": window_intervals,
            "baseline_cost_eur": baseline_cost,
            "optimized_cost_eur": optimized_cost,
            "flex_value_eur": baseline_cost - optimized_cost,
            "gross_consumption_value_eur": gross_consumption_value,
        },
    )


def dispatch_with_rolling_battery_policy(
    portfolio: VirtualPowerPlant, market: MarketData, window_intervals: int
) -> PortfolioDispatch:
    """Dispatch the portfolio with rolling battery and flexible-load decisions."""
    if window_intervals <= 0:
        raise ValueError("window_intervals must be positive")

    dispatches: list[AssetDispatch] = []
    for asset in portfolio.assets:
        if isinstance(asset, BatteryStorage):
            dispatches.append(
                _rolling_dispatch_battery(asset, market, window_intervals)
            )
        elif isinstance(asset, FlexibleLoad):
            dispatches.append(
                _rolling_dispatch_flexible_load(asset, market, window_intervals)
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


_rolling_dispatch_portfolio = dispatch_with_rolling_battery_policy


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
            dispatch_with_rolling_battery_policy(portfolio, market, window)
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
                **market_price_diagnostics(markets),
                **portfolio_dispatch_diagnostics(results, probs),
            },
        )
