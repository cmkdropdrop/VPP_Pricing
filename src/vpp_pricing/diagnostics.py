"""Analysis diagnostics shared by pricing methods.

The pricing methods intentionally return a compact headline valuation plus a
diagnostics dictionary.  This module keeps the diagnostics consistent across
methods so method comparisons do not mix incompatible definitions.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from vpp_pricing.market import MarketData
from vpp_pricing.results import PortfolioDispatch
from vpp_pricing.risk import normalized_probabilities, weighted_mean, weighted_quantile


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def market_price_diagnostics(
    markets: Iterable[MarketData],
    *,
    prefix: str = "market",
) -> dict[str, float]:
    """Return weighted price-distribution diagnostics for market scenarios."""
    market_list = list(markets)
    if not market_list:
        raise ValueError("at least one market scenario is required")

    scenario_probs = normalized_probabilities(
        [market.probability for market in market_list], len(market_list)
    )
    values: list[float] = []
    weights: list[float] = []
    move_values: list[float] = []
    move_weights: list[float] = []

    for market, scenario_prob in zip(market_list, scenario_probs):
        interval_weight = scenario_prob / market.intervals
        values.extend(market.prices_eur_per_mwh)
        weights.extend(interval_weight for _ in range(market.intervals))

        if market.intervals > 1:
            move_weight = scenario_prob / (market.intervals - 1)
            for previous, current in zip(
                market.prices_eur_per_mwh, market.prices_eur_per_mwh[1:]
            ):
                move_values.append(abs(current - previous))
                move_weights.append(move_weight)

    mean_price = weighted_mean(values, weights)
    variance = weighted_mean([(value - mean_price) ** 2 for value in values], weights)
    negative_weight = sum(
        weight for value, weight in zip(values, weights) if value < 0.0
    )

    diagnostics = {
        f"{prefix}_price_min_eur_per_mwh": _round(min(values), 4),
        f"{prefix}_price_p05_eur_per_mwh": _round(
            weighted_quantile(values, weights, 0.05), 4
        ),
        f"{prefix}_price_mean_eur_per_mwh": _round(mean_price, 4),
        f"{prefix}_price_p50_eur_per_mwh": _round(
            weighted_quantile(values, weights, 0.50), 4
        ),
        f"{prefix}_price_p95_eur_per_mwh": _round(
            weighted_quantile(values, weights, 0.95), 4
        ),
        f"{prefix}_price_max_eur_per_mwh": _round(max(values), 4),
        f"{prefix}_price_std_eur_per_mwh": _round(variance**0.5, 4),
        f"{prefix}_negative_price_interval_pct": _round(100.0 * negative_weight, 4),
        f"{prefix}_price_spread_p95_p05_eur_per_mwh": _round(
            weighted_quantile(values, weights, 0.95)
            - weighted_quantile(values, weights, 0.05),
            4,
        ),
    }
    if move_values:
        diagnostics[f"{prefix}_mean_abs_interval_move_eur_per_mwh"] = _round(
            weighted_mean(move_values, move_weights), 4
        )
    else:
        diagnostics[f"{prefix}_mean_abs_interval_move_eur_per_mwh"] = 0.0
    return diagnostics


def portfolio_dispatch_diagnostics(
    dispatches: Iterable[PortfolioDispatch],
    probabilities: Iterable[float],
    *,
    prefix: str = "dispatch",
) -> dict[str, Any]:
    """Return weighted dispatch, capture-price, and cycling diagnostics."""
    dispatch_list = list(dispatches)
    if not dispatch_list:
        raise ValueError("at least one dispatch result is required")
    probs = normalized_probabilities(probabilities, len(dispatch_list))

    total_cashflow = 0.0
    export_mwh = 0.0
    import_mwh = 0.0
    export_revenue = 0.0
    import_cost = 0.0
    negative_price_export_mwh = 0.0
    negative_price_import_mwh = 0.0
    negative_price_market_cashflow = 0.0
    expected_peak_export = 0.0
    expected_peak_import = 0.0
    max_peak_export = 0.0
    max_peak_import = 0.0
    battery_cycles_by_asset: defaultdict[str, float] = defaultdict(float)

    first = dispatch_list[0]
    horizon_hours = first.intervals * first.timestep_hours

    for dispatch, probability in zip(dispatch_list, probs):
        power = dispatch.aggregate_power_mw
        dt = dispatch.timestep_hours
        scenario_export = 0.0
        scenario_import = 0.0
        scenario_export_revenue = 0.0
        scenario_import_cost = 0.0
        scenario_negative_export = 0.0
        scenario_negative_import = 0.0
        scenario_negative_cashflow = 0.0

        for mw, price in zip(power, dispatch.prices_eur_per_mwh):
            exported = max(mw, 0.0) * dt
            imported = max(-mw, 0.0) * dt
            scenario_export += exported
            scenario_import += imported
            scenario_export_revenue += exported * price
            scenario_import_cost += imported * price
            if price < 0.0:
                scenario_negative_export += exported
                scenario_negative_import += imported
                scenario_negative_cashflow += (exported - imported) * price

        scenario_peak_export = max(power) if power else 0.0
        scenario_peak_import = abs(min(power)) if power else 0.0

        total_cashflow += probability * dispatch.total_cashflow_eur
        export_mwh += probability * scenario_export
        import_mwh += probability * scenario_import
        export_revenue += probability * scenario_export_revenue
        import_cost += probability * scenario_import_cost
        negative_price_export_mwh += probability * scenario_negative_export
        negative_price_import_mwh += probability * scenario_negative_import
        negative_price_market_cashflow += probability * scenario_negative_cashflow
        expected_peak_export += probability * scenario_peak_export
        expected_peak_import += probability * scenario_peak_import
        max_peak_export = max(max_peak_export, scenario_peak_export)
        max_peak_import = max(max_peak_import, scenario_peak_import)

        for asset in dispatch.asset_dispatches:
            if asset.asset_type != "battery":
                continue
            capacity = float(asset.metadata.get("capacity_mwh", 0.0) or 0.0)
            if capacity <= 0.0:
                continue
            throughput = sum(abs(mw) * dt for mw in asset.power_mw)
            battery_cycles_by_asset[asset.asset_name] += probability * (
                throughput / (2.0 * capacity)
            )

    gross_traded_mwh = export_mwh + import_mwh
    capture_price = export_revenue / export_mwh if export_mwh > 0.0 else 0.0
    import_price = import_cost / import_mwh if import_mwh > 0.0 else 0.0
    horizon_days = horizon_hours / 24.0 if horizon_hours > 0.0 else 0.0
    battery_cycles = sum(battery_cycles_by_asset.values())
    max_asset_cycles = max(battery_cycles_by_asset.values(), default=0.0)
    cycles_per_day = max_asset_cycles / horizon_days if horizon_days > 0.0 else 0.0

    return {
        f"{prefix}_expected_total_cashflow_eur": _round(total_cashflow, 2),
        f"{prefix}_expected_export_mwh": _round(export_mwh, 6),
        f"{prefix}_expected_import_mwh": _round(import_mwh, 6),
        f"{prefix}_expected_net_export_mwh": _round(export_mwh - import_mwh, 6),
        f"{prefix}_gross_traded_mwh": _round(gross_traded_mwh, 6),
        f"{prefix}_capture_price_eur_per_mwh": _round(capture_price, 4),
        f"{prefix}_average_import_price_eur_per_mwh": _round(import_price, 4),
        f"{prefix}_expected_peak_export_mw": _round(expected_peak_export, 6),
        f"{prefix}_expected_peak_import_mw": _round(expected_peak_import, 6),
        f"{prefix}_max_peak_export_mw": _round(max_peak_export, 6),
        f"{prefix}_max_peak_import_mw": _round(max_peak_import, 6),
        f"{prefix}_negative_price_export_mwh": _round(
            negative_price_export_mwh, 6
        ),
        f"{prefix}_negative_price_import_mwh": _round(
            negative_price_import_mwh, 6
        ),
        f"{prefix}_negative_price_market_cashflow_eur": _round(
            negative_price_market_cashflow, 2
        ),
        f"{prefix}_battery_equivalent_cycles": _round(battery_cycles, 6),
        f"{prefix}_max_battery_equivalent_cycles_per_asset": _round(
            max_asset_cycles, 6
        ),
        f"{prefix}_max_battery_equivalent_cycles_per_day": _round(
            cycles_per_day, 6
        ),
        f"{prefix}_battery_cycles_by_asset": {
            name: _round(cycles, 6)
            for name, cycles in sorted(battery_cycles_by_asset.items())
        },
    }
