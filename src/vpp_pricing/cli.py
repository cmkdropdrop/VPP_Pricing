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
        default=["intrinsic", "rolling_intrinsic", "monte_carlo", "gan"],
        help="pricing methods to compare (default: intrinsic, rolling, MC, GAN)",
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
    compare_parser.add_argument(
        "--mc-price-floor",
        type=float,
        default=20.0,
        help=(
            "minimum shifted price level for the displaced-lognormal MC process "
            "(EUR/MWh)"
        ),
    )
    compare_parser.add_argument(
        "--mc-dispatch-window-hours",
        type=float,
        default=None,
        help=(
            "if set, dispatch MC paths with a rolling VPP look-ahead window "
            "instead of full-path perfect foresight"
        ),
    )
    compare_parser.add_argument(
        "--gan-paths",
        type=int,
        default=200,
        help="number of GAN-generated price paths",
    )
    compare_parser.add_argument(
        "--gan-epochs",
        type=int,
        default=250,
        help="training epochs for the dependency-free GAN baseline",
    )
    compare_parser.add_argument(
        "--gan-latent-dim",
        type=int,
        default=8,
        help="latent dimension for GAN price-curve generation",
    )
    compare_parser.add_argument(
        "--gan-learning-rate",
        type=float,
        default=0.01,
        help="learning rate for generator and discriminator updates",
    )
    compare_parser.add_argument(
        "--gan-seed",
        type=int,
        default=42,
        help="random seed for GAN training and generation",
    )
    compare_parser.add_argument(
        "--gan-dispatch-window-hours",
        type=float,
        default=None,
        help=(
            "if set, dispatch GAN paths with a rolling VPP look-ahead window "
            "instead of full-path perfect foresight"
        ),
    )
    compare_parser.add_argument(
        "--rl-episodes",
        type=int,
        default=500,
        help="training episodes for the tabular RL battery baseline",
    )
    compare_parser.add_argument(
        "--rl-learning-rate",
        type=float,
        default=0.20,
        help="Q-learning update step size for RL",
    )
    compare_parser.add_argument(
        "--rl-discount-factor",
        type=float,
        default=0.95,
        help="future-reward discount factor for RL",
    )
    compare_parser.add_argument(
        "--rl-epsilon",
        type=float,
        default=0.25,
        help="initial epsilon-greedy exploration rate for RL",
    )
    compare_parser.add_argument(
        "--rl-epsilon-decay",
        type=float,
        default=0.995,
        help="per-episode epsilon decay for RL",
    )
    compare_parser.add_argument(
        "--rl-soc-bins",
        type=int,
        default=11,
        help="number of state-of-charge bins for RL",
    )
    compare_parser.add_argument(
        "--rl-price-bins",
        type=int,
        default=8,
        help="number of price quantile bins for RL",
    )
    compare_parser.add_argument(
        "--rl-seed",
        type=int,
        default=42,
        help="random seed for RL training",
    )

    validate_parser = subparsers.add_parser(
        "validate", help="validate portfolio JSON and market CSV inputs"
    )
    _add_input_args(validate_parser)
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="return a non-zero exit code when warnings are present",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="emit the validation report as JSON",
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


