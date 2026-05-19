import unittest

from vpp_pricing.market import MarketData
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.methods.monte_carlo import MonteCarloPricing
from vpp_pricing.methods.rolling_intrinsic import RollingIntrinsicPricing
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.pricing import price_portfolio


class PricingTests(unittest.TestCase):
    def test_price_portfolio_uses_scenario_probabilities(self):
        portfolio = VirtualPowerPlant.from_dict(
            {
                "name": "test",
                "assets": [
                    {
                        "type": "renewable",
                        "name": "renewable",
                        "capacity_mw": 1.0,
                        "availability": 1.0,
                    }
                ],
            }
        )
        low = MarketData(
            timestamps=("t0",),
            prices_eur_per_mwh=(10.0,),
            probability=0.25,
            name="low",
        )
        high = MarketData(
            timestamps=("t0",),
            prices_eur_per_mwh=(110.0,),
            probability=0.75,
            name="high",
        )

        quote = price_portfolio(portfolio, [low, high])

        self.assertAlmostEqual(quote.expected_cashflow_eur, 85.0)
        self.assertAlmostEqual(quote.cashflow_at_risk_eur, 10.0)

    def test_monte_carlo_preserves_base_scenario_probabilities(self):
        portfolio = VirtualPowerPlant.from_dict(
            {
                "name": "weighted_mc",
                "assets": [
                    {
                        "type": "renewable",
                        "name": "renewable",
                        "capacity_mw": 1.0,
                        "availability": 1.0,
                    }
                ],
            }
        )
        low = MarketData(
            timestamps=("t0",),
            prices_eur_per_mwh=(0.0,),
            probability=0.9,
            name="low",
        )
        high = MarketData(
            timestamps=("t0",),
            prices_eur_per_mwh=(100.0,),
            probability=0.1,
            name="high",
        )

        result = MonteCarloPricing(num_paths=10, volatility=0.0, seed=1).price(
            portfolio, [low, high]
        )

        self.assertAlmostEqual(result.expected_value_eur, 10.0)
        self.assertEqual(
            result.diagnostics["path_count_by_base_scenario"],
            {"low": 9, "high": 1},
        )

    def test_rolling_intrinsic_matches_intrinsic_with_full_lookahead(self):
        portfolio = VirtualPowerPlant.from_dict(
            {
                "name": "battery_only",
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
        market = MarketData(
            timestamps=("t0", "t1", "t2", "t3"),
            prices_eur_per_mwh=(10.0, 100.0, 20.0, 120.0),
        )

        intrinsic = IntrinsicPricing().price(portfolio, [market])
        rolling = RollingIntrinsicPricing(window_hours=4).price(portfolio, [market])

        self.assertAlmostEqual(rolling.expected_value_eur, intrinsic.expected_value_eur)
        self.assertAlmostEqual(rolling.expected_value_eur, 190.0)
        self.assertEqual(
            rolling.scenario_results[0].asset_dispatches[0].power_mw,
            (-1.0, 1.0, -1.0, 1.0),
        )


if __name__ == "__main__":
    unittest.main()
