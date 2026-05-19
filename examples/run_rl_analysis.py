#!/usr/bin/env python3
"""Run focused analyses for the tabular RL battery-dispatch baseline.

Usage:
    PYTHONPATH=src python examples/run_rl_analysis.py

The script intentionally uses only the standard library and the local package.
It prints compact tables that can be copied into the README when the RL
baseline or scenarios change.
"""

from __future__ import annotations

from html import escape
from math import ceil, floor, log10
import sys
from pathlib import Path
from statistics import mean, median, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vpp_pricing import (  # noqa: E402
    IntrinsicPricing,
    RollingIntrinsicPricing,
    VirtualPowerPlant,
    load_market_csv,
)
from vpp_pricing.methods.reinforcement_learning import (  # noqa: E402
    ReinforcementLearningPricing,
)


ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "docs" / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)


def _capture_pct(value: float, benchmark: float) -> float:
    if abs(benchmark) <= 1e-9:
        return 0.0
    return 100.0 + (value - benchmark) / abs(benchmark) * 100.0


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def _fmt0(value: float) -> str:
    return f"{value:,.0f}"


def _svg_text(
    x: float,
    y: float,
    text: object,
    *,
    size: int = 12,
    fill: str = "#263238",
    anchor: str = "middle",
    weight: str = "400",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-family="Arial, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}">{escape(str(text))}</text>'
    )


def _write_svg(filename: str, width: int, height: int, elements: list[str]) -> None:
    payload = "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            *elements,
            "</svg>",
        ]
    )
    (IMG_DIR / filename).write_text(payload, encoding="utf-8")
    print(f"Chart saved: docs/img/{filename}")


def _nice_bounds(values: list[float]) -> tuple[float, float]:
    low = min(values)
    high = max(values)
    if low == high:
        return low - 1.0, high + 1.0
    span = high - low
    raw_step = span / 5.0
    magnitude = 10 ** floor(log10(raw_step)) if raw_step > 0 else 1
    candidates = [1, 2, 5, 10]
    nice_step = min(candidates, key=lambda c: abs(c * magnitude - raw_step)) * magnitude
    return floor(low / nice_step) * nice_step, ceil(high / nice_step) * nice_step


def _interp_color(low: str, high: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    low_rgb = tuple(int(low[i : i + 2], 16) for i in (1, 3, 5))
    high_rgb = tuple(int(high[i : i + 2], 16) for i in (1, 3, 5))
    rgb = tuple(round(a + (b - a) * ratio) for a, b in zip(low_rgb, high_rgb))
    return "#" + "".join(f"{v:02X}" for v in rgb)


def _value_color(value: float, max_abs: float) -> str:
    if max_abs <= 0:
        return "#ECEFF1"
    if value < 0:
        return _interp_color("#ECEFF1", "#C94035", abs(value) / max_abs)
    return _interp_color("#ECEFF1", "#287C71", value / max_abs)


def _plot_episode_sensitivity(
    rows: list[dict[str, float]],
    *,
    intrinsic_ev: float,
    rolling_6h_ev: float,
) -> None:
    width, height = 900, 430
    left, right, top, bottom = 86, 35, 52, 76
    plot_w = width - left - right
    plot_h = height - top - bottom
    y_values = [row["ev"] for row in rows] + [intrinsic_ev, rolling_6h_ev, 0.0]
    y_min, y_max = _nice_bounds(y_values)

    def x_pos(idx: int) -> float:
        return left + idx * plot_w / (len(rows) - 1)

    def y_pos(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    elements = [
        _svg_text(width / 2, 26, "RL episode sensitivity - storage stress case", size=17, weight="700"),
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#455A64" stroke-width="1"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#455A64" stroke-width="1"/>',
    ]
    for i in range(6):
        value = y_min + (y_max - y_min) * i / 5
        y = y_pos(value)
        elements.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#CFD8DC" stroke-width="1"/>'
        )
        elements.append(_svg_text(left - 12, y + 4, _fmt0(value), anchor="end", size=11))
    if y_min <= 0 <= y_max:
        y = y_pos(0.0)
        elements.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#78909C" stroke-width="1.2" stroke-dasharray="4 4"/>'
        )

    for label, value, color in (
        ("Intrinsic", intrinsic_ev, "#1976D2"),
        ("Rolling 6h", rolling_6h_ev, "#388E3C"),
    ):
        y = y_pos(value)
        elements.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="{color}" stroke-width="1.6" stroke-dasharray="7 5"/>'
        )
        elements.append(_svg_text(left + plot_w - 3, y - 6, label, anchor="end", size=11, fill=color, weight="700"))

    points = " ".join(f"{x_pos(i):.1f},{y_pos(row['ev']):.1f}" for i, row in enumerate(rows))
    elements.append(f'<polyline points="{points}" fill="none" stroke="#C75000" stroke-width="3"/>')
    for i, row in enumerate(rows):
        x = x_pos(i)
        y = y_pos(row["ev"])
        elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#C75000" stroke="white" stroke-width="1.5"/>')
        elements.append(_svg_text(x, top + plot_h + 23, int(row["episodes"]), size=10))
        elements.append(_svg_text(x, y - 11, _fmt0(row["ev"]), size=10, fill="#C75000", weight="700"))

    elements.extend(
        [
            _svg_text(left + plot_w / 2, height - 18, "Training episodes", size=12, weight="700"),
            _svg_text(17, top + plot_h / 2, "E[V] EUR", size=12, weight="700", anchor="middle"),
        ]
    )
    _write_svg("rl_episode_sensitivity.svg", width, height, elements)