def _add_input_args(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument("--output", default=None, help="optional path for JSON report")


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    _add_input_args(parser)
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
    if args.command == "validate":
        return _cmd_validate(args, portfolio, markets)
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
                    price_floor_eur_per_mwh=args.mc_price_floor,
                    dispatch_window_hours=args.mc_dispatch_window_hours,
                )
            )
        elif name == "gan":
            method_instances.append(
                get_method(
                    name,
                    num_paths=args.gan_paths,
                    epochs=args.gan_epochs,
                    latent_dim=args.gan_latent_dim,
                    learning_rate=args.gan_learning_rate,
                    seed=args.gan_seed,
                    dispatch_window_hours=args.gan_dispatch_window_hours,
                )
            )
        elif name == "rl":
            method_instances.append(
                get_method(
                    name,
                    episodes=args.rl_episodes,
                    learning_rate=args.rl_learning_rate,
                    discount_factor=args.rl_discount_factor,
                    epsilon=args.rl_epsilon,
                    epsilon_decay=args.rl_epsilon_decay,
                    soc_bins=args.rl_soc_bins,
                    price_bins=args.rl_price_bins,
                    seed=args.rl_seed,
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


def _cmd_validate(args, portfolio, markets) -> int:
    from vpp_pricing.validation import validate_portfolio_and_markets

    report = validate_portfolio_and_markets(portfolio, markets)
    payload = report.to_dict()

    if args.output:
        _write_json(payload, args.output, quiet=args.json)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_validation_report(report)

    if report.has_errors:
        return 1
    if args.strict and report.warning_count:
        return 1
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


def _write_json(payload: dict, path: str, *, quiet: bool = False) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    if not quiet:
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

    print(f"\n{'=' * 110}")
    print(f"  VPP PRICING METHOD COMPARISON -- {result.portfolio_name}")
    print(f"{'=' * 110}")
    print(f"  Base scenarios: {result.num_scenarios}")
    table = result.summary_table()
    first_row = table[0] if table else {}
    asset_counts = first_row.get("asset_type_counts") or {}
    if asset_counts:
        asset_mix = ", ".join(
            f"{asset_type}={count}" for asset_type, count in asset_counts.items()
        )
        print(f"  Asset mix: {asset_mix}")
    print()

    header = (
        f"  {'Method':<22} {'Approach':<30} {'E[V] EUR':>12} {'Std EUR':>10} "
        f"{'CaR EUR':>12} {'CVaR EUR':>12} {'Capture%':>9}"
    )
    print(header)
    print(f"  {'-' * 108}")

    for row in table:
        approach = row.get("practical_approach") or "-"
        capture = row.get("capture_ratio_pct")
        capture_str = f"{capture:>8.1f}%" if capture is not None else "       -"
        print(
            f"  {row['method']:<22} "
            f"{approach:<30} "
            f"{row['expected_value_eur']:>12.2f} "
            f"{row['std_dev_eur']:>10.2f} "
            f"{row['CaR_eur']:>12.2f} "
            f"{row['CVaR_eur']:>12.2f} "
            f"{capture_str}"
        )

    print(f"\n  Portfolio dispatch diagnostics:")
    print(
        f"  {'Method':<22} {'Export MWh':>11} {'Import MWh':>11} "
        f"{'Capture EUR/MWh':>16} {'RES curt.':>10} {'Flex EUR':>10} {'Batt cyc.':>10}"
    )
    print(f"  {'-' * 104}")
    for row in table:
        print(
            f"  {row['method']:<22} "
            f"{row['export_mwh']:>11.2f} "
            f"{row['import_mwh']:>11.2f} "
            f"{row['capture_price_eur_per_mwh']:>16.2f} "
            f"{row['renewable_curtailed_mwh']:>10.2f} "
            f"{row['flexible_load_value_eur']:>10.2f} "
            f"{row['battery_equivalent_cycles']:>10.2f}"
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

    print(f"\n{'=' * 110}\n")


def _print_validation_report(report) -> None:
    status = "FAILED" if report.has_errors else "PASSED"
    print(f"\n{'=' * 88}")
    print(f"  VPP INPUT VALIDATION -- {report.portfolio_name} [{status}]")
    print(f"{'=' * 88}")
    print(f"  Assets: {report.asset_count}")
    print(f"  Market scenarios: {report.market_count}")

    diagnostics = report.diagnostics
    print(
        "  Horizon: "
        f"{diagnostics['horizon_intervals']} intervals, "
        f"{diagnostics['horizon_hours']:.2f} hours, "
        f"dt={diagnostics['timestep_hours']}"
    )
    print(
        "  Price range: "
        f"{diagnostics['market_price_min_eur_per_mwh']} to "
        f"{diagnostics['market_price_max_eur_per_mwh']} EUR/MWh"
    )
    print(f"  Asset types: {diagnostics['asset_types']}")

    if report.issues:
        print("\n  Findings:")
        for issue in report.issues:
            print(
                f"    [{issue.severity.upper():<7}] "
                f"{issue.code}: {issue.message}"
            )
    else:
        print("\n  No findings.")

    print(f"\n{'=' * 88}\n")


if __name__ == "__main__":
    raise SystemExit(main())
