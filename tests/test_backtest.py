import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from vpp_pricing.backtest import (
    HistoricalMarketProduct,
    load_historical_market_csv,
    run_backtest,
)
from vpp_pricing.cli import main
from vpp_pricing.market import MarketData
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.pricing import price_portfolio


def _battery_portfolio() -> VirtualPowerPlant:
    return VirtualPowerPlant.from_dict(
        {
            "name": "battery_backtest",
            "assets": [
                {
                    "type": "battery",
                    "name": "battery",
                    "capacity_mwh": 2.0,
                    "power_mw": 1.0,
                    "round_trip_efficiency": 1.0,
                    "initial_soc_mwh": 1.0,
                    "terminal_soc_mwh": 1.0,
                    "grid_points": 3,
                }
            ],
        }
    )


class BacktestTests(unittest.TestCase):
    def test_historical_market_product_validates_alignment(self):
        with self.assertRaisesRegex(ValueError, "identical timestamps"):
            HistoricalMarketProduct(
                product_id="p1",
                as_of="2026-01-01T10:00:00Z",
                valuation_markets=(
                    MarketData(("t0",), (10.0,), name="base"),
                ),
                settlement_market=MarketData(("t1",), (12.0,), name="settlement"),
            )

    def test_load_historical_market_csv_reads_example_fixture(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "examples" / "data" / "historical_products.csv"

        products = load_historical_market_csv(path)

        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].product_id, "day_ahead_2026_01_01")
        self.assertEqual(products[0].decision_market.name, "base")
        self.assertEqual(products[0].intervals, 4)
        self.assertAlmostEqual(products[0].valuation_markets[0].probability, 1.0)

    def test_backtest_settles_decision_schedule_without_reoptimization(self):
        product = HistoricalMarketProduct(
            product_id="day_ahead_test",
            as_of="2026-01-01T10:00:00Z",
            valuation_markets=(
                MarketData(
                    timestamps=("t0", "t1"),
                    prices_eur_per_mwh=(10.0, 100.0),
                    name="base",
                ),
            ),
            settlement_market=MarketData(
                timestamps=("t0", "t1"),
                prices_eur_per_mwh=(20.0, 80.0),
                name="settlement",
            ),
        )

        result = run_backtest(_battery_portfolio(), [product], IntrinsicPricing())
        entry = result.entries[0]

        self.assertEqual(
            entry.settlement_dispatch.asset_dispatches[0].power_mw,
            (-1.0, 1.0),
        )
        self.assertAlmostEqual(entry.valuation_expected_value_eur, 90.0)
        self.assertAlmostEqual(entry.settled_cashflow_eur, 60.0)
        self.assertAlmostEqual(entry.pricing_error_eur, -30.0)
        self.assertAlmostEqual(result.metrics()["mean_absolute_error_eur"], 30.0)
        self.assertIn("not re-optimized", entry.diagnostics["settlement_caveat"])

    def test_backtest_cli_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio_path = root / "portfolio.json"
            market_path = root / "historical.csv"
            report_path = root / "backtest.json"

            portfolio_path.write_text(
                json.dumps(
                    {
                        "name": "cli_backtest",
                        "assets": [
                            {
                                "type": "battery",
                                "name": "battery",
                                "capacity_mwh": 2.0,
                                "power_mw": 1.0,
                                "round_trip_efficiency": 1.0,
                                "initial_soc_mwh": 1.0,
                                "terminal_soc_mwh": 1.0,
                                "grid_points": 3,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            market_path.write_text(
                "product_id,as_of,timestamp,valuation_price_eur_per_mwh,"
                "settlement_price_eur_per_mwh\n"
                "p1,2026-01-01T10:00:00Z,t0,10,20\n"
                "p1,2026-01-01T10:00:00Z,t1,100,80\n",
                encoding="utf-8",
            )

            buffer = StringIO()
            with patch("sys.stdout", buffer):
                exit_code = main(
                    [
                        "backtest",
                        str(portfolio_path),
                        str(market_path),
                        "--output",
                        str(report_path),
                        "--no-timeseries",
                    ]
                )
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["portfolio_name"], "cli_backtest")
        self.assertEqual(payload["method"], "intrinsic")
        self.assertAlmostEqual(
            payload["metrics"]["mean_absolute_error_eur"],
            30.0,
        )
        self.assertIn("no ex-post re-optimization", buffer.getvalue())

    def test_legacy_price_portfolio_regression_stays_unchanged(self):
        quote = price_portfolio(
            _battery_portfolio(),
            [
                MarketData(
                    timestamps=("t0", "t1"),
                    prices_eur_per_mwh=(10.0, 100.0),
                    name="base",
                )
            ],
        )

        self.assertAlmostEqual(quote.expected_cashflow_eur, 90.0)
        self.assertAlmostEqual(quote.scenario_results[0].total_cashflow_eur, 90.0)


if __name__ == "__main__":
    unittest.main()
