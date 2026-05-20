"""Historical backtesting primitives for tradable VPP pricing runs.

The backtest flow separates information available at valuation time from
settlement prices observed after delivery.  It prices each historical product
with valuation-market data, selects a decision schedule from that valuation
run, and settles that fixed schedule against realized prices.  It does not
re-optimize dispatch on settlement prices.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from math import isclose, isfinite, sqrt
from pathlib import Path
from typing import Any, Iterable

from vpp_pricing.market import MarketData, validate_market_scenarios
from vpp_pricing.methods.base import PricingMethod, PricingResult
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import AssetDispatch, PortfolioDispatch


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


@dataclass(frozen=True)
class HistoricalMarketProduct:
    """One historical product snapshot used for backtesting.

    ``valuation_markets`` are the prices or scenarios available at ``as_of``.
    ``settlement_market`` is the realized price curve used to settle the
    decision schedule chosen from the valuation run.
    """

    product_id: str
    as_of: str
    valuation_markets: tuple[MarketData, ...]
    settlement_market: MarketData
    decision_market_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        product_id = str(self.product_id).strip()
        as_of = str(self.as_of).strip()
        if not product_id:
            raise ValueError("product_id must not be empty")
        if not as_of:
            raise ValueError("as_of must not be empty")

        valuation_markets = tuple(self.valuation_markets)
        validate_market_scenarios(list(valuation_markets))
        for market in valuation_markets:
            _validate_market_alignment(
                market,
                self.settlement_market,
                context="valuation and settlement markets",
            )

        decision_market_name = self.decision_market_name
        if decision_market_name is not None:
            decision_market_name = str(decision_market_name).strip()
            if not decision_market_name:
                decision_market_name = None
        if decision_market_name is not None and not any(
            market.name == decision_market_name for market in valuation_markets
        ):
            raise ValueError(
                f"decision market {decision_market_name!r} is not present in "
                f"product {product_id!r}"
            )

        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valuation_markets", valuation_markets)
        object.__setattr__(self, "decision_market_name", decision_market_name)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def intervals(self) -> int:
        return self.settlement_market.intervals

    @property
    def timestamps(self) -> tuple[str, ...]:
        return self.settlement_market.timestamps

    @property
    def timestep_hours(self) -> float:
        return self.settlement_market.timestep_hours

    @property
    def decision_market(self) -> MarketData:
        if self.decision_market_name is not None:
            for market in self.valuation_markets:
                if market.name == self.decision_market_name:
                    return market
        best = self.valuation_markets[0]
        for market in self.valuation_markets[1:]:
            if market.probability > best.probability:
                best = market
        return best

    def to_dict(self, include_timeseries: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "product_id": self.product_id,
            "as_of": self.as_of,
            "decision_market_name": self.decision_market.name,
            "valuation_scenarios": [
                {
                    "name": market.name,
                    "probability": _round(market.probability),
                    "intervals": market.intervals,
                }
                for market in self.valuation_markets
            ],
            "settlement_market_name": self.settlement_market.name,
            "timestep_hours": self.timestep_hours,
            "metadata": self.metadata,
        }
        if include_timeseries:
            payload["timeseries"] = [
                {
                    "timestamp": self.timestamps[i],
                    "settlement_price_eur_per_mwh": _round(
                        self.settlement_market.prices_eur_per_mwh[i]
                    ),
                }
                for i in range(self.intervals)
            ]
        return payload


@dataclass(frozen=True)
class BacktestEntry:
    product_id: str
    as_of: str
    portfolio_name: str
    method_name: str
    decision_market_name: str
    valuation_expected_value_eur: float
    valuation_risk_adjusted_value_eur: float
    cashflow_at_risk_eur: float
    conditional_value_at_risk_eur: float
    settled_cashflow_eur: float
    valuation_scenario_count: int
    settlement_dispatch: PortfolioDispatch
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def pricing_error_eur(self) -> float:
        """Settled schedule cashflow minus valuation expected value."""
        return self.settled_cashflow_eur - self.valuation_expected_value_eur

    @property
    def absolute_error_eur(self) -> float:
        return abs(self.pricing_error_eur)

    def to_dict(self, include_timeseries: bool = False) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "as_of": self.as_of,
            "portfolio_name": self.portfolio_name,
            "method": self.method_name,
            "decision_market_name": self.decision_market_name,
            "valuation_expected_value_eur": _round(
                self.valuation_expected_value_eur
            ),
            "valuation_risk_adjusted_value_eur": _round(
                self.valuation_risk_adjusted_value_eur
            ),
            "cashflow_at_risk_eur": _round(self.cashflow_at_risk_eur),
            "conditional_value_at_risk_eur": _round(
                self.conditional_value_at_risk_eur
            ),
            "settled_cashflow_eur": _round(self.settled_cashflow_eur),
            "pricing_error_eur": _round(self.pricing_error_eur),
            "absolute_error_eur": _round(self.absolute_error_eur),
            "valuation_scenario_count": self.valuation_scenario_count,
            "diagnostics": self.diagnostics,
            "settlement_dispatch": self.settlement_dispatch.to_dict(
                include_timeseries=include_timeseries
            ),
        }


@dataclass(frozen=True)
class BacktestResult:
    portfolio_name: str
    method_name: str
    entries: tuple[BacktestEntry, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def num_products(self) -> int:
        return len(self.entries)

    def metrics(self) -> dict[str, float | int]:
        if not self.entries:
            return {
                "num_products": 0,
                "total_valuation_expected_eur": 0.0,
                "total_settled_cashflow_eur": 0.0,
                "mean_valuation_expected_eur": 0.0,
                "mean_settled_cashflow_eur": 0.0,
                "mean_pricing_error_eur": 0.0,
                "mean_absolute_error_eur": 0.0,
                "root_mean_squared_error_eur": 0.0,
            }

        expected = [entry.valuation_expected_value_eur for entry in self.entries]
        settled = [entry.settled_cashflow_eur for entry in self.entries]
        errors = [entry.pricing_error_eur for entry in self.entries]
        n = len(self.entries)
        return {
            "num_products": n,
            "total_valuation_expected_eur": _round(sum(expected)),
            "total_settled_cashflow_eur": _round(sum(settled)),
            "mean_valuation_expected_eur": _round(sum(expected) / n),
            "mean_settled_cashflow_eur": _round(sum(settled) / n),
            "mean_pricing_error_eur": _round(sum(errors) / n),
            "mean_absolute_error_eur": _round(
                sum(abs(error) for error in errors) / n
            ),
            "root_mean_squared_error_eur": _round(
                sqrt(sum(error * error for error in errors) / n)
            ),
        }

    def to_dict(self, include_timeseries: bool = False) -> dict[str, Any]:
        return {
            "portfolio_name": self.portfolio_name,
            "method": self.method_name,
            "metrics": self.metrics(),
            "parameters": self.parameters,
            "diagnostics": self.diagnostics,
            "products": [
                entry.to_dict(include_timeseries=include_timeseries)
                for entry in self.entries
            ],
        }


def run_backtest(
    portfolio: VirtualPowerPlant,
    products: Iterable[HistoricalMarketProduct],
    method: PricingMethod | None = None,
    *,
    risk_aversion: float = 0.0,
    alpha: float = 0.05,
) -> BacktestResult:
    product_list = tuple(products)
    if not product_list:
        raise ValueError("at least one historical market product is required")

    pricing_method = method if method is not None else IntrinsicPricing()
    entries: list[BacktestEntry] = []

    for product in product_list:
        pricing_result = pricing_method.price(
            portfolio,
            list(product.valuation_markets),
            risk_aversion=risk_aversion,
            alpha=alpha,
        )
        decision_market = product.decision_market
        decision_dispatch = _select_decision_dispatch(
            pricing_result,
            decision_market.name,
        )
        settlement_dispatch = settle_dispatch_against_market(
            decision_dispatch,
            product.settlement_market,
        )
        entries.append(
            BacktestEntry(
                product_id=product.product_id,
                as_of=product.as_of,
                portfolio_name=portfolio.name,
                method_name=pricing_result.method_name,
                decision_market_name=decision_market.name,
                valuation_expected_value_eur=pricing_result.expected_value_eur,
                valuation_risk_adjusted_value_eur=(
                    pricing_result.risk_adjusted_value_eur
                ),
                cashflow_at_risk_eur=pricing_result.cashflow_at_risk_eur,
                conditional_value_at_risk_eur=(
                    pricing_result.conditional_value_at_risk_eur
                ),
                settled_cashflow_eur=settlement_dispatch.total_cashflow_eur,
                valuation_scenario_count=pricing_result.num_scenarios,
                settlement_dispatch=settlement_dispatch,
                diagnostics={
                    "settlement_basis": "decision_schedule_repriced_on_settlement_market",
                    "settlement_caveat": (
                        "The dispatch schedule is selected from valuation-time "
                        "data and is not re-optimized on settlement prices."
                    ),
                },
            )
        )

    return BacktestResult(
        portfolio_name=portfolio.name,
        method_name=pricing_method.name,
        entries=tuple(entries),
        parameters={"risk_aversion": risk_aversion, "alpha": alpha},
        diagnostics={
            "num_products": len(entries),
            "settlement_basis": "decision_schedule_repriced_on_settlement_market",
        },
    )


def settle_dispatch_against_market(
    dispatch: PortfolioDispatch,
    settlement_market: MarketData,
) -> PortfolioDispatch:
    """Settle a fixed dispatch schedule against realized market prices."""
    _validate_market_alignment(
        dispatch,
        settlement_market,
        context="dispatch and settlement market",
    )
    return PortfolioDispatch(
        portfolio_name=dispatch.portfolio_name,
        market_name=settlement_market.name,
        timestamps=settlement_market.timestamps,
        prices_eur_per_mwh=settlement_market.prices_eur_per_mwh,
        timestep_hours=settlement_market.timestep_hours,
        asset_dispatches=tuple(
            _settle_asset_dispatch(asset, settlement_market)
            for asset in dispatch.asset_dispatches
        ),
    )


def load_historical_market_csv(
    path: str | Path,
    *,
    product_column: str = "product_id",
    as_of_column: str = "as_of",
    timestamp_column: str = "timestamp",
    valuation_price_column: str = "valuation_price_eur_per_mwh",
    settlement_price_column: str = "settlement_price_eur_per_mwh",
    scenario_column: str | None = None,
    probability_column: str | None = None,
    timestep_hours: float = 1.0,
    decision_market_name: str | None = None,
) -> list[HistoricalMarketProduct]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} has no header row")
        fieldnames = set(reader.fieldnames)
        required = {
            product_column,
            as_of_column,
            timestamp_column,
            valuation_price_column,
            settlement_price_column,
        }
        if scenario_column is not None:
            required.add(scenario_column)
        if probability_column is not None:
            required.add(probability_column)
        missing = required - fieldnames
        if missing:
            raise ValueError(f"{csv_path} misses required columns: {sorted(missing)}")
        rows = list(reader)

    if not rows:
        raise ValueError(f"{csv_path} contains no historical product rows")

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        product_id = row[product_column] or "product"
        as_of = row[as_of_column] or "as_of"
        grouped.setdefault((product_id, as_of), []).append(row)

    products: list[HistoricalMarketProduct] = []
    for (product_id, as_of), product_rows in grouped.items():
        timestamps: list[str] = []
        settlement_by_timestamp: dict[str, float] = {}
        for row in product_rows:
            timestamp = row[timestamp_column]
            price = float(row[settlement_price_column])
            if timestamp not in settlement_by_timestamp:
                timestamps.append(timestamp)
                settlement_by_timestamp[timestamp] = price
            elif not isclose(
                settlement_by_timestamp[timestamp],
                price,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    f"product {product_id!r} has inconsistent settlement prices "
                    f"for timestamp {timestamp!r}"
                )

        scenario_rows: dict[str, list[dict[str, str]]] = {}
        for row in product_rows:
            scenario = row.get(scenario_column, "base") if scenario_column else "base"
            scenario_rows.setdefault(scenario or "base", []).append(row)

        valuation_markets: list[MarketData] = []
        for scenario_name, rows_for_scenario in scenario_rows.items():
            price_by_timestamp: dict[str, float] = {}
            probabilities: list[float] = []
            for row in rows_for_scenario:
                timestamp = row[timestamp_column]
                if timestamp in price_by_timestamp:
                    raise ValueError(
                        f"product {product_id!r}, scenario {scenario_name!r} "
                        f"has duplicate timestamp {timestamp!r}"
                    )
                price_by_timestamp[timestamp] = float(row[valuation_price_column])
                if probability_column is not None:
                    probabilities.append(float(row[probability_column]))

            missing_timestamps = sorted(set(timestamps) - set(price_by_timestamp))
            extra_timestamps = sorted(set(price_by_timestamp) - set(timestamps))
            if missing_timestamps or extra_timestamps:
                raise ValueError(
                    f"product {product_id!r}, scenario {scenario_name!r} does not "
                    "align with settlement timestamps"
                )

            probability = 1.0
            if probabilities:
                first_probability = probabilities[0]
                if any(
                    abs(probability - first_probability) > 1e-12
                    for probability in probabilities
                ):
                    raise ValueError(
                        f"product {product_id!r}, scenario {scenario_name!r} has "
                        "inconsistent probabilities"
                    )
                probability = first_probability

            valuation_markets.append(
                MarketData(
                    timestamps=tuple(timestamps),
                    prices_eur_per_mwh=tuple(
                        price_by_timestamp[timestamp] for timestamp in timestamps
                    ),
                    timestep_hours=timestep_hours,
                    name=scenario_name,
                    probability=probability,
                )
            )

        products.append(
            HistoricalMarketProduct(
                product_id=product_id,
                as_of=as_of,
                valuation_markets=_normalize_market_probabilities(valuation_markets),
                settlement_market=MarketData(
                    timestamps=tuple(timestamps),
                    prices_eur_per_mwh=tuple(
                        settlement_by_timestamp[timestamp] for timestamp in timestamps
                    ),
                    timestep_hours=timestep_hours,
                    name=f"{product_id}_settlement",
                ),
                decision_market_name=decision_market_name,
                metadata={"source_file": str(csv_path)},
            )
        )

    return products


def _select_decision_dispatch(
    pricing_result: PricingResult,
    decision_market_name: str,
) -> PortfolioDispatch:
    for dispatch in pricing_result.scenario_results:
        if dispatch.market_name == decision_market_name:
            return dispatch
    raise ValueError(
        f"pricing method {pricing_result.method_name!r} did not return a dispatch "
        f"for decision market {decision_market_name!r}"
    )


def _settle_asset_dispatch(
    asset: AssetDispatch,
    settlement_market: MarketData,
) -> AssetDispatch:
    cashflows = tuple(
        _settled_asset_cashflow(asset, price, power, settlement_market.timestep_hours)
        for price, power in zip(
            settlement_market.prices_eur_per_mwh,
            asset.power_mw,
        )
    )
    metadata = dict(asset.metadata)
    metadata.update(
        {
            "settlement_market_name": settlement_market.name,
            "settlement_basis": "fixed_dispatch_schedule",
        }
    )
    return AssetDispatch(
        asset_name=asset.asset_name,
        asset_type=asset.asset_type,
        power_mw=asset.power_mw,
        cashflow_eur=cashflows,
        metadata=metadata,
    )


def _settled_asset_cashflow(
    asset: AssetDispatch,
    price_eur_per_mwh: float,
    power_mw: float,
    timestep_hours: float,
) -> float:
    metadata = asset.metadata
    asset_type = asset.asset_type

    if asset_type == "renewable":
        variable_om = _finite_metadata_float(
            metadata,
            "variable_om_eur_per_mwh",
            default=0.0,
        )
        return (price_eur_per_mwh - variable_om) * power_mw * timestep_hours

    if asset_type == "fixed_load":
        return price_eur_per_mwh * power_mw * timestep_hours

    if asset_type == "flexible_load":
        energy_mwh = _finite_metadata_float(
            metadata,
            "energy_mwh",
            default=sum(abs(power) * timestep_hours for power in asset.power_mw),
        )
        gross_value = _finite_metadata_float(
            metadata,
            "gross_consumption_value_eur",
            default=0.0,
        )
        value_eur_per_mwh = gross_value / energy_mwh if energy_mwh > 0 else 0.0
        return (
            price_eur_per_mwh * power_mw + value_eur_per_mwh * abs(power_mw)
        ) * timestep_hours

    if asset_type == "generator":
        marginal_cost = _finite_metadata_float(
            metadata,
            "marginal_cost_eur_per_mwh",
            default=0.0,
        )
        return (price_eur_per_mwh - marginal_cost) * power_mw * timestep_hours

    if asset_type == "battery":
        cycle_cost = _finite_metadata_float(
            metadata,
            "cycle_cost_eur_per_mwh",
            default=0.0,
        )
        return (
            price_eur_per_mwh * power_mw
            - cycle_cost * abs(power_mw)
        ) * timestep_hours

    return price_eur_per_mwh * power_mw * timestep_hours


def _finite_metadata_float(
    metadata: dict[str, Any],
    key: str,
    *,
    default: float,
) -> float:
    value = float(metadata.get(key, default))
    if not isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def _normalize_market_probabilities(markets: Iterable[MarketData]) -> tuple[MarketData, ...]:
    market_list = list(markets)
    total_probability = sum(market.probability for market in market_list)
    if total_probability <= 0:
        probability = 1.0 / len(market_list)
        return tuple(_market_with_probability(market, probability) for market in market_list)
    return tuple(
        _market_with_probability(market, market.probability / total_probability)
        for market in market_list
    )


def _market_with_probability(market: MarketData, probability: float) -> MarketData:
    return MarketData(
        timestamps=market.timestamps,
        prices_eur_per_mwh=market.prices_eur_per_mwh,
        timestep_hours=market.timestep_hours,
        name=market.name,
        probability=probability,
    )


def _validate_market_alignment(
    left: MarketData | PortfolioDispatch,
    right: MarketData,
    *,
    context: str,
) -> None:
    if left.timestamps != right.timestamps:
        raise ValueError(f"{context} must use identical timestamps")
    if not isclose(
        left.timestep_hours,
        right.timestep_hours,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(f"{context} must use identical timesteps")
