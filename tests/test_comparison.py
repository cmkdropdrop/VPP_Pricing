"""Tests for comparison module: mispricing warnings, capture ratio, summary table."""

import unittest

from vpp_pricing.comparison import compare_methods, ComparisonResult
from vpp_pricing.market import MarketData
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.methods.monte_carlo import MonteCarloPricing
from vpp_pricing.methods.rolling_intrinsic import RollingIntrinsicPricing
from vpp_pricing.portfolio import VirtualPowerPlant


def _simple_portfolio() -> VirtualPowerPlant:
    return VirtualPowerPlant.from_dict(
        {
            "name": "test_vpp",
            "assets": [
                {
                    "type": "battery",
                    "name": "bat",
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


def _simple_markets() -> list[MarketData]:
    return [
        MarketData(
            timestamps=("t0", "t1", "t2", "t3"),
            prices_eur_per_mwh=(10.0, 100.0, 20.0, 120.0),
            name="base",
            probability=1.0,
        )
    ]


class ComparisonSummaryTests(unittest.TestCase):
    def test_capture_ratio_is_present_and_correct(self):
        portfolio = _simple_portfolio()
        markets = _simple_markets()
        result = compare_methods(
            portfolio,
            markets,
            [IntrinsicPricing(), RollingIntrinsicPricing(window_hours=2.0)],
        )
        table = result.summary_table()
        intrinsic_row = next(r for r in table if r["method"] == "intrinsic")
        rolling_row = next(r for r in table if r["method"] == "rolling_intrinsic")

        # Intrinsic capture ratio should be 100%
        self.assertAlmostEqual(intrinsic_row["capture_ratio_pct"], 100.0)
        # Rolling with small window should capture less than 100%
        self.assertIsNotNone(rolling_row["capture_ratio_pct"])
        self.assertLessEqual(rolling_row["capture_ratio_pct"], 100.1)

    def test_mispricing_warnings_include_intrinsic_benchmark_warning(self):
        portfolio = _simple_portfolio()
        markets = _simple_markets()
        result = compare_methods(
            portfolio, markets, [IntrinsicPricing()]
        )
        warnings = result.mispricing_warnings()
        self.assertTrue(
            any("upper bound" in w for w in warnings),
            f"Expected intrinsic benchmark warning, got: {warnings}",
        )

    def test_mispricing_warnings_include_rolling_forecast_caveat(self):
        portfolio = _simple_portfolio()
        markets = _simple_markets()
        result = compare_methods(
            portfolio,
            markets,
            [IntrinsicPricing(), RollingIntrinsicPricing(window_hours=2.0)],
        )
        warnings = result.mispricing_warnings()
        self.assertTrue(
            any("forecast error" in w for w in warnings),
            f"Expected rolling forecast caveat, got: {warnings}",
        )

    def test_mispricing_warnings_flag_low_mc_path_count(self):
        portfolio = _simple_portfolio()
        markets = _simple_markets()
        result = compare_methods(
            portfolio,
            markets,
            [MonteCarloPricing(num_paths=5, volatility=0.01, seed=1)],
        )
        warnings = result.mispricing_warnings()
        self.assertTrue(
            any("5 paths" in w for w in warnings),
            f"Expected low-path-count warning, got: {warnings}",
        )

    def test_mispricing_warnings_in_to_dict(self):
        portfolio = _simple_portfolio()
        markets = _simple_markets()
        result = compare_methods(
            portfolio, markets, [IntrinsicPricing()]
        )
        payload = result.to_dict()
        self.assertIn("mispricing_warnings", payload)
        self.assertIsInstance(payload["mispricing_warnings"], list)


if __name__ == "__main__":
    unittest.main()
