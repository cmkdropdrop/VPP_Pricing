from __future__ import annotations

from dataclasses import dataclass, fields
from math import isclose, isfinite, sqrt
from typing import Any, Protocol

from vpp_pricing.market import MarketData
from vpp_pricing.results import AssetDispatch


class Asset(Protocol):
    name: str

    def dispatch(self, market: MarketData) -> AssetDispatch:
        ...


def _series(value: Any, length: int, field_name: str) -> tuple[float, ...]:
    if isinstance(value, (int, float)):
        coerced = _finite_float(value, field_name)
        return tuple(coerced for _ in range(length))
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a number or list")
    if len(value) == 1:
        coerced = _finite_float(value[0], field_name)
        return tuple(coerced for _ in range(length))
    if len(value) != length:
        raise ValueError(f"{field_name} has {len(value)} values, expected {length}")
    return tuple(_finite_float(v, field_name) for v in value)


def _finite_float(value: Any, field_name: str) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain numeric values") from exc
    if not isfinite(coerced):
        raise ValueError(f"{field_name} must contain finite values")
    return coerced


@dataclass(frozen=True)
class RenewableAsset:
    name: str
    capacity_mw: float
    availability: list[float] | float | None = None
    profile_mw: list[float] | float | None = None
    variable_om_eur_per_mwh: float = 0.0
    curtail_below_price_eur_per_mwh: float | None = None

    def dispatch(self, market: MarketData) -> AssetDispatch:
        if self.capacity_mw < 0:
            raise ValueError("capacity_mw must not be negative")
        if self.profile_mw is not None:
            raw_profile = _series(self.profile_mw, market.intervals, "profile_mw")
            profile = tuple(min(max(v, 0.0), self.capacity_mw) for v in raw_profile)
        else:
            availability = _series(
                1.0 if self.availability is None else self.availability,
                market.intervals,
                "availability",
            )
            profile = tuple(
                min(max(a, 0.0), 1.0) * self.capacity_mw for a in availability
            )

        power: list[float] = []
        cashflow: list[float] = []
        market_revenue = 0.0
        for price, output in zip(market.prices_eur_per_mwh, profile):
            dispatched = output
            if (
                self.curtail_below_price_eur_per_mwh is not None
                and price < self.curtail_below_price_eur_per_mwh
            ):
                dispatched = 0.0
            power.append(dispatched)
            market_revenue += price * dispatched * market.timestep_hours
            cashflow.append(
                (price - self.variable_om_eur_per_mwh)
                * dispatched
                * market.timestep_hours
            )

        available_mwh = sum(profile) * market.timestep_hours
        dispatched_mwh = sum(power) * market.timestep_hours
        capture_price = market_revenue / dispatched_mwh if dispatched_mwh else 0.0
        return AssetDispatch(
            asset_name=self.name,
            asset_type="renewable",
            power_mw=tuple(power),
            cashflow_eur=tuple(cashflow),
            metadata={
                "capacity_mw": self.capacity_mw,
                "available_mwh": round(available_mwh, 6),
                "dispatched_mwh": round(dispatched_mwh, 6),
                "curtailed_mwh": round(max(0.0, available_mwh - dispatched_mwh), 6),
                "capture_price_eur_per_mwh": round(capture_price, 6),
                "variable_om_eur_per_mwh": self.variable_om_eur_per_mwh,
            },
        )


@dataclass(frozen=True)
class FixedLoad:
    name: str
    profile_mw: list[float] | float

    def dispatch(self, market: MarketData) -> AssetDispatch:
        consumption = _series(self.profile_mw, market.intervals, "profile_mw")
        power = tuple(-max(v, 0.0) for v in consumption)
        cashflow = tuple(
            price * p * market.timestep_hours
            for price, p in zip(market.prices_eur_per_mwh, power)
        )
        return AssetDispatch(
            asset_name=self.name,
            asset_type="fixed_load",
            power_mw=power,
            cashflow_eur=cashflow,
            metadata={"energy_mwh": sum(consumption) * market.timestep_hours},
        )


