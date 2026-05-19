from __future__ import annotations

import csv
from dataclasses import dataclass
from math import isclose, isfinite
from pathlib import Path


@dataclass(frozen=True)
class MarketData:
    timestamps: tuple[str, ...]
    prices_eur_per_mwh: tuple[float, ...]
    timestep_hours: float = 1.0
    name: str = "base"
    probability: float = 1.0

    def __post_init__(self) -> None:
        if len(self.timestamps) != len(self.prices_eur_per_mwh):
            raise ValueError("timestamps and prices must have identical length")
        if not self.timestamps:
            raise ValueError("market data must contain at least one interval")
        if self.timestep_hours <= 0 or not isfinite(self.timestep_hours):
            raise ValueError("timestep_hours must be positive")
        if self.probability < 0:
            raise ValueError("scenario probability must not be negative")
        if not isfinite(self.probability):
            raise ValueError("scenario probability must be finite")
        object.__setattr__(self, "timestamps", tuple(str(v) for v in self.timestamps))
        prices = tuple(float(v) for v in self.prices_eur_per_mwh)
        if any(not isfinite(price) for price in prices):
            raise ValueError("prices must be finite")
        object.__setattr__(self, "prices_eur_per_mwh", prices)

    @property
    def intervals(self) -> int:
        return len(self.timestamps)


def validate_market_scenarios(
    markets: list[MarketData],
    *,
    require_aligned_time_index: bool = True,
) -> None:
    """Validate scenario-level consistency before pricing.

    Pricing outputs compare scenario cashflows as one distribution.  That only
    has a clean interpretation when scenarios cover the same delivery horizon
    with the same timestep.
    """
    if not markets:
        raise ValueError("at least one market scenario is required")

    first = markets[0]
    for market in markets[1:]:
        if not isclose(
            market.timestep_hours,
            first.timestep_hours,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("all market scenarios must use identical timesteps")
        if require_aligned_time_index and market.timestamps != first.timestamps:
            raise ValueError("all market scenarios must use identical timestamps")


def load_market_csv(
    path: str | Path,
    *,
    price_column: str = "price_eur_per_mwh",
    timestamp_column: str = "timestamp",
    scenario_column: str | None = None,
    probability_column: str | None = None,
    timestep_hours: float = 1.0,
) -> list[MarketData]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} has no header row")
        fieldnames = set(reader.fieldnames)
        missing = {price_column, timestamp_column} - fieldnames
        if scenario_column is not None and scenario_column not in fieldnames:
            missing.add(scenario_column)
        if probability_column is not None and probability_column not in fieldnames:
            missing.add(probability_column)
        if missing:
            raise ValueError(f"{csv_path} misses required columns: {sorted(missing)}")
        rows = list(reader)

    if not rows:
        raise ValueError(f"{csv_path} contains no price rows")

    scenario_key = scenario_column if scenario_column in fieldnames else None
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        scenario_name = row.get(scenario_key, "base") if scenario_key else "base"
        grouped.setdefault(scenario_name or "base", []).append(row)

    markets: list[MarketData] = []
    for name, scenario_rows in grouped.items():
        probability = 1.0
        if probability_column and probability_column in scenario_rows[0]:
            probabilities = [float(row[probability_column]) for row in scenario_rows]
            if any(
                abs(probability - probabilities[0]) > 1e-12
                for probability in probabilities
            ):
                raise ValueError(f"scenario {name!r} has inconsistent probabilities")
            probability = probabilities[0]
        markets.append(
            MarketData(
                timestamps=tuple(row[timestamp_column] for row in scenario_rows),
                prices_eur_per_mwh=tuple(
                    float(row[price_column]) for row in scenario_rows
                ),
                timestep_hours=timestep_hours,
                name=name,
                probability=probability,
            )
        )

    total_probability = sum(m.probability for m in markets)
    if total_probability <= 0:
        equal_probability = 1.0 / len(markets)
        normalized_markets = [
            MarketData(
                timestamps=m.timestamps,
                prices_eur_per_mwh=m.prices_eur_per_mwh,
                timestep_hours=m.timestep_hours,
                name=m.name,
                probability=equal_probability,
            )
            for m in markets
        ]
        validate_market_scenarios(normalized_markets)
        return normalized_markets

    normalized_markets = [
        MarketData(
            timestamps=m.timestamps,
            prices_eur_per_mwh=m.prices_eur_per_mwh,
            timestep_hours=m.timestep_hours,
            name=m.name,
            probability=m.probability / total_probability,
        )
        for m in markets
    ]
    validate_market_scenarios(normalized_markets)
    return normalized_markets
