import unittest
from math import isfinite, sqrt

from vpp_pricing.comparison import compare_methods
from vpp_pricing.market import MarketData, load_market_csv
from vpp_pricing.methods import get_method
from vpp_pricing.methods.intrinsic import IntrinsicPricing
from vpp_pricing.methods.reinforcement_learning import ReinforcementLearningPricing
from vpp_pricing.portfolio import VirtualPowerPlant


def _battery_portfolio() -> VirtualPowerPlant:
    return VirtualPowerPlant.from_dict(
        {
            "name": "rl_battery",
            "assets": [
                {
                    "type": "battery",
                    "name": "battery",
                    "capacity_mwh": 2.0,
                    "power_mw": 1.0,
                    "round_trip_efficiency": 0.81,
                    "initial_soc_mwh": 1.0,
                    "terminal_soc_mwh": 1.0,
                    "cycle_cost_eur_per_mwh": 1.0,
                    "grid_points": 3,
                }
            ],
        }
    )


def _markets() -> list[MarketData]:
    return [
        MarketData(
            timestamps=("t0", "t1", "t2", "t3"),
            prices_eur_per_mwh=(10.0, 100.0, 20.0, 120.0),
            name="base",
            probability=0.7,
        ),
        MarketData(
            timestamps=("t0", "t1", "t2", "t3"),
            prices_eur_per_mwh=(80.0, 15.0, 95.0, 30.0),
            name="alt",
            probability=0.3,
        ),
    ]


class ReinforcementLearningPricingTests(unittest.TestCase):
    def test_rl_runs_on_merchant_bess_example(self):
        portfolio = VirtualPowerPlant.from_json("examples/merchant_bess.json")
        markets = load_market_csv(
            "examples/data/extended_scenarios.csv",
            scenario_column="scenario",
            probability_column="probability",
        )

        result = ReinforcementLearningPricing(
            episodes=40,
            soc_bins=9,
            price_bins=5,
            seed=7,
        ).price(portfolio, markets)

        self.assertEqual(result.method_name, "rl")
        self.assertEqual(result.num_scenarios, len(markets))
        self.assertTrue(isfinite(result.expected_value_eur))
        self.assertEqual(result.diagnostics["rl_training_episodes"], 40)
        self.assertGreater(result.diagnostics["rl_state_count"], 0)
        self.assertEqual(result.diagnostics["rl_action_count"], 3)
        self.assertEqual(
            result.diagnostics["rl_policy_scope"],
            "battery_only_tabular_q_learning",
        )

    def test_rl_policy_respects_soc_and_power_limits(self):
        portfolio = _battery_portfolio()
        market = _markets()[0]
        result = ReinforcementLearningPricing(episodes=30, seed=3).price(
            portfolio,
            [market],
        )
        dispatch = result.scenario_results[0].asset_dispatches[0]
        battery = portfolio.assets[0]
        charge_efficiency = sqrt(battery.round_trip_efficiency)
        discharge_efficiency = sqrt(battery.round_trip_efficiency)
        soc = battery.initial_soc_mwh

        for power_mw in dispatch.power_mw:
            self.assertLessEqual(abs(power_mw), battery.power_mw + 1e-9)
            if power_mw < 0:
                soc += (-power_mw * market.timestep_hours) * charge_efficiency
            else:
                soc -= (power_mw * market.timestep_hours) / discharge_efficiency
            self.assertGreaterEqual(soc, -1e-9)
            self.assertLessEqual(soc, battery.capacity_mwh + 1e-9)

        self.assertAlmostEqual(soc, battery.terminal_soc_mwh, places=6)

    def test_rl_seed_makes_results_reproducible(self):
        kwargs = {
            "episodes": 60,
            "learning_rate": 0.25,
            "soc_bins": 7,
            "price_bins": 4,
            "seed": 123,
        }
        first = ReinforcementLearningPricing(**kwargs).price(
            _battery_portfolio(),
            _markets(),
        )
        second = ReinforcementLearningPricing(**kwargs).price(
            _battery_portfolio(),
            _markets(),
        )

        self.assertAlmostEqual(first.expected_value_eur, second.expected_value_eur)
        self.assertEqual(
            [
                asset.power_mw
                for scenario in first.scenario_results
                for asset in scenario.asset_dispatches
            ],
            [
                asset.power_mw
                for scenario in second.scenario_results
                for asset in scenario.asset_dispatches
            ],
        )

    def test_rl_registry_instantiates_method(self):
        method = get_method("rl", episodes=5)

        self.assertIsInstance(method, ReinforcementLearningPricing)

    def test_comparison_warns_about_small_rl_training_set(self):
        result = compare_methods(
            _battery_portfolio(),
            _markets(),
            [
                IntrinsicPricing(),
                ReinforcementLearningPricing(episodes=10, seed=1),
            ],
        )

        warnings = result.mispricing_warnings()
        self.assertTrue(
            any("rl: trained on only 2" in warning for warning in warnings),
            f"Expected small RL training-set warning, got: {warnings}",
        )


if __name__ == "__main__":
    unittest.main()