@dataclass(frozen=True)
class FlexibleLoad:
    name: str
    energy_mwh: float
    min_power_mw: float
    max_power_mw: float
    value_eur_per_mwh: float = 0.0

    def dispatch(self, market: MarketData) -> AssetDispatch:
        if self.min_power_mw < 0 or self.max_power_mw < 0:
            raise ValueError("load power limits must not be negative")
        if self.min_power_mw > self.max_power_mw:
            raise ValueError("min_power_mw must be <= max_power_mw")

        dt = market.timestep_hours
        min_energy = self.min_power_mw * dt * market.intervals
        max_energy = self.max_power_mw * dt * market.intervals
        if self.energy_mwh < min_energy - 1e-9 or self.energy_mwh > max_energy + 1e-9:
            raise ValueError(
                f"energy_mwh={self.energy_mwh} is infeasible for bounds "
                f"[{min_energy}, {max_energy}]"
            )

        consumption = [self.min_power_mw for _ in range(market.intervals)]
        remaining_mwh = self.energy_mwh - min_energy
        cheapest_hours = sorted(
            range(market.intervals), key=lambda i: market.prices_eur_per_mwh[i]
        )
        for i in cheapest_hours:
            if remaining_mwh <= 1e-9:
                break
            add_mw = min(self.max_power_mw - self.min_power_mw, remaining_mwh / dt)
            consumption[i] += add_mw
            remaining_mwh -= add_mw * dt

        power = tuple(-mw for mw in consumption)
        cashflow = tuple(
            (price * p + self.value_eur_per_mwh * abs(p)) * dt
            for price, p in zip(market.prices_eur_per_mwh, power)
        )
        baseline_mw = self.energy_mwh / (dt * market.intervals)
        baseline_cost = sum(
            price * baseline_mw * dt for price in market.prices_eur_per_mwh
        )
        optimized_cost = sum(
            price * mw * dt
            for price, mw in zip(market.prices_eur_per_mwh, consumption)
        )
        gross_consumption_value = self.value_eur_per_mwh * self.energy_mwh

        return AssetDispatch(
            asset_name=self.name,
            asset_type="flexible_load",
            power_mw=power,
            cashflow_eur=cashflow,
            metadata={
                "energy_mwh": self.energy_mwh,
                "baseline_cost_eur": baseline_cost,
                "optimized_cost_eur": optimized_cost,
                "flex_value_eur": baseline_cost - optimized_cost,
                "gross_consumption_value_eur": gross_consumption_value,
            },
        )


@dataclass(frozen=True)
class DispatchableGenerator:
    name: str
    max_power_mw: float
    marginal_cost_eur_per_mwh: float
    min_margin_eur_per_mwh: float = 0.0

    def dispatch(self, market: MarketData) -> AssetDispatch:
        if self.max_power_mw < 0:
            raise ValueError("max_power_mw must not be negative")
        power: list[float] = []
        cashflow: list[float] = []
        trigger = self.marginal_cost_eur_per_mwh + self.min_margin_eur_per_mwh
        for price in market.prices_eur_per_mwh:
            output = self.max_power_mw if price >= trigger else 0.0
            power.append(output)
            cashflow.append(
                (price - self.marginal_cost_eur_per_mwh)
                * output
                * market.timestep_hours
            )
        return AssetDispatch(
            asset_name=self.name,
            asset_type="generator",
            power_mw=tuple(power),
            cashflow_eur=tuple(cashflow),
            metadata={"marginal_cost_eur_per_mwh": self.marginal_cost_eur_per_mwh},
        )