def _plot_discretization_heatmap(rows: list[dict[str, float]]) -> None:
    soc_values = sorted({int(row["soc_bins"]) for row in rows})
    price_values = sorted({int(row["price_bins"]) for row in rows})
    lookup = {(int(row["soc_bins"]), int(row["price_bins"])): row for row in rows}
    width, height = 720, 430
    left, top = 120, 78
    cell_w, cell_h = 132, 64
    max_abs = max(abs(row["ev"]) for row in rows)
    elements = [
        _svg_text(width / 2, 30, "RL discretisation sensitivity", size=17, weight="700"),
        _svg_text(width / 2, 52, "E[V] EUR, episodes=1,000, seed=42", size=12, fill="#546E7A"),
    ]
    for col, price_bins in enumerate(price_values):
        x = left + col * cell_w + cell_w / 2
        elements.append(_svg_text(x, top - 15, f"price {price_bins}", size=12, weight="700"))
    for row_idx, soc_bins in enumerate(soc_values):
        y = top + row_idx * cell_h + cell_h / 2
        elements.append(_svg_text(left - 16, y + 5, f"SOC {soc_bins}", anchor="end", size=12, weight="700"))
        for col, price_bins in enumerate(price_values):
            item = lookup[(soc_bins, price_bins)]
            x0 = left + col * cell_w
            y0 = top + row_idx * cell_h
            fill = _value_color(item["ev"], max_abs)
            text_fill = "white" if abs(item["ev"]) / max_abs > 0.62 else "#263238"
            elements.append(
                f'<rect x="{x0}" y="{y0}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="white" stroke-width="2"/>'
            )
            elements.append(_svg_text(x0 + cell_w / 2, y0 + 28, _fmt0(item["ev"]), size=14, fill=text_fill, weight="700"))
            elements.append(_svg_text(x0 + cell_w / 2, y0 + 48, f"{item['capture']:.1f}% cap", size=10, fill=text_fill))

    legend_x = left
    legend_y = top + len(soc_values) * cell_h + 32
    elements.extend(
        [
            f'<rect x="{legend_x}" y="{legend_y}" width="24" height="16" fill="#C94035"/>',
            _svg_text(legend_x + 34, legend_y + 13, "negative", anchor="start", size=11),
            f'<rect x="{legend_x + 130}" y="{legend_y}" width="24" height="16" fill="#ECEFF1" stroke="#B0BEC5"/>',
            _svg_text(legend_x + 164, legend_y + 13, "near zero", anchor="start", size=11),
            f'<rect x="{legend_x + 270}" y="{legend_y}" width="24" height="16" fill="#287C71"/>',
            _svg_text(legend_x + 304, legend_y + 13, "positive", anchor="start", size=11),
        ]
    )
    _write_svg("rl_discretization_heatmap.svg", width, height, elements)


