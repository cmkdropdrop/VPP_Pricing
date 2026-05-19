import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from vpp_pricing.assets import create_asset
from vpp_pricing.cli import main
from vpp_pricing.market import MarketData, validate_market_scenarios
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.validation import validate_portfolio_and_markets


class InputValidationTests(unittest.TestCase):
    def test_unknown_asset_fields_raise_clear_value_error(self):
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            create_asset(
                {
                    "type": "battery",
                    "name": "battery",
                    "capacity_mwh": 1.0,
                    "power_mw": 1.0,
                    "unknown_field": 123,
                }
            )

    def test_market_scenarios_must_have_identical_timestamps(self):
        markets = [
            MarketData(("t0", "t1"), (10.0, 20.0), name="base"),
            MarketData(("t0", "t2"), (10.0, 20.0), name="stress"),
        ]

        with self.assertRaisesRegex(ValueError, "identical timestamps"):
            validate_market_scenarios(markets)

    def test_validation_report_flags_domain_quality_issues(self):
        portfolio = VirtualPowerPlant.from_dict(
            {
                "name": "test",
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
        markets = [
            MarketData(
                timestamps=("t0", "t1"),
                prices_eur_per_mwh=(-10.0, 120.0),
                name="base",
            )
        ]

        report = validate_portfolio_and_markets(portfolio, markets)
        codes = {issue.code for issue in report.issues}

        self.assertFalse(report.has_errors)
        self.assertIn("single_market_scenario", codes)
        self.assertIn("battery_degradation_omitted", codes)
        self.assertIn("battery_low_state_grid_resolution", codes)

    def test_validate_cli_can_emit_json_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio_path = root / "portfolio.json"
            market_path = root / "market.csv"
            report_path = root / "validation.json"
            portfolio_path.write_text(
                json.dumps(
                    {
                        "name": "cli_test",
                        "assets": [
                            {
                                "type": "renewable",
                                "name": "solar",
                                "capacity_mw": 1.0,
                                "availability": 1.0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            market_path.write_text(
                "timestamp,price_eur_per_mwh\n"
                "t0,10\n",
                encoding="utf-8",
            )

            buffer = StringIO()
            with patch("sys.stdout", buffer):
                exit_code = main(
                    [
                        "validate",
                        str(portfolio_path),
                        str(market_path),
                        "--json",
                        "--output",
                        str(report_path),
                    ]
                )

            saved_payload = json.loads(report_path.read_text(encoding="utf-8"))

        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["portfolio_name"], "cli_test")
        self.assertEqual(payload["status"], "passed")
        self.assertIn("issues", payload)
        self.assertEqual(saved_payload["portfolio_name"], "cli_test")


if __name__ == "__main__":
    unittest.main()