@dataclass(frozen=True)
class BatteryStorage:
    name: str
    capacity_mwh: float
    power_mw: float
    round_trip_efficiency: float = 0.9
    initial_soc_mwh: float = 0.0
    terminal_soc_mwh: float | None = None
    cycle_cost_eur_per_mwh: float = 0.0
    grid_points: int = 81

    def dispatch(self, market: MarketData) -> AssetDispatch:
        if self.capacity_mwh <= 0:
            raise ValueError("capacity_mwh must be positive")
        if self.power_mw < 0:
            raise ValueError("power_mw must not be negative")
        if not 0 < self.round_trip_efficiency <= 1:
            raise ValueError("round_trip_efficiency must be in (0, 1]")
        if self.grid_points < 2:
            raise ValueError("grid_points must be at least 2")

        terminal_soc = (
            self.initial_soc_mwh
            if self.terminal_soc_mwh is None
            else self.terminal_soc_mwh
        )
        for label, soc in (
            ("initial_soc_mwh", self.initial_soc_mwh),
            ("terminal_soc_mwh", terminal_soc),
        ):
            if soc < -1e-9 or soc > self.capacity_mwh + 1e-9:
                raise ValueError(f"{label} must be within [0, capacity_mwh]")

        states = self._state_grid(terminal_soc)
        initial_idx = min(range(len(states)), key=lambda i: abs(states[i] - self.initial_soc_mwh))
        terminal_idx = min(range(len(states)), key=lambda i: abs(states[i] - terminal_soc))
        charge_efficiency = sqrt(self.round_trip_efficiency)
        discharge_efficiency = sqrt(self.round_trip_efficiency)

        neg_inf = float("-inf")
        dp = [neg_inf for _ in states]
        dp[initial_idx] = 0.0
        parents: list[list[tuple[int, float, float] | None]] = []

        for price in market.prices_eur_per_mwh:
            next_dp = [neg_inf for _ in states]
            step_parent: list[tuple[int, float, float] | None] = [None for _ in states]
            for current_idx, value in enumerate(dp):
                if value == neg_inf:
                    continue
                current_soc = states[current_idx]
                for next_idx, next_soc in enumerate(states):
                    transition = self._transition(
                        current_soc=current_soc,
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

        if dp[terminal_idx] == neg_inf:
            raise ValueError("battery dispatch has no feasible path")

        path_power = [0.0 for _ in range(market.intervals)]
        path_cashflow = [0.0 for _ in range(market.intervals)]
        idx = terminal_idx
        for t in range(market.intervals - 1, -1, -1):
            parent = parents[t][idx]
            if parent is None:
                raise RuntimeError("battery path reconstruction failed")
            idx, path_power[t], path_cashflow[t] = parent

        throughput_mwh = sum(abs(power_mw) * market.timestep_hours for power_mw in path_power)
        return AssetDispatch(
            asset_name=self.name,
            asset_type="battery",
            power_mw=tuple(path_power),
            cashflow_eur=tuple(path_cashflow),
            metadata={
                "capacity_mwh": self.capacity_mwh,
                "power_mw": self.power_mw,
                "round_trip_efficiency": self.round_trip_efficiency,
                "initial_soc_mwh": states[initial_idx],
                "terminal_soc_mwh": states[terminal_idx],
                "cycle_cost_eur_per_mwh": self.cycle_cost_eur_per_mwh,
                "throughput_mwh": round(throughput_mwh, 6),
                "equivalent_cycles": round(
                    throughput_mwh / (2.0 * self.capacity_mwh), 6
                ),
            },
        )

    def _state_grid(self, terminal_soc: float) -> tuple[float, ...]:
        base = [
            self.capacity_mwh * i / (self.grid_points - 1)
            for i in range(self.grid_points)
        ]
        base.extend([0.0, self.capacity_mwh, self.initial_soc_mwh, terminal_soc])
        unique = sorted({round(min(max(v, 0.0), self.capacity_mwh), 10) for v in base})
        return tuple(unique)

    def _transition(
        self,
        *,
        current_soc: float,
        next_soc: float,
        price: float,
        timestep_hours: float,
        charge_efficiency: float,
        discharge_efficiency: float,
    ) -> tuple[float, float] | None:
        delta_soc = next_soc - current_soc
        if isclose(delta_soc, 0.0, abs_tol=1e-10):
            return 0.0, 0.0

        max_energy = self.power_mw * timestep_hours
        if delta_soc > 0:
            grid_import_mwh = delta_soc / charge_efficiency
            if grid_import_mwh > max_energy + 1e-9:
                return None
            power_mw = -grid_import_mwh / timestep_hours
            throughput_mwh = grid_import_mwh
            cashflow_eur = -price * grid_import_mwh
        else:
            grid_export_mwh = (-delta_soc) * discharge_efficiency
            if grid_export_mwh > max_energy + 1e-9:
                return None
            power_mw = grid_export_mwh / timestep_hours
            throughput_mwh = grid_export_mwh
            cashflow_eur = price * grid_export_mwh

        cashflow_eur -= self.cycle_cost_eur_per_mwh * throughput_mwh
        return power_mw, cashflow_eur


def create_asset(config: dict[str, Any]) -> Asset:
    if not isinstance(config, dict):
        raise ValueError("asset config must be an object")
    asset_type = str(config.get("type", "")).lower()
    if not asset_type:
        raise ValueError("asset config must include a type")
    payload = {key: value for key, value in config.items() if key != "type"}
    aliases = {
        "solar": "renewable",
        "wind": "renewable",
        "storage": "battery",
        "demand_response": "flexible_load",
        "load": "fixed_load",
        "peaker": "generator",
        "dispatchable_generator": "generator",
    }
    normalized = aliases.get(asset_type, asset_type)
    registry = {
        "renewable": RenewableAsset,
        "fixed_load": FixedLoad,
        "flexible_load": FlexibleLoad,
        "generator": DispatchableGenerator,
        "battery": BatteryStorage,
    }
    if normalized not in registry:
        raise ValueError(f"unsupported asset type: {asset_type!r}")
    return _build_asset(registry[normalized], payload, asset_type)


def _build_asset(
    asset_cls: type[Any],
    payload: dict[str, Any],
    asset_type: str,
) -> Asset:
    valid_fields = {field.name for field in fields(asset_cls)}
    unknown = sorted(set(payload) - valid_fields)
    if unknown:
        raise ValueError(
            f"{asset_type!r} asset has unsupported fields: {unknown}. "
            f"Allowed fields: {sorted(valid_fields)}"
        )
    try:
        return asset_cls(**payload)
    except TypeError as exc:
        raise ValueError(f"invalid {asset_type!r} asset config: {exc}") from exc
