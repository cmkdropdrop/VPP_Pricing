from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vpp_pricing.assets import Asset, create_asset
from vpp_pricing.market import MarketData
from vpp_pricing.results import PortfolioDispatch


@dataclass(frozen=True)
class VirtualPowerPlant:
    name: str
    assets: tuple[Asset, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VirtualPowerPlant":
        assets = payload.get("assets")
        if not isinstance(assets, list) or not assets:
            raise ValueError("portfolio JSON must contain a non-empty assets list")
        return cls(
            name=str(payload.get("name", "Virtual Power Plant")),
            assets=tuple(create_asset(asset) for asset in assets),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "VirtualPowerPlant":
        json_path = Path(path)
        with json_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("portfolio JSON root must be an object")
        return cls.from_dict(payload)

    def dispatch(self, market: MarketData) -> PortfolioDispatch:
        asset_dispatches = tuple(asset.dispatch(market) for asset in self.assets)
        for dispatch in asset_dispatches:
            if dispatch.intervals != market.intervals:
                raise ValueError(
                    f"{dispatch.asset_name} returned {dispatch.intervals} intervals, "
                    f"expected {market.intervals}"
                )
        return PortfolioDispatch(
            portfolio_name=self.name,
            market_name=market.name,
            timestamps=market.timestamps,
            prices_eur_per_mwh=market.prices_eur_per_mwh,
            timestep_hours=market.timestep_hours,
            asset_dispatches=asset_dispatches,
        )
