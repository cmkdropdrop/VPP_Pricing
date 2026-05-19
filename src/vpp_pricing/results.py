from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


@dataclass(frozen=True)
class AssetDispatch:
    asset_name: str
    asset_type: str
    power_mw: tuple[float, ...]
    cashflow_eur: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_cashflow_eur(self) -> float:
        return float(sum(self.cashflow_eur))

    @property
    def intervals(self) -> int:
        return len(self.power_mw)

    def to_dict(self, timestamps: tuple[str, ...] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "asset_name": self.asset_name,
            "asset_type": self.asset_type,
            "total_cashflow_eur": _round(self.total_cashflow_eur),
            "metadata": self.metadata,
        }
        if timestamps is not None:
            payload["timeseries"] = [
                {
                    "timestamp": timestamps[i],
                    "power_mw": _round(self.power_mw[i]),
                    "cashflow_eur": _round(self.cashflow_eur[i]),
                }
                for i in range(self.intervals)
            ]
        return payload


@dataclass(frozen=True)
class PortfolioDispatch:
    portfolio_name: str
    market_name: str
    timestamps: tuple[str, ...]
    prices_eur_per_mwh: tuple[float, ...]
    timestep_hours: float
    asset_dispatches: tuple[AssetDispatch, ...]

    @property
    def intervals(self) -> int:
        return len(self.timestamps)

    @property
    def aggregate_power_mw(self) -> tuple[float, ...]:
        return tuple(
            sum(asset.power_mw[i] for asset in self.asset_dispatches)
            for i in range(self.intervals)
        )

    @property
    def cashflow_eur(self) -> tuple[float, ...]:
        return tuple(
            sum(asset.cashflow_eur[i] for asset in self.asset_dispatches)
            for i in range(self.intervals)
        )

    @property
    def total_cashflow_eur(self) -> float:
        return float(sum(self.cashflow_eur))

    def metrics(self) -> dict[str, float]:
        power = self.aggregate_power_mw
        cashflow = self.cashflow_eur
        dt = self.timestep_hours
        export_mwh = sum(max(p, 0.0) * dt for p in power)
        import_mwh = sum(max(-p, 0.0) * dt for p in power)
        export_revenue = sum(
            max(power[i], 0.0) * self.prices_eur_per_mwh[i] * dt
            for i in range(self.intervals)
        )
        import_cost = sum(
            max(-power[i], 0.0) * self.prices_eur_per_mwh[i] * dt
            for i in range(self.intervals)
        )
        return {
            "total_cashflow_eur": _round(sum(cashflow)),
            "export_mwh": _round(export_mwh),
            "import_mwh": _round(import_mwh),
            "net_export_mwh": _round(export_mwh - import_mwh),
            "peak_export_mw": _round(max(power) if power else 0.0),
            "peak_import_mw": _round(abs(min(power)) if power else 0.0),
            "average_export_price_eur_per_mwh": _round(
                export_revenue / export_mwh if export_mwh else 0.0
            ),
            "average_import_price_eur_per_mwh": _round(
                import_cost / import_mwh if import_mwh else 0.0
            ),
        }

    def to_dict(self, include_timeseries: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "portfolio_name": self.portfolio_name,
            "market_name": self.market_name,
            "timestep_hours": self.timestep_hours,
            "metrics": self.metrics(),
            "assets": [
                asset.to_dict(self.timestamps if include_timeseries else None)
                for asset in self.asset_dispatches
            ],
        }
        if include_timeseries:
            power = self.aggregate_power_mw
            cashflow = self.cashflow_eur
            payload["timeseries"] = [
                {
                    "timestamp": self.timestamps[i],
                    "price_eur_per_mwh": _round(self.prices_eur_per_mwh[i]),
                    "aggregate_power_mw": _round(power[i]),
                    "cashflow_eur": _round(cashflow[i]),
                }
                for i in range(self.intervals)
            ]
        return payload
