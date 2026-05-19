#!/usr/bin/env python3
"""Run all analyses and generate charts for the README.

Usage:
    PYTHONPATH=src python examples/run_analyses.py

Outputs charts to docs/img/ and prints summary tables.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from vpp_pricing import (
    VirtualPowerPlant,
    load_market_csv,
    compare_methods,
    GANPricing,
    IntrinsicPricing,
    RollingIntrinsicPricing,
    MonteCarloPricing,
)

IMG_DIR = Path(__file__).resolve().parent.parent / "docs" / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)
CHART_DPI = 180

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#263238",
        "axes.labelcolor": "#263238",
        "axes.titlecolor": "#263238",
        "xtick.color": "#263238",
        "ytick.color": "#263238",
        "grid.color": "#B0BEC5",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "legend.frameon": True,
        "legend.framealpha": 0.92,
    }
)

# Consistent style
COLORS = {
    "deep_low": "#2196F3",
    "low": "#4CAF50",
    "base": "#FF9800",
    "high": "#F44336",
    "stress": "#9C27B0",
    "scarcity": "#9C27B0",
    "solar_surplus": "#2196F3",
    "heat_wave": "#F44336",
}
METHOD_COLORS = {
    "gan": "#5E35B1",
    "intrinsic": "#1976D2",
    "rolling_intrinsic": "#388E3C",
    "monte_carlo": "#E64A19",
}
METHOD_LABELS = {
    "gan": "GAN ML",
    "intrinsic": "Intrinsic (Benchmark)",
    "rolling_intrinsic": "Rolling Intrinsic",
    "monte_carlo": "MC (Rolling)",
}


def scenario_color(name: str) -> str:
    return COLORS.get(name, "#757575")


# Chart 1: Price curves for all market datasets
def plot_price_curves(
    csv_path: str,
    title: str,
    filename: str,
    *,
    scenario_col: str = "scenario",
    prob_col: str = "probability",
    timestep: float = 1.0,
):
    markets = load_market_csv(
        csv_path,
        scenario_column=scenario_col,
        probability_column=prob_col,
        timestep_hours=timestep,
    )

    fig, ax = plt.subplots(figsize=(12, 5))
    for m in markets:
        hours = [i * m.timestep_hours for i in range(m.intervals)]
        prob_pct = m.probability * 100
        label = f"{m.name} ({prob_pct:.0f}%)"
        ax.plot(hours, m.prices_eur_per_mwh, label=label,
                color=scenario_color(m.name), linewidth=1.5, alpha=0.85)

    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Hour", fontsize=11)
    ax.set_ylabel("EUR/MWh", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(IMG_DIR / filename, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: docs/img/{filename}")


# Chart 2: Comparison bar charts
def run_comparison(
    portfolio_path: str,
    csv_path: str,
    *,
    scenario_col: str = "scenario",
    prob_col: str = "probability",
    timestep: float = 1.0,
    mc_paths: int = 200,
    mc_vol: float = 0.15,
    gan_paths: int = 16,
    gan_epochs: int = 35,
    window_hours: float = 6.0,
    label: str = "",
):
    portfolio = VirtualPowerPlant.from_json(portfolio_path)
    markets = load_market_csv(
        csv_path,
        scenario_column=scenario_col,
        probability_column=prob_col,
        timestep_hours=timestep,
    )
    result = compare_methods(
        portfolio,
        markets,
        methods=[
            IntrinsicPricing(),
            RollingIntrinsicPricing(window_hours=window_hours),
            MonteCarloPricing(
                num_paths=mc_paths,
                volatility=mc_vol,
                seed=42,
                dispatch_window_hours=window_hours,
            ),
            GANPricing(
                num_paths=gan_paths,
                epochs=gan_epochs,
                seed=42,
                dispatch_window_hours=window_hours,
            ),
        ],
        alpha=0.05,
    )
    return result


def plot_comparison_bars(result, title: str, filename: str):
    table = result.summary_table()
    methods = [r["method"] for r in table]
    ev = [r["expected_value_eur"] for r in table]
    car = [r["CaR_eur"] for r in table]
    cvar = [r["CVaR_eur"] for r in table]
    std = [r["std_dev_eur"] for r in table]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: E[V] and risk metrics
    x = range(len(methods))
    width = 0.22
    colors_bar = [METHOD_COLORS.get(m, "#757575") for m in methods]

    ax1 = axes[0]
    bars_ev = ax1.bar([i - width for i in x], ev, width, label="E[V]",
                      color=colors_bar, alpha=0.9, edgecolor="white")
    bars_car = ax1.bar([i for i in x], car, width, label="CaR (5%)",
                       color=colors_bar, alpha=0.5, edgecolor="white")
    bars_cvar = ax1.bar([i + width for i in x], cvar, width, label="CVaR (5%)",
                        color=colors_bar, alpha=0.3, edgecolor="white")

    ax1.set_xticks(list(x))
    ax1.set_xticklabels([METHOD_LABELS.get(m, m) for m in methods], fontsize=9)
    ax1.set_ylabel("EUR", fontsize=11)
    ax1.set_title("Expected Value & Risk Metrics", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=9)
    ax1.grid(True, axis="y", alpha=0.3)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    # Right: Capture ratio and std
    ax2 = axes[1]
    capture = [r.get("capture_ratio_pct") for r in table]
    bar_colors = [METHOD_COLORS.get(m, "#757575") for m in methods]

    bars = ax2.bar(list(x), capture, 0.5, color=bar_colors, alpha=0.85, edgecolor="white")
    ax2.axhline(100, color="gray", linewidth=1, linestyle="--", label="Intrinsic = 100%")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels([METHOD_LABELS.get(m, m) for m in methods], fontsize=9)
    ax2.set_ylabel("Capture Ratio (%)", fontsize=11)
    ax2.set_title("Value Capture vs. Intrinsic Benchmark", fontsize=11, fontweight="bold")
    ax2.legend(fontsize=9)
    ax2.grid(True, axis="y", alpha=0.3)

    # Add value labels on bars
    for bar, val in zip(bars, capture):
        if val is not None:
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                     f"{val:.1f}%", ha="center", va="bottom", fontsize=10, fontweight="bold")

    fig.suptitle(title, fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(IMG_DIR / filename, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: docs/img/{filename}")


def plot_dispatch_profile(result, scenario_idx: int, title: str, filename: str):
    """Plot aggregate power profile for a single scenario."""
    # Use intrinsic result
    intrinsic = result.results["intrinsic"]
    rolling = result.results["rolling_intrinsic"]

    sr_i = intrinsic.scenario_results[scenario_idx]
    sr_r = rolling.scenario_results[scenario_idx]

    hours = [i * sr_i.timestep_hours for i in range(sr_i.intervals)]
    prices = sr_i.prices_eur_per_mwh

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                    gridspec_kw={"height_ratios": [1, 1.5]})

    # Top: prices
    ax1.fill_between(hours, prices, alpha=0.3, color="#FF9800")
    ax1.plot(hours, prices, color="#FF9800", linewidth=1.5, label="Price")
    ax1.set_ylabel("EUR/MWh", fontsize=10)
    ax1.set_title(title, fontsize=12, fontweight="bold")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(0, color="gray", linewidth=0.5, linestyle="--")

    # Bottom: aggregate power
    power_i = sr_i.aggregate_power_mw
    power_r = sr_r.aggregate_power_mw

    ax2.fill_between(hours, power_i, alpha=0.2, color=METHOD_COLORS["intrinsic"])
    ax2.plot(hours, power_i, color=METHOD_COLORS["intrinsic"], linewidth=1.5,
             label="Intrinsic", alpha=0.8)
    ax2.plot(hours, power_r, color=METHOD_COLORS["rolling_intrinsic"], linewidth=1.5,
             label="Rolling Intrinsic", linestyle="--", alpha=0.8)
    ax2.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax2.set_xlabel("Hour", fontsize=10)
    ax2.set_ylabel("MW (+ export / - import)", fontsize=10)
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(IMG_DIR / filename, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: docs/img/{filename}")


def plot_multi_portfolio_comparison(results_dict: dict, filename: str):
    """Bar chart comparing E[V] capture ratios across multiple portfolios."""
    portfolios = list(results_dict.keys())
    methods = ["intrinsic", "rolling_intrinsic", "monte_carlo", "gan"]

    fig, ax = plt.subplots(figsize=(14, 6))
    x = range(len(portfolios))
    width = min(0.8 / len(methods), 0.22)

    for i, method in enumerate(methods):
        captures = []
        for pname in portfolios:
            table = results_dict[pname].summary_table()
            row = next((r for r in table if r["method"] == method), None)
            captures.append(row["capture_ratio_pct"] if row and row["capture_ratio_pct"] else 0)

        offset = (i - (len(methods) - 1) / 2) * width
        bars = ax.bar([xi + offset for xi in x], captures, width,
                      label=METHOD_LABELS[method], color=METHOD_COLORS[method], alpha=0.85)
        for bar, val in zip(bars, captures):
            if val != 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.8,
                        f"{val:.0f}%", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax.axhline(100, color="gray", linewidth=1, linestyle="--", alpha=0.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(portfolios, fontsize=9, rotation=15, ha="right")
    ax.set_ylabel("Capture Ratio (%)", fontsize=11)
    ax.set_title("Value Capture Across VPP Archetypes", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(IMG_DIR / filename, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: docs/img/{filename}")


def plot_cross_portfolio_dispatch_diagnostics(results_dict: dict, filename: str):
    """Show capture-price and cycling diagnostics across portfolio archetypes."""
    portfolios = list(results_dict.keys())
    methods = ["intrinsic", "rolling_intrinsic", "monte_carlo", "gan"]
    x = range(len(portfolios))
    width = min(0.8 / len(methods), 0.22)

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    for i, method in enumerate(methods):
        capture_prices = []
        cycles = []
        for name in portfolios:
            row = next(
                r
                for r in results_dict[name].summary_table()
                if r["method"] == method
            )
            capture_prices.append(row["capture_price_eur_per_mwh"])
            cycles.append(row["battery_equivalent_cycles"])

        offset = [xi + (i - (len(methods) - 1) / 2) * width for xi in x]
        axes[0].bar(
            offset,
            capture_prices,
            width,
            label=METHOD_LABELS[method],
            color=METHOD_COLORS[method],
            alpha=0.85,
            edgecolor="white",
        )
        axes[1].bar(
            offset,
            cycles,
            width,
            label=METHOD_LABELS[method],
            color=METHOD_COLORS[method],
            alpha=0.85,
            edgecolor="white",
        )

    axes[0].set_title("Weighted Capture Price")
    axes[0].set_ylabel("EUR/MWh")
    axes[0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    axes[1].set_title("Expected Battery Equivalent Cycles")
    axes[1].set_ylabel("cycles over horizon")

    for ax in axes:
        ax.set_xticks(list(x))
        ax.set_xticklabels(portfolios, rotation=20, ha="right", fontsize=9)
        ax.grid(True, axis="y", alpha=0.3)
    axes[0].legend(fontsize=9, loc="upper left")

    fig.suptitle(
        "Cross-Portfolio Dispatch Diagnostics",
        fontsize=13,
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    fig.savefig(IMG_DIR / filename, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: docs/img/{filename}")


def plot_mc_policy_comparison(portfolio, markets, intrinsic_ev: float, filename: str):
    """Compare perfect-foresight MC against rolling-policy MC."""
    vols = [0.0, 0.10, 0.20, 0.30, 0.40]
    perfect = []
    rolling = []

    for vol in vols:
        perfect_result = MonteCarloPricing(
            num_paths=24,
            volatility=vol,
            seed=42,
        ).price(portfolio, markets)
        rolling_result = MonteCarloPricing(
            num_paths=24,
            volatility=vol,
            seed=42,
            dispatch_window_hours=4.0,
        ).price(portfolio, markets)
        perfect.append(perfect_result.expected_value_eur)
        rolling.append(rolling_result.expected_value_eur)
        print(
            "    "
            f"vol={vol:.2f}  "
            f"MC perfect={perfect[-1]:>10,.2f}  "
            f"MC rolling={rolling[-1]:>10,.2f}"
        )

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].plot(
        vols,
        perfect,
        "o-",
        color="#8E24AA",
        linewidth=2,
        markersize=7,
        label="MC perfect-foresight dispatch",
    )
    axes[0].plot(
        vols,
        rolling,
        "s-",
        color=METHOD_COLORS["monte_carlo"],
        linewidth=2,
        markersize=7,
        label="MC rolling dispatch (4h)",
    )
    axes[0].axhline(
        intrinsic_ev,
        color=METHOD_COLORS["intrinsic"],
        linewidth=1.5,
        linestyle="--",
        label=f"Base intrinsic ({intrinsic_ev:,.0f} EUR)",
    )
    axes[0].set_xlabel("Volatility (per sqrt-hour)")
    axes[0].set_ylabel("E[V] (EUR)")
    axes[0].set_title("Policy-Dependent MC Value")
    axes[0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    axes[0].legend(fontsize=9)
    axes[0].grid(True, alpha=0.3)

    perfect_uplift = [
        (value / intrinsic_ev - 1.0) * 100.0 if intrinsic_ev else 0.0
        for value in perfect
    ]
    rolling_uplift = [
        (value / intrinsic_ev - 1.0) * 100.0 if intrinsic_ev else 0.0
        for value in rolling
    ]
    axes[1].plot(
        vols,
        perfect_uplift,
        "o-",
        color="#8E24AA",
        linewidth=2,
        markersize=7,
        label="Perfect foresight",
    )
    axes[1].plot(
        vols,
        rolling_uplift,
        "s-",
        color=METHOD_COLORS["monte_carlo"],
        linewidth=2,
        markersize=7,
        label="Rolling dispatch",
    )
    axes[1].axhline(0, color="#455A64", linewidth=1, linestyle="--")
    axes[1].set_xlabel("Volatility (per sqrt-hour)")
    axes[1].set_ylabel("Uplift vs intrinsic (%)")
    axes[1].set_title("Apparent Uplift vs Base Intrinsic")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(fontsize=9)

    fig.suptitle(
        "Merchant BESS - Monte Carlo Dispatch Policy Effect",
        fontsize=13,
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    fig.savefig(IMG_DIR / filename, dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: docs/img/{filename}")


def format_eur(v):
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.2f}"


# MAIN

def main():
    base = Path(__file__).resolve().parent.parent
    ex = base / "examples"
    data = ex / "data"

    print("=" * 70)
    print("  VPP PRICING - FULL ANALYSIS")
    print("=" * 70)

    # 1. Price curve charts
    print("\n[1] Generating price curve charts...")

    plot_price_curves(
        str(data / "scenario_prices.csv"),
        "Original Scenarios - Winter Day (3 Scenarios)",
        "prices_original.png",
    )
    plot_price_curves(
        str(data / "extended_scenarios.csv"),
        "Extended Scenarios - Winter Day (5 Scenarios, Deep Tails)",
        "prices_extended.png",
    )
    plot_price_curves(
        str(data / "summer_day_scenarios.csv"),
        "Summer Day - Duck Curve (5 Scenarios)",
        "prices_summer.png",
    )
    plot_price_curves(
        str(data / "week_scenarios.csv"),
        "Winter Week - 7 Days (5 Scenarios)",
        "prices_week.png",
    )
    plot_price_curves(
        str(data / "quarter_hourly_scenarios.csv"),
        "Quarter-Hourly - Winter Day (15-min, 3 Scenarios)",
        "prices_quarter_hourly.png",
        timestep=0.25,
    )

    # 2. Portfolio comparisons
    print("\n[2] Running portfolio comparisons...")

    analyses = {
        "Demo VPP": {
            "portfolio": str(ex / "sample_portfolio.json"),
            "csv": str(data / "extended_scenarios.csv"),
            "mc_paths": 40,
            "window_hours": 6.0,
        },
        "Merchant BESS": {
            "portfolio": str(ex / "merchant_bess.json"),
            "csv": str(data / "extended_scenarios.csv"),
            "mc_paths": 40,
            "window_hours": 8.0,
        },
        "Renewable Hybrid": {
            "portfolio": str(ex / "renewable_hybrid.json"),
            "csv": str(data / "extended_scenarios.csv"),
            "mc_paths": 40,
            "window_hours": 6.0,
        },
        "Storage Only": {
            "portfolio": str(ex / "storage_only.json"),
            "csv": str(data / "extended_scenarios.csv"),
            "mc_paths": 40,
            "window_hours": 8.0,
        },
        "Industrial Site": {
            "portfolio": str(ex / "industrial_site.json"),
            "csv": str(data / "extended_scenarios.csv"),
            "mc_paths": 40,
            "window_hours": 6.0,
        },
        "Demand Response": {
            "portfolio": str(ex / "demand_response.json"),
            "csv": str(data / "extended_scenarios.csv"),
            "mc_paths": 40,
            "window_hours": 6.0,
        },
    }

    all_results = {}
    for label, cfg in analyses.items():
        print(f"\n  --- {label} ---")
        result = run_comparison(
            cfg["portfolio"],
            cfg["csv"],
            mc_paths=cfg["mc_paths"],
            window_hours=cfg["window_hours"],
        )
        all_results[label] = result

        # Print summary
        for row in result.summary_table():
            capture = row.get("capture_ratio_pct")
            cap_str = f"{capture:.1f}%" if capture else "  -"
            print(
                f"    {row['method']:<22} E[V]={row['expected_value_eur']:>10,.2f}  "
                f"Std={row['std_dev_eur']:>9,.2f}  CaR={row['CaR_eur']:>10,.2f}  "
                f"CVaR={row['CVaR_eur']:>10,.2f}  Capture={cap_str}"
            )

        # Per-portfolio chart
        safe_name = label.lower().replace(" ", "_")
        plot_comparison_bars(
            result,
            f"{label} - Method Comparison",
            f"comparison_{safe_name}.png",
        )

    # 3. Dispatch profiles
    print("\n[3] Generating dispatch profiles...")

    # Demo VPP base scenario dispatch
    plot_dispatch_profile(
        all_results["Demo VPP"],
        scenario_idx=2,  # base scenario (index 2 in 5-scenario set)
        title="Demo VPP - Base Scenario Dispatch Profile",
        filename="dispatch_demo_vpp.png",
    )
    plot_dispatch_profile(
        all_results["Merchant BESS"],
        scenario_idx=4,  # scarcity scenario
        title="Merchant BESS - Scarcity Scenario Dispatch",
        filename="dispatch_merchant_scarcity.png",
    )

    # 4. Cross-portfolio comparison
    print("\n[4] Cross-portfolio comparison chart...")
    plot_multi_portfolio_comparison(all_results, "cross_portfolio_capture.png")
    plot_cross_portfolio_dispatch_diagnostics(
        all_results,
        "cross_portfolio_dispatch_diagnostics.png",
    )

    # 5. Summer duck curve analysis
    print("\n[5] Summer duck curve analysis...")
    summer_result = run_comparison(
        str(ex / "renewable_hybrid.json"),
        str(data / "summer_day_scenarios.csv"),
        mc_paths=40,
        window_hours=4.0,
    )
    for row in summer_result.summary_table():
        capture = row.get("capture_ratio_pct")
        cap_str = f"{capture:.1f}%" if capture else "  -"
        print(
            f"    {row['method']:<22} E[V]={row['expected_value_eur']:>10,.2f}  "
            f"Capture={cap_str}"
        )
    plot_comparison_bars(
        summer_result,
        "Renewable Hybrid - Summer Duck Curve",
        "comparison_summer_hybrid.png",
    )
    plot_dispatch_profile(
        summer_result,
        scenario_idx=2,  # base scenario
        title="Renewable Hybrid - Summer Base Dispatch (Duck Curve)",
        filename="dispatch_summer_hybrid.png",
    )

    # 6. Quarter-hourly analysis
    print("\n[6] Quarter-hourly (15-min) analysis...")
    qh_result = run_comparison(
        str(ex / "quarter_hourly_portfolio.json"),
        str(data / "quarter_hourly_scenarios.csv"),
        timestep=0.25,
        mc_paths=40,
        window_hours=1.5,
    )
    for row in qh_result.summary_table():
        capture = row.get("capture_ratio_pct")
        cap_str = f"{capture:.1f}%" if capture else "  -"
        print(
            f"    {row['method']:<22} E[V]={row['expected_value_eur']:>10,.2f}  "
            f"Capture={cap_str}"
        )
    plot_comparison_bars(
        qh_result,
        "Quarter-Hourly Portfolio - 15-min Intervals",
        "comparison_quarter_hourly.png",
    )

    # 7. Window sensitivity analysis
    print("\n[7] Rolling intrinsic window sensitivity...")
    portfolio = VirtualPowerPlant.from_json(str(ex / "merchant_bess.json"))
    markets = load_market_csv(
        str(data / "extended_scenarios.csv"),
        scenario_column="scenario",
        probability_column="probability",
    )
    windows = [1, 2, 3, 4, 6, 8, 12, 16, 24]
    intrinsic_ev = IntrinsicPricing().price(portfolio, markets).expected_value_eur
    rolling_evs = []
    for w in windows:
        r = RollingIntrinsicPricing(window_hours=float(w)).price(portfolio, markets)
        capture = r.expected_value_eur / intrinsic_ev * 100 if intrinsic_ev else 0
        rolling_evs.append(capture)
        print(f"    window={w:>2}h  E[V]={r.expected_value_eur:>10,.2f}  Capture={capture:.1f}%")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(windows, rolling_evs, "o-", color=METHOD_COLORS["rolling_intrinsic"],
            linewidth=2, markersize=8)
    ax.axhline(100, color=METHOD_COLORS["intrinsic"], linewidth=1.5,
               linestyle="--", label="Intrinsic (100%)", alpha=0.7)
    ax.set_xlabel("Look-Ahead Window (hours)", fontsize=11)
    ax.set_ylabel("Capture Ratio (%)", fontsize=11)
    ax.set_title("Merchant BESS - Rolling Intrinsic Window Sensitivity",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(windows)
    for w, cap in zip(windows, rolling_evs):
        ax.annotate(f"{cap:.0f}%", (w, cap), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=9, fontweight="bold")
    fig.tight_layout()
    fig.savefig(IMG_DIR / "sensitivity_window.png", dpi=CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: docs/img/sensitivity_window.png")

    # 8. MC volatility sensitivity
    print("\n[8] Monte Carlo volatility sensitivity...")
    vols = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
    mc_evs = []
    mc_stds = []
    for vol in vols:
        r = MonteCarloPricing(
            num_paths=40,
            volatility=vol,
            seed=42,
            dispatch_window_hours=8.0,
        ).price(portfolio, markets)
        mc_evs.append(r.expected_value_eur)
        mc_stds.append(float(r.diagnostics.get("cashflow_std_eur", 0)))
        print(f"    vol={vol:.2f}  E[V]={r.expected_value_eur:>10,.2f}  Std={mc_stds[-1]:>9,.2f}")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    ax1.plot(vols, mc_evs, "o-", color=METHOD_COLORS["monte_carlo"], linewidth=2, markersize=8)
    ax1.axhline(intrinsic_ev, color=METHOD_COLORS["intrinsic"], linewidth=1.5,
                linestyle="--", label=f"Intrinsic ({intrinsic_ev:,.0f} EUR)", alpha=0.7)
    ax1.set_xlabel("Volatility (per sqrt-hour)", fontsize=11)
    ax1.set_ylabel("E[V] (EUR)", fontsize=11)
    ax1.set_title("MC Expected Value vs. Volatility", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    ax2.plot(vols, mc_stds, "s-", color=METHOD_COLORS["monte_carlo"], linewidth=2, markersize=8)
    ax2.set_xlabel("Volatility (per sqrt-hour)", fontsize=11)
    ax2.set_ylabel("Std Dev (EUR)", fontsize=11)
    ax2.set_title("MC Cashflow Dispersion vs. Volatility", fontsize=11, fontweight="bold")
    ax2.grid(True, alpha=0.3)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    fig.suptitle("Merchant BESS - Monte Carlo Volatility Sensitivity",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(
        IMG_DIR / "sensitivity_mc_volatility.png",
        dpi=CHART_DPI,
        bbox_inches="tight",
    )
    plt.close(fig)
    print(f"  Chart saved: docs/img/sensitivity_mc_volatility.png")

    print("\n[9] Monte Carlo dispatch policy comparison...")
    plot_mc_policy_comparison(
        portfolio,
        markets,
        intrinsic_ev,
        "mc_dispatch_policy_comparison.png",
    )

    # Summary
    print("\n" + "=" * 70)
    print("  ALL ANALYSES COMPLETE")
    print("=" * 70)
    charts = sorted(IMG_DIR.glob("*.png"))
    print(f"\n  {len(charts)} charts generated in docs/img/:")
    for c in charts:
        print(f"    - {c.name}")

    # Save JSON summary for README
    summary = {}
    for label, result in all_results.items():
        summary[label] = result.summary_table()
    summary["Summer: Renewable Hybrid"] = summer_result.summary_table()
    summary["Quarter-Hourly Portfolio"] = qh_result.summary_table()

    summary_path = base / "docs" / "analysis_results.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary JSON: docs/analysis_results.json")


if __name__ == "__main__":
    main()