def _plot_seed_sensitivity(rows: list[dict[str, float]], *, intrinsic_ev: float) -> None:
    width, height = 860, 420
    left, right, top, bottom = 80, 34, 52, 72
    plot_w = width - left - right
    plot_h = height - top - bottom
    y_min, y_max = _nice_bounds([row["ev"] for row in rows] + [0.0])

    def y_pos(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    bar_gap = 12
    bar_w = (plot_w - bar_gap * (len(rows) - 1)) / len(rows)
    elements = [
        _svg_text(width / 2, 27, "RL seed sensitivity", size=17, weight="700"),
        _svg_text(width / 2, 48, "episodes=1,000, SOC bins=11, price bins=8", size=12, fill="#546E7A"),
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#455A64" stroke-width="1"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#455A64" stroke-width="1"/>',
    ]
    for i in range(6):
        value = y_min + (y_max - y_min) * i / 5
        y = y_pos(value)
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#CFD8DC" stroke-width="1"/>')
        elements.append(_svg_text(left - 12, y + 4, _fmt0(value), anchor="end", size=11))
    y_zero = y_pos(0.0)
    elements.append(f'<line x1="{left}" y1="{y_zero:.1f}" x2="{left + plot_w}" y2="{y_zero:.1f}" stroke="#455A64" stroke-width="1.3"/>')

    for idx, row in enumerate(rows):
        x = left + idx * (bar_w + bar_gap)
        y_value = y_pos(row["ev"])
        fill = "#287C71" if row["ev"] >= 0 else "#C94035"
        y0 = min(y_zero, y_value)
        h = abs(y_zero - y_value)
        elements.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{fill}" opacity="0.9"/>')
        elements.append(_svg_text(x + bar_w / 2, top + plot_h + 24, int(row["seed"]), size=10))
        label_y = y_value - 8 if row["ev"] >= 0 else y_value + 18
        elements.append(_svg_text(x + bar_w / 2, label_y, _fmt0(row["ev"]), size=9, fill=fill, weight="700"))

    elements.extend(
        [
            _svg_text(left + plot_w / 2, height - 18, "Seed", size=12, weight="700"),
            _svg_text(17, top + plot_h / 2, "E[V] EUR", size=12, weight="700"),
            _svg_text(left + plot_w - 2, top + 15, f"Intrinsic reference: {_fmt0(intrinsic_ev)} EUR", anchor="end", size=11, fill="#1976D2", weight="700"),
        ]
    )
    _write_svg("rl_seed_sensitivity.svg", width, height, elements)


def _rl_result(
    portfolio: VirtualPowerPlant,
    markets,
    *,
    episodes: int,
    soc_bins: int = 11,
    price_bins: int = 8,
    seed: int = 42,
):
    return ReinforcementLearningPricing(
        episodes=episodes,
        soc_bins=soc_bins,
        price_bins=price_bins,
        seed=seed,
    ).price(portfolio, markets)


def main() -> int:
    portfolio = VirtualPowerPlant.from_json("examples/merchant_bess.json")
    markets = load_market_csv(
        "examples/data/extended_scenarios.csv",
        scenario_column="scenario",
        probability_column="probability",
    )

    intrinsic = IntrinsicPricing().price(portfolio, markets)
    intrinsic_ev = intrinsic.expected_value_eur

    print("Storage stress case / extended_scenarios.csv")
    print(f"Intrinsic E[V]: {_fmt(intrinsic_ev)} EUR")
    print()

    print("Benchmark methods")
    print("method, E[V] EUR, capture %, battery cycles")
    benchmark_evs = {"intrinsic": intrinsic_ev}
    print(
        "intrinsic, "
        f"{_fmt(intrinsic_ev)}, "
        f"{_capture_pct(intrinsic_ev, intrinsic_ev):.1f}, "
        f"{intrinsic.diagnostics['dispatch_battery_equivalent_cycles']:.3f}"
    )
    for window in (4, 6, 8):
        result = RollingIntrinsicPricing(window_hours=window).price(portfolio, markets)
        benchmark_evs[f"rolling_{window}h"] = result.expected_value_eur
        print(
            f"rolling_{window}h, "
            f"{_fmt(result.expected_value_eur)}, "
            f"{_capture_pct(result.expected_value_eur, intrinsic_ev):.1f}, "
            f"{result.diagnostics['dispatch_battery_equivalent_cycles']:.3f}"
        )

    print()
    print("RL episode sensitivity (soc_bins=11, price_bins=8, seed=42)")
    print("episodes, E[V] EUR, capture %, std EUR, battery cycles, state count")
    episode_rows: list[dict[str, float]] = []
    for episodes in (40, 100, 250, 500, 1000, 2000, 5000):
        result = _rl_result(portfolio, markets, episodes=episodes)
        episode_rows.append(
            {
                "episodes": float(episodes),
                "ev": result.expected_value_eur,
                "capture": _capture_pct(result.expected_value_eur, intrinsic_ev),
                "std": float(result.diagnostics["cashflow_std_eur"]),
                "cycles": float(result.diagnostics["dispatch_battery_equivalent_cycles"]),
                "state_count": float(result.diagnostics["rl_state_count"]),
            }
        )
        print(
            f"{episodes}, "
            f"{_fmt(result.expected_value_eur)}, "
            f"{_capture_pct(result.expected_value_eur, intrinsic_ev):.1f}, "
            f"{_fmt(result.diagnostics['cashflow_std_eur'])}, "
            f"{result.diagnostics['dispatch_battery_equivalent_cycles']:.3f}, "
            f"{result.diagnostics['rl_state_count']}"
        )

    print()
    print("RL discretisation sensitivity (episodes=1000, seed=42)")
    print("soc_bins, price_bins, E[V] EUR, capture %, battery cycles, state count")
    discretization_rows: list[dict[str, float]] = []
    for soc_bins, price_bins in (
        (5, 4),
        (5, 8),
        (5, 12),
        (9, 4),
        (9, 8),
        (9, 12),
        (11, 4),
        (11, 8),
        (11, 12),
        (21, 4),
        (21, 8),
        (21, 12),
    ):
        result = _rl_result(
            portfolio,
            markets,
            episodes=1000,
            soc_bins=soc_bins,
            price_bins=price_bins,
        )
        discretization_rows.append(
            {
                "soc_bins": float(soc_bins),
                "price_bins": float(price_bins),
                "ev": result.expected_value_eur,
                "capture": _capture_pct(result.expected_value_eur, intrinsic_ev),
                "cycles": float(result.diagnostics["dispatch_battery_equivalent_cycles"]),
                "state_count": float(result.diagnostics["rl_state_count"]),
            }
        )
        print(
            f"{soc_bins}, "
            f"{price_bins}, "
            f"{_fmt(result.expected_value_eur)}, "
            f"{_capture_pct(result.expected_value_eur, intrinsic_ev):.1f}, "
            f"{result.diagnostics['dispatch_battery_equivalent_cycles']:.3f}, "
            f"{result.diagnostics['rl_state_count']}"
        )

    print()
    print("RL seed sensitivity (episodes=1000, soc_bins=11, price_bins=8)")
    values: list[float] = []
    seed_rows: list[dict[str, float]] = []
    for seed in range(1, 11):
        result = _rl_result(portfolio, markets, episodes=1000, seed=seed)
        values.append(result.expected_value_eur)
        seed_rows.append(
            {
                "seed": float(seed),
                "ev": result.expected_value_eur,
                "capture": _capture_pct(result.expected_value_eur, intrinsic_ev),
                "cycles": float(result.diagnostics["dispatch_battery_equivalent_cycles"]),
            }
        )
        print(
            f"seed={seed}, "
            f"E[V]={_fmt(result.expected_value_eur)} EUR, "
            f"capture={_capture_pct(result.expected_value_eur, intrinsic_ev):.1f}%, "
            f"cycles={result.diagnostics['dispatch_battery_equivalent_cycles']:.3f}"
        )
    print(
        "summary, "
        f"min={_fmt(min(values))}, "
        f"median={_fmt(median(values))}, "
        f"max={_fmt(max(values))}, "
        f"mean={_fmt(mean(values))}, "
        f"std={_fmt(pstdev(values))}"
    )

    print()
    result = _rl_result(portfolio, markets, episodes=1000)
    max_abs_power = 0.0
    terminal_socs = []
    min_soc = float("inf")
    max_soc = float("-inf")
    for scenario in result.scenario_results:
        for asset in scenario.asset_dispatches:
            if asset.asset_type != "battery":
                continue
            max_abs_power = max(max_abs_power, max(abs(p) for p in asset.power_mw))
            terminal_socs.append(asset.metadata["terminal_soc_mwh"])
            min_soc = min(min_soc, min(asset.metadata["soc_mwh"]))
            max_soc = max(max_soc, max(asset.metadata["soc_mwh"]))

    print("RL feasibility check (episodes=1000, soc_bins=11, price_bins=8, seed=42)")
    print(f"max_abs_power_mw={max_abs_power:.2f}")
    print(f"terminal_socs_mwh={terminal_socs}")
    print(f"soc_range_mwh={min_soc:.2f}..{max_soc:.2f}")
    print(f"warnings={result.diagnostics['rl_warnings']}")

    print()
    print("Generating SVG charts...")
    _plot_episode_sensitivity(
        episode_rows,
        intrinsic_ev=intrinsic_ev,
        rolling_6h_ev=benchmark_evs["rolling_6h"],
    )
    _plot_discretization_heatmap(discretization_rows)
    _plot_seed_sensitivity(seed_rows, intrinsic_ev=intrinsic_ev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
