import json
import unittest

from vpp_pricing.cli import main
from vpp_pricing.practical import (
    approach_for_method,
    get_practical_approach,
    list_practical_approaches,
)


class PracticalApproachTests(unittest.TestCase):
    def test_implemented_methods_map_to_practical_approaches(self):
        self.assertEqual(approach_for_method("intrinsic").id, "benchmark_intrinsic")
        self.assertEqual(
            approach_for_method("rolling_intrinsic").id,
            "rolling_forecast_dispatch",
        )
        self.assertEqual(
            approach_for_method("monte_carlo").id,
            "stochastic_merchant_bidding",
        )

    def test_catalog_contains_risks_and_validation_focus(self):
        approach = get_practical_approach("balancing_ancillary_services")

        self.assertIn("Enel X", approach.example_users)
        self.assertTrue(approach.mispricing_risks)
        self.assertTrue(approach.validation_focus)

    def test_implemented_only_filters_planned_approaches(self):
        approaches = list_practical_approaches(implemented_only=True)

        self.assertEqual(
            {approach.implemented_method for approach in approaches},
            {"intrinsic", "rolling_intrinsic", "monte_carlo"},
        )

    def test_approaches_cli_json_does_not_require_market_inputs(self):
        from io import StringIO
        from unittest.mock import patch

        buffer = StringIO()
        with patch("sys.stdout", buffer):
            exit_code = main(["approaches", "--implemented-only", "--json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(payload), 3)
        self.assertEqual(payload[0]["id"], "benchmark_intrinsic")


if __name__ == "__main__":
    unittest.main()
