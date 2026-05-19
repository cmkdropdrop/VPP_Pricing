"""Input validation and quality checks for portfolio pricing runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isclose
from typing import Any

from vpp_pricing.assets import (
    BatteryStorage,
    DispatchableGenerator,
    FixedLoad,
    FlexibleLoad,
    RenewableAsset,
)
from vpp_pricing.market import MarketData, validate_market_scenarios
from vpp_pricing.portfolio import VirtualPowerPlant


@dataclass(frozen=True)
class ValidationIssue:
    """A structured validation finding."""

    severity: str
    code: str
    message: str
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.context:
            payload["context"] = self.context
        return payload


@dataclass(frozen=True)
class ValidationReport:
    """Result of checking a portfolio and market scenario set."""

    portfolio_name: str
    asset_count: int
    market_count: int
    diagnostics: dict[str, Any]
    issues: tuple[ValidationIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_name": self.portfolio_name,
            "asset_count": self.asset_count,
            "market_count": self.market_count,
            "status": "failed" if self.has_errors else "passed",
            "diagnostics": self.diagnostics,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_portfolio_and_markets(
    portfolio: VirtualPowerPlant,
    markets: list[MarketData],
) -> ValidationReport:
    """Return technical and domain checks before running a valuation."""
    issues: list[ValidationIssue] = []

    try:
        validate_market_scenarios(markets)
    except ValueError as exc:
        issues.append(
            ValidationIssue(
                "error",
                "market_scenario_alignment",
                str(exc),
            )
        )

    diagnostics = _diagnostics(portfolio, markets)
    _check_probabilities(markets, issues)
    _check_assets(portfolio, markets, issues)
    _check_dispatch_feasibility(portfolio, markets, issues)

    return ValidationReport(
        portfolio_name=portfolio.name,
        asset_count=len(portfolio.assets),
        market_count=len(markets),
        diagnostics=diagnostics,
        issues=tuple(issues),
    )


def _diagnostics(
    portfolio: VirtualPowerPlant,
    markets: list[MarketData],
) -> dict[str, Any]:
    asset_counts = Counter(asset.__class__.__name__ for asset in portfolio.assets)
    prices = [
        price
        for market in markets
        for price in market.prices_eur_per_mwh
    ]
    first = markets[0] if markets else None
    horizon_hours = (
        first.intervals * first.timestep_hours
        if first is not None
        else 0.0
    )
    negative_intervals = sum(1 for price in prices if price < 0.0)

    return {
        "asset_types": dict(sorted(asset_counts.items())),
        "horizon_intervals": first.intervals if first is not None else 0,
        "horizon_hours": round(horizon_hours, 6),
        "timestep_hours": first.timestep_hours if first is not None else None,
        "scenario_probability_sum": round(sum(m.probability for m in markets), 8),
        "market_price_min_eur_per_mwh": min(prices) if prices else None,
        "market_price_max_eur_per_mwh": max(prices) if prices else None,
        "negative_price_interval_count": negative_intervals,
    }


def _check_probabilities(
    markets: list[MarketData],
    issues: list[ValidationIssue],
) -> None:
    if not markets:
        return

    total_probability = sum(market.probability for market in markets)
    if len(markets) == 1:
        issues.append(
            ValidationIssue(
                "warning",
                "single_market_scenario",
                "Only one market scenario is loaded; CaR, CVaR, and standard "
                "deviation will not describe scenario uncertainty.",
            )
        )
    if total_probability <= 0.0:
        issues.append(
            ValidationIssue(
                "warning",
                "zero_probability_sum",
                "Scenario probabilities sum to zero; pricing will fall back to "
                "equal weights.",
            )
        )
    elif not isclose(total_probability, 1.0, rel_tol=0.0, abs_tol=1e-6):
        issues.append(
            ValidationIssue(
                "info",
                "probabilities_normalized",
                "Scenario probabilities do not sum to 1.0; pricing normalizes "
                "them before computing risk metrics.",
                {"probability_sum": total_probability},
            )
        )


def _check_assets(
    portfolio: VirtualPowerPlant,
    markets: list[MarketData],
    issues: list[ValidationIssue],
) -> None:
    names = [str(getattr(asset, "name", "")) for asset in portfolio.assets]
    duplicate_names = sorted(
        name for name, count in Counter(names).items() if count > 1
    )
    if duplicate_names:
        issues.append(
            ValidationIssue(
                "warning",
                "duplicate_asset_names",
                "Asset names should be unique so dispatch diagnostics can be "
                "read without ambiguity.",
                {"asset_names": duplicate_names},
            )
        )

    controllable_types = (BatteryStorage, FlexibleLoad, DispatchableGenerator)
    if not any(isinstance(asset, controllable_types) for asset in portfolio.assets):
        issues.append(
            ValidationIssue(
                "info",
                "passive_portfolio",
                "The portfolio has no battery, flexible load, or dispatchable "
                "generator; most value will come from exogenous production/load "
                "profiles rather than dispatch optionality.",
            )
        )

    has_negative_prices = any(
        price < 0.0 for market in markets for price in market.prices_eur_per_mwh
    )

    for asset in portfolio.assets:
        if isinstance(asset, BatteryStorage):
            _check_battery(asset, issues)
        elif isinstance(asset, RenewableAsset) and has_negative_prices:
            if asset.curtail_below_price_eur_per_mwh is None:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "renewable_negative_price_curtailment",
                        f"Renewable asset {asset.name!r} can export during "
                        "negative-price intervals because no curtailment "
                        "threshold is configured.",
                    )
                )
        elif isinstance(asset, FixedLoad):
            continue


def _check_battery(
    battery: BatteryStorage,
    issues: list[ValidationIssue],
) -> None:
    if battery.cycle_cost_eur_per_mwh == 0.0:
        issues.append(
            ValidationIssue(
                "warning",
                "battery_degradation_omitted",
                f"Battery {battery.name!r} has zero cycle cost; valuation may "
                "overstate executable merchant value if degradation or warranty "
                "limits matter.",
            )
        )
    if battery.grid_points < 20:
        issues.append(
            ValidationIssue(
                "info",
                "battery_low_state_grid_resolution",
                f"Battery {battery.name!r} uses only {battery.grid_points} SOC "
                "grid points; increase grid_points for smoother dispatch values.",
            )
        )


def _check_dispatch_feasibility(
    portfolio: VirtualPowerPlant,
    markets: list[MarketData],
    issues: list[ValidationIssue],
) -> None:
    for market in markets:
        try:
            portfolio.dispatch(market)
        except Exception as exc:  # pragma: no cover - exact asset errors vary
            issues.append(
                ValidationIssue(
                    "error",
                    "dispatch_infeasible",
                    f"Portfolio dispatch failed for market {market.name!r}: {exc}",
                    {"market": market.name},
                )
            )
