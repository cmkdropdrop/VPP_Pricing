"""Side-by-side comparison of pricing methods.

This module runs multiple pricing approaches against the same portfolio and
market data, then collects the results into a structured comparison that
highlights differences in valuation, risk metrics, and dispatch behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any

from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingMethod, PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.practical import approach_for_method


@dataclass(frozen=True)
class ComparisonResult:
    """Collected outputs from running multiple pricing methods."""

    portfolio_name: str
    num_scenarios: int
    results: dict[str, PricingResult]

    @property
    def method_names(self) -> list[str]:
        return list(self.results.keys())

    def summary_table(self) -> list[dict[str, Any]]:
        """Return a list of dicts suitable for tabular display."""
        rows = []
        intrinsic_value = (
            self.results["intrinsic"].expected_value_eur
            if "intrinsic" in self.results
            else None
        )
        for name, result in self.results.items():
            approach = approach_for_method(name)
            delta = (
                result.expected_value_eur - intrinsic_value
                if intrinsic_value is not None
                else None
            )
            capture_ratio = (
                (result.expected_value_eur / intrinsic_value * 100.0)
                if intrinsic_value is not None and abs(intrinsic_value) > 1e-9
                else None
            )
            rows.append(
                {
                    "method": name,
                    "practical_approach": approach.id if approach else None,
                    "economic_role": approach.economic_role if approach else None,
                    "expected_value_eur": round(result.expected_value_eur, 2),
                    "std_dev_eur": round(
                        float(result.diagnostics.get("cashflow_std_eur", 0.0)), 2
                    ),
                    "CaR_eur": round(result.cashflow_at_risk_eur, 2),
                    "CVaR_eur": round(result.conditional_value_at_risk_eur, 2),
                    "risk_adj_eur": round(result.risk_adjusted_value_eur, 2),
                    "export_mwh": round(
                        float(
                            result.diagnostics.get(
                                "dispatch_expected_export_mwh", 0.0
                            )
                        ),
                        3,
                    ),
                    "import_mwh": round(
                        float(
                            result.diagnostics.get(
                                "dispatch_expected_import_mwh", 0.0
                            )
                        ),
                        3,
                    ),
                    "capture_price_eur_per_mwh": round(
                        float(
                            result.diagnostics.get(
                                "dispatch_capture_price_eur_per_mwh", 0.0
                            )
                        ),
                        2,
                    ),
                    "negative_price_export_mwh": round(
                        float(
                            result.diagnostics.get(
                                "dispatch_negative_price_export_mwh", 0.0
                            )
                        ),
                        3,
                    ),
                    "battery_equivalent_cycles": round(
                        float(
                            result.diagnostics.get(
                                "dispatch_battery_equivalent_cycles", 0.0
                            )
                        ),
                        3,
                    ),
                    "delta_vs_intrinsic_eur": (
                        round(delta, 2) if delta is not None else None
                    ),
                    "capture_ratio_pct": (
                        round(capture_ratio, 1) if capture_ratio is not None else None
                    ),
                    "num_scenarios": result.num_scenarios,
                }
            )
        return rows

    def mispricing_warnings(self) -> list[str]:
        """Return context-dependent warnings about potential mispricing."""
        warnings: list[str] = []
        intrinsic = self.results.get("intrinsic")
        if intrinsic is not None:
            warnings.append(
                "intrinsic: perfect-foresight upper bound, not an executable strategy"
            )

        mc = self.results.get("monte_carlo")
        if mc is not None:
            if (
                intrinsic is not None
                and mc.expected_value_eur > intrinsic.expected_value_eur + 1e-2
            ):
                warnings.append(
                    "monte_carlo E[V] exceeds base-scenario intrinsic - simulated "
                    "path volatility and the selected dispatch policy can create "
                    "apparent uplift; validate before treating it as executable value"
                )
            num_paths = mc.parameters.get("num_paths", 0)
            if num_paths < 100:
                warnings.append(
                    f"monte_carlo: only {num_paths} paths - tail statistics "
                    f"(CaR, CVaR) may be unreliable"
                )
            if mc.parameters.get("dispatch_policy") == "intrinsic_per_path":
                warnings.append(
                    "monte_carlo: dispatch uses full-path perfect foresight; set "
                    "dispatch_window_hours for a more operational receding-horizon policy"
                )

        rolling = self.results.get("rolling_intrinsic")
        if rolling is not None:
            warnings.append(
                "rolling_intrinsic: still uses known prices within window "
                "(no forecast error modelled)"
            )

        for name, result in self.results.items():
            negative_export = float(
                result.diagnostics.get("dispatch_negative_price_export_mwh", 0.0)
            )
            if negative_export > 1e-6:
                warnings.append(
                    f"{name}: exports {negative_export:.2f} MWh during negative-price "
                    "intervals; check curtailment logic, PPA clauses, and imbalance rules"
                )

            cycles_per_day = float(
                result.diagnostics.get(
                    "dispatch_max_battery_equivalent_cycles_per_day", 0.0
                )
            )
            if cycles_per_day > 2.0:
                warnings.append(
                    f"{name}: battery cycles average {cycles_per_day:.2f}/day; "
                    "validate degradation, warranty, and availability assumptions"
                )
        return warnings

    def to_dict(self, include_timeseries: bool = False) -> dict[str, Any]:
        return {
            "portfolio_name": self.portfolio_name,
            "num_base_scenarios": self.num_scenarios,
            "methods": {
                name: res.to_dict(include_timeseries=include_timeseries)
                for name, res in self.results.items()
            },
            "summary": self.summary_table(),
            "mispricing_warnings": self.mispricing_warnings(),
        }


def compare_methods(
    portfolio: VirtualPowerPlant,
    markets: list[MarketData],
    methods: list[PricingMethod],
    *,
    risk_aversion: float = 0.0,
    alpha: float = 0.05,
) -> ComparisonResult:
    """Run each method against the same inputs and collect results."""
    _validate_markets(markets)
    results: dict[str, PricingResult] = {}
    for method in methods:
        if method.name in results:
            raise ValueError(f"duplicate pricing method: {method.name!r}")
        results[method.name] = method.price(
            portfolio, markets, risk_aversion=risk_aversion, alpha=alpha
        )

    return ComparisonResult(
        portfolio_name=portfolio.name,
        num_scenarios=len(markets),
        results=results,
    )


def _validate_markets(markets: list[MarketData]) -> None:
    if not markets:
        raise ValueError("at least one market scenario is required")
    first = markets[0]
    for market in markets[1:]:
        if market.timestamps != first.timestamps:
            raise ValueError("all market scenarios must use identical timestamps")
        if not isclose(market.timestep_hours, first.timestep_hours, rel_tol=0.0):
            raise ValueError("all market scenarios must use identical timesteps")
