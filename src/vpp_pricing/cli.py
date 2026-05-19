from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from vpp_pricing.market import load_market_csv
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.pricing import price_portfolio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vpp-price",
        description="VPP Pricing Research Toolkit -- model, price and compare "
        "Virtual Power Plant portfolios under different valuation methods.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ---- price (legacy single-method) ----
    price_parser = subparsers.add_parser(
        "price", help="price a VPP portfolio (intrinsic method)"
    )
    _add_common_args(price_parser)
    price_parser.add_argument(
        "--no-timeseries",
        action="store_true",
        help="omit interval-level data from JSON output",
    )

    # ---- compare (multi-method research) ----
    compare_parser = subparsers.add_parser(
        "compare", help="run multiple pricing methods side-by-side"
    )
    _add_common_args(compare_parser)
    compare_parser.add_argument(
        "--methods",
        nargs="+",
        default=["intrinsic", "rolling_intrinsic", "monte_carlo"],
        help="pricing methods to compare (default: all three)",
    )
    compare_parser.add_argument(
        "--window-hours",
        type=float,
        default=6.0,
        help="look-ahead window for rolling intrinsic (hours, supports sub-hourly)",
    )
    compare_parser.add_argument(
        "--mc-paths",
        type=int,
        default=200,
        help="number of Monte-Carlo price paths",
    )
    compare_parser.add_argument(
        "--mc-volatility",
        type=float,
        default=0.15,
        help="per-sqrt-hour volatility for MC price simulation",
    )
    compare_parser.add_argument(
        "--mc-seed",
        type=int,
        default=42,
        help="random seed for reproducibility",
    )
    compare_parser.add_argument(
        "--mc-mean-reversion",
        type=float,
        default=0.7,
        help="AR(1) mean-reversion coefficient for MC shock process (0-1)",
    )

    approaches_parser = subparsers.add_parser(
        "approaches", help="list practical VPP pricing approaches and risks"
    )
    approaches_parser.add_argument(
        "--implemented-only",
        action="store_true",
        help="only show approaches with an implemented pricing method",
    )
    approaches_parser.add_argument(
        "--json",
        action="store_true",
        help="emit the approach catalogue as JSON",
    )

    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("portfolio_json", help="path to portfolio JSON")
    parser.add_argument("market_csv", help="path to market price CSV")
    parser.add_argument(
        "--price-column", default="price_eur_per_mwh", help="CSV price column"
    )
    parser.add_argument(
        "--timestamp-column", default="timestamp", help="CSV timestamp column"
    )
    parser.add_argument(
        "--scenario-column", default=None, help="optional CSV scenario column"
    )
    parser.add_argument(
        "--probability-column", default=None, help="optional CSV probability column"
    )
    parser.add_argument(
        "--timestep-hours", type=float, default=1.0, help="interval length in hours"
    )
    parser.add_argument(
        "--risk-aversion",
        type=float,
        default=0.0,
        help="CVaR penalty weight for risk-adjusted value",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        help="lower-tail probability for CaR and CVaR",
    )
    parser.add_argument(
        "--output", default=None, help="optional path for JSON report"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "approaches":
        return _cmd_approaches(args)

    portfolio = VirtualPowerPlant.from_json(args.portfolio_json)
    markets = load_market_csv(
        args.market_csv,
        price_column=args.price_column,
        timestamp_column=args.timestamp_column,
        scenario_column=args.scenario_column,
        probability_column=args.probability_column,
        timestep_hours=args.timestep_hours,
    )

    if args.command == "price":
        return _cmd_price(args, portfolio, markets)
    if args.command == "compare":
        return _cmd_compare(args, portfolio, markets)
    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_price(args, portfolio, markets) -> int:
    quote = price_portfolio(
        portfolio,
        markets,
        risk_aversion=args.risk_aversion,
        alpha=args.alpha,
    )
    payload = quote.to_dict(include_timeseries=not args.no_timeseries)

    if args.output:
        _write_json(payload, args.output)

    _print_summary(payload)
    return 0


def _cmd_compare(args, portfolio, markets) -> int:
    from vpp_pricing.comparison import compare_methods
    from vpp_pricing.methods import get_method

    method_instances = []
    for name in args.methods:
        if name == "rolling_intrinsic":
            method_instances.append(get_method(name, window_hours=args.window_hours))
        elif name == "monte_carlo":
            method_instances.append(
                get_method(
                    name,
                    num_paths=args.mc_paths,
                    volatility=args.mc_volatility,
                    seed=args.mc_seed,
                    mean_reversion=args.mc_mean_reversion,
                )
            )
        else:
            method_instances.append(get_method(name))

    result = compare_methods(
        portfolio,
        markets,
        method_instances,
        risk_aversion=args.risk_aversion,
        alpha=args.alpha,
    )

    payload = result.to_dict(include_timeseries=False)
    if args.output:
        _write_json(payload, args.output)

    _print_comparison(result)
    return 0


def _cmd_approaches(args) -> int:
    from vpp_pricing.practical import list_practical_approaches

    approaches = list_practical_approaches(implemented_only=args.implemented_only)
    if args.json:
        print(json.dumps([approach.to_dict() for approach in approaches], indent=2))
        return 0

    print(f"\n{'=' * 98}")
    print("  PRACTICAL VPP PRICING APPROACHES")
    print(f"{'=' * 98}")
    print(
        f"  {'Approach':<29} {'Status':<22} {'Method':<18} "
        f"{'Economic relevance':<20}"
    )
    print(f"  {'-' * 96}")
    for approach in approaches:
        method = approach.implemented_method or "-"
        print(
            f"  {approach.id:<29} {approach.implementation_status:<22} "
            f"{method:<18} {approach.economic_relevance:<20}"
        )
    print("\n  Use --json for users, revenue streams, markets, and mispricing risks.\n")
    return 0


def _write_json(payload: dict, path: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print(f"Report written to {output_path}")


def _print_summary(payload: dict) -> None:
    print(f"Portfolio: {payload['portfolio_name']}")
    print(f"Expected cashflow: {payload['expected_cashflow_eur']:.2f} EUR")
    print(f"Cashflow at risk: {payload['cashflow_at_risk_eur']:.2f} EUR")
    print(f"CVaR: {payload['conditional_value_at_risk_eur']:.2f} EUR")
    print(f"Risk-adjusted value: {payload['risk_adjusted_value_eur']:.2f} EUR")
    print(f"Scenarios: {len(payload['scenarios'])}")
    if payload["scenarios"]:
        metrics = payload["scenarios"][0]["metrics"]
        print(f"Base net export: {metrics['net_export_mwh']:.2f} MWh")
        print(f"Base peak export: {metrics['peak_export_mw']:.2f} MW")
        print(f"Base peak import: {metrics['peak_import_mw']:.2f} MW")


def _print_comparison(result) -> None:
    from vpp_pricing.comparison import ComparisonResult

    print(f"\n{'=' * 98}")
    print(f"  VPP PRICING METHOD COMPARISON -- {result.portfolio_name}")
    print(f"{'=' * 98}")
    print(f"  Base scenarios: {result.num_scenarios}")
    print()

    header = (
        f"  {'Method':<22} {'Approach':<18} {'E[V] EUR':>12} {'Std EUR':>10} "
        f"{'CaR EUR':>12} {'CVaR EUR':>12} {'Capture%':>9}"
    )
    print(header)
    print(f"  {'-' * 96}")

    for row in result.summary_table():
        approach = row.get("practical_approach") or "-"
        capture = row.get("capture_ratio_pct")
        capture_str = f"{capture:>8.1f}%" if capture is not None else "       -"
        print(
            f"  {row['method']:<22} "
            f"{approach:<18} "
            f"{row['expected_value_eur']:>12.2f} "
            f"{row['std_dev_eur']:>10.2f} "
            f"{row['CaR_eur']:>12.2f} "
            f"{row['CVaR_eur']:>12.2f} "
            f"{capture_str}"
        )

    # Delta analysis vs intrinsic
    if "intrinsic" in result.results:
        intrinsic_ev = result.results["intrinsic"].expected_value_eur
        print(f"\n  Delta vs. intrinsic (perfect-foresight benchmark):")
        for name, res in result.results.items():
            if name == "intrinsic":
                continue
            delta = res.expected_value_eur - intrinsic_ev
            pct = (delta / abs(intrinsic_ev) * 100) if intrinsic_ev != 0 else 0
            print(f"    {name:<22} {delta:>+12.2f} EUR  ({pct:>+.1f}%)")

    # Mispricing warnings
    warnings = result.mispricing_warnings()
    if warnings:
        print(f"\n  Mispricing warnings:")
        for warning in warnings:
            print(f"    * {warning}")

    print(f"\n{'=' * 98}\n")


if __name__ == "__main__":
    raise SystemExit(main())
