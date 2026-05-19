"""Tests for comparison module: mispricing warnings, capture ratio, summary table."""

import unittest

from vpp_pricing.comparison import compare_methods, ComparisonResult
from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
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


def _mixed_vpp_portfolio() -> VirtualPowerPlant:
    return VirtualPowerPlant.from_dict(
        {
            "name": "mixed_vpp",
            "assets": [
                {
                    "type": "renewable",
                    "name": "solar",
                    "capacity_mw": 2.0,
                    "availability": [0.0, 0.6, 1.0, 0.2],
                    "curtail_below_price_eur_per_mwh": 0.0,
                },
                {
                    "type": "fixed_load",
                    "name": "site_load",
                    "profile_mw": [0.8, 0.8, 0.8, 0.8],
                },
                {
                    "type": "flexible_load",
                    "name": "ev_pool",
                    "energy_mwh": 1.0,
                    "min_power_mw": 0.0,
                    "max_power_mw": 1.0,
                },
                {
                    "type": "generator",
                    "name": "peaker",
                    "max_power_mw": 0.5,
                    "marginal_cost_eur_per_mwh": 80.0,
                },
            ],
        }
    )


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
        self.assertGreater(intrinsic_row["export_mwh"], 0.0)
        self.assertGreater(intrinsic_row["capture_price_eur_per_mwh"], 0.0)
        self.assertGreater(intrinsic_row["battery_equivalent_cycles"], 0.0)
        # Rolling with small window should capture less than 100%
        self.assertIsNotNone(rolling_row["capture_ratio_pct"])
        self.assertLessEqual(rolling_row["capture_ratio_pct"], 100.1)

    def test_capture_ratio_is_sign_aware_for_net_cost_benchmarks(self):
        result = ComparisonResult(
            portfolio_name="cost_portfolio",
            num_scenarios=1,
            results={
                "intrinsic": PricingResult(
                    method_name="intrinsic",
                    portfolio_name="cost_portfolio",
                    expected_value_eur=-100.0,
                    cashflow_at_risk_eur=-100.0,
                    conditional_value_at_risk_eur=-100.0,
                    risk_adjusted_value_eur=-100.0,
                    scenario_results=(),
                ),
                "worse_method": PricingResult(
                    method_name="worse_method",
                    portfolio_name="cost_portfolio",
                    expected_value_eur=-120.0,
                    cashflow_at_risk_eur=-120.0,
                    conditional_value_at_risk_eur=-120.0,
                    risk_adjusted_value_eur=-120.0,
                    scenario_results=(),
                ),
            },
        )

        table = result.summary_table()
        worse_row = next(r for r in table if r["method"] == "worse_method")

        self.assertAlmostEqual(worse_row["delta_vs_intrinsic_eur"], -20.0)
        self.assertAlmostEqual(worse_row["capture_ratio_pct"], 80.0)

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

    def test_summary_includes_portfolio_level_vpp_diagnostics(self):
        result = compare_methods(
            _mixed_vpp_portfolio(),
            _simple_markets(),
            [IntrinsicPricing()],
        )
        row = result.summary_table()[0]
        diagnostics = result.results["intrinsic"].diagnostics

        self.assertEqual(
            row["asset_type_counts"],
            {
                "fixed_load": 1,
                "flexible_load": 1,
                "generator": 1,
                "renewable": 1,
            },
        )
        self.assertIn("dispatch_cashflow_by_asset_type_eur", diagnostics)
        self.assertIn("renewable", diagnostics["dispatch_export_mwh_by_asset_type"])
        self.assertGreaterEqual(row["renewable_curtailed_mwh"], 0.0)
        self.assertGreaterEqual(row["flexible_load_value_eur"], 0.0)
        self.assertGreaterEqual(row["dispatchable_generation_mwh"], 0.0)


if __name__ == "__main__":
    unittest.main()
