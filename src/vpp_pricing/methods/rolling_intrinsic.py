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
    * Battery dispatch is myopic beyond the window edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, sqrt

from vpp_pricing.assets import Asset, BatteryStorage
from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import AssetDispatch, PortfolioDispatch


def _rolling_dispatch_battery(
    battery: BatteryStorage, market: MarketData, window: int
) -> AssetDispatch:
    """Dispatch a battery with rolling look-ahead of *window* intervals."""
    dt = market.timestep_hours
    charge_eff = sqrt(battery.round_trip_efficiency)
    discharge_eff = sqrt(battery.round_trip_efficiency)
    soc = battery.initial_soc_mwh

    power_out: list[float] = []
    cashflow_out: list[float] = []

    for t in range(market.intervals):
        lookahead_end = min(t + window, market.intervals)
        window_prices = market.prices_eur_per_mwh[t:lookahead_end]

        best_power = 0.0
        best_cf = 0.0

        # Evaluate: idle, full charge, full discharge
        for action_mw in [0.0, -battery.power_mw, battery.power_mw]:
            if action_mw < 0:  # charging
                energy_in = abs(action_mw) * dt
                new_soc = soc + energy_in * charge_eff
                if new_soc > battery.capacity_mwh + 1e-9:
                    continue
                cf = action_mw * dt * window_prices[0]  # cost of charging
                cf -= battery.cycle_cost_eur_per_mwh * energy_in
            elif action_mw > 0:  # discharging
                energy_out = action_mw * dt
                soc_drain = energy_out / discharge_eff
                if soc - soc_drain < -1e-9:
                    continue
                cf = action_mw * dt * window_prices[0]
                cf -= battery.cycle_cost_eur_per_mwh * energy_out
            else:
                cf = 0.0

            # Simple heuristic: charge when current price is below window
            # average, discharge when above.
            avg_future = sum(window_prices) / len(window_prices)
            if action_mw < 0:
                # Charging is attractive when price is low relative to future
                score = cf + (avg_future - window_prices[0]) * abs(action_mw) * dt * 0.5
            elif action_mw > 0:
                score = cf + (window_prices[0] - avg_future) * action_mw * dt * 0.3
            else:
                score = 0.0

            if score > best_cf + 1e-9:
                best_cf = cf
                best_power = action_mw

        # Commit action
        if best_power < 0:
            energy_in = abs(best_power) * dt
            soc += energy_in * charge_eff
            actual_cf = best_power * dt * window_prices[0]
            actual_cf -= battery.cycle_cost_eur_per_mwh * energy_in
        elif best_power > 0:
            energy_out = best_power * dt
            soc -= energy_out / discharge_eff
            actual_cf = best_power * dt * window_prices[0]
            actual_cf -= battery.cycle_cost_eur_per_mwh * energy_out
        else:
            actual_cf = 0.0

        power_out.append(best_power)
        cashflow_out.append(actual_cf)

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
            "window_hours": window * dt,
        },
    )


def _rolling_dispatch_portfolio(
    portfolio: VirtualPowerPlant, market: MarketData, window: int
) -> PortfolioDispatch:
    """Dispatch the portfolio: batteries use rolling window, others use
    their default (full-horizon) dispatch since they don't benefit from
    look-ahead (renewables/loads are price-takers)."""
    dispatches: list[AssetDispatch] = []
    for asset in portfolio.assets:
        if isinstance(asset, BatteryStorage):
            dispatches.append(_rolling_dispatch_battery(asset, market, window))
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


def _normalized_probabilities(probs: list[float]) -> list[float]:
    total = sum(probs)
    if total <= 0:
        return [1.0 / len(probs)] * len(probs)
    return [p / total for p in probs]


def _weighted_quantile(values: list[float], probs: list[float], alpha: float) -> float:
    ordered = sorted(zip(values, probs), key=lambda x: x[0])
    cum = 0.0
    for v, p in ordered:
        cum += p
        if cum >= alpha:
            return v
    return ordered[-1][0]


def _weighted_cvar(values: list[float], probs: list[float], alpha: float) -> float:
    ordered = sorted(zip(values, probs), key=lambda x: x[0])
    remaining = alpha
    ws = 0.0
    used = 0.0
    for v, p in ordered:
        take = min(p, remaining)
        if take <= 0:
            break
        ws += v * take
        used += take
        remaining -= take
    return ws / used if used > 0 else ordered[0][0]


@dataclass
class RollingIntrinsicPricing:
    """Rolling look-ahead intrinsic value with configurable window."""

    window_hours: int = 6

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

        window = max(1, self.window_hours)
        results = tuple(
            _rolling_dispatch_portfolio(portfolio, m, window) for m in markets
        )
        probs = _normalized_probabilities([m.probability for m in markets])
        cashflows = [r.total_cashflow_eur for r in results]

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
            scenario_results=results,
            parameters={
                "risk_aversion": risk_aversion,
                "alpha": alpha,
                "window_hours": window,
            },
            diagnostics={
                "num_scenarios": len(markets),
                "scenario_cashflows_eur": [round(c, 2) for c in cashflows],
            },
        )
