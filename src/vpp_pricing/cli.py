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
        description="Model and price Virtual Power Plant portfolios.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    price_parser = subparsers.add_parser("price", help="price a VPP portfolio")
    price_parser.add_argument("portfolio_json", help="path to portfolio JSON")
    price_parser.add_argument("market_csv", help="path to market price CSV")
    price_parser.add_argument(
        "--price-column", default="price_eur_per_mwh", help="CSV price column"
    )
    price_parser.add_argument(
        "--timestamp-column", default="timestamp", help="CSV timestamp column"
    )
    price_parser.add_argument(
        "--scenario-column", default=None, help="optional CSV scenario column"
    )
    price_parser.add_argument(
        "--probability-column", default=None, help="optional CSV probability column"
    )
    price_parser.add_argument(
        "--timestep-hours", type=float, default=1.0, help="interval length in hours"
    )
    price_parser.add_argument(
        "--risk-aversion",
        type=float,
        default=0.0,
        help="CVaR penalty weight for risk-adjusted value",
    )
    price_parser.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        help="lower-tail probability for cashflow-at-risk and CVaR",
    )
    price_parser.add_argument(
        "--output", default=None, help="optional path for JSON report"
    )
    price_parser.add_argument(
        "--no-timeseries",
        action="store_true",
        help="omit interval-level data from JSON output",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "price":
        portfolio = VirtualPowerPlant.from_json(args.portfolio_json)
        markets = load_market_csv(
            args.market_csv,
            price_column=args.price_column,
            timestamp_column=args.timestamp_column,
            scenario_column=args.scenario_column,
            probability_column=args.probability_column,
            timestep_hours=args.timestep_hours,
        )
        quote = price_portfolio(
            portfolio,
            markets,
            risk_aversion=args.risk_aversion,
            alpha=args.alpha,
        )
        payload = quote.to_dict(include_timeseries=not args.no_timeseries)

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)

        _print_summary(payload)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


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


if __name__ == "__main__":
    raise SystemExit(main())
