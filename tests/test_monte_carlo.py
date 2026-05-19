"""Tests for Monte-Carlo pricing: drift correction, mean-reversion, edge cases."""

import unittest

from vpp_pricing.market import MarketData
from vpp_pricing.methods.monte_carlo import MonteCarloPricing, _simulate_paths
from vpp_pricing.methods.rolling_intrinsic import RollingIntrinsicPricing
from vpp_pricing.portfolio import VirtualPowerPlant

import random


class MCDriftCorrectionTests(unittest.TestCase):
    """Verify that simulated paths are unbiased around the base price."""

    def test_mean_of_many_paths_is_close_to_base_price(self):
        """With enough paths, the average simulated price at each step
        should converge to the base price (unbiased drift correction)."""
        base = MarketData(
            timestamps=tuple(f"t{i}" for i in range(24)),
            prices_eur_per_mwh=tuple(50.0 + i * 2 for i in range(24)),
            timestep_hours=1.0,
            name="flat",
        )
        rng = random.Random(12345)
        paths = _simulate_paths(base, num_paths=5000, volatility=0.30, rng=rng)

        for step in range(24):
            base_price = base.prices_eur_per_mwh[step]
            mean_sim = sum(p.prices_eur_per_mwh[step] for p in paths) / len(paths)
            # With 5000 paths the sample mean should be within ~3% of base
            self.assertAlmostEqual(
                mean_sim / base_price,
                1.0,
                delta=0.05,
                msg=f"step {step}: E[sim]={mean_sim:.2f} vs base={base_price:.2f}",
            )

    def test_zero_volatility_paths_equal_base(self):
        """With zero volatility, simulated paths must exactly equal base."""
        base = MarketData(
            timestamps=("t0", "t1", "t2"),
            prices_eur_per_mwh=(100.0, 50.0, 75.0),
        )
        rng = random.Random(42)
        paths = _simulate_paths(base, num_paths=3, volatility=0.0, rng=rng)

        for path in paths:
            self.assertEqual(path.prices_eur_per_mwh, base.prices_eur_per_mwh)

    def test_mean_reversion_zero_gives_independent_shocks(self):
        """With mean_reversion=0, shocks are independent (no autocorrelation)."""
        base = MarketData(
            timestamps=tuple(f"t{i}" for i in range(100)),
            prices_eur_per_mwh=tuple(80.0 for _ in range(100)),
        )
        rng = random.Random(999)
        paths = _simulate_paths(
            base, num_paths=3000, volatility=0.20, rng=rng, mean_reversion=0.0
        )

        # With independent shocks, the mean should still be unbiased
        for step in [0, 50, 99]:
            mean_sim = sum(p.prices_eur_per_mwh[step] for p in paths) / len(paths)
            self.assertAlmostEqual(
                mean_sim / 80.0,
                1.0,
                delta=0.05,
                msg=f"step {step}: E[sim]={mean_sim:.2f} vs base=80.0",
            )

    def test_negative_base_price_handling(self):
        """Negative base prices use the same unbiased displaced process."""
        base = MarketData(
            timestamps=("t0", "t1", "t2"),
            prices_eur_per_mwh=(-40.0, 0.0, 60.0),
        )
        rng = random.Random(42)
        paths = _simulate_paths(base, num_paths=5000, volatility=0.20, rng=rng)

        for step, base_price in enumerate(base.prices_eur_per_mwh):
            mean_sim = sum(path.prices_eur_per_mwh[step] for path in paths) / len(paths)
            self.assertAlmostEqual(mean_sim, base_price, delta=2.0)

    def test_negative_twenty_base_price_keeps_dispersion(self):
        base = MarketData(
            timestamps=("t0",),
            prices_eur_per_mwh=(-20.0,),
        )
        rng = random.Random(42)
        paths = _simulate_paths(base, num_paths=50, volatility=0.30, rng=rng)

        simulated_prices = {path.prices_eur_per_mwh[0] for path in paths}

        self.assertGreater(len(simulated_prices), 1)


class MCPricingIntegrationTests(unittest.TestCase):
    def test_mean_reversion_parameter_appears_in_result(self):
        portfolio = VirtualPowerPlant.from_dict(
            {
                "name": "test",
                "assets": [
                    {
                        "type": "renewable",
                        "name": "solar",
                        "capacity_mw": 1.0,
                        "availability": 1.0,
                    }
                ],
            }
        )
        market = MarketData(
            timestamps=("t0",), prices_eur_per_mwh=(50.0,), name="base"
        )
        result = MonteCarloPricing(
            num_paths=5, volatility=0.1, seed=1, mean_reversion=0.5
        ).price(portfolio, [market])

        self.assertEqual(result.parameters["mean_reversion"], 0.5)
        self.assertEqual(result.parameters["price_floor_eur_per_mwh"], 20.0)
        self.assertEqual(
            result.diagnostics["mc_price_process"],
            "displaced_lognormal_ar1",
        )
        self.assertIn(
            "mc_empirical_mean_abs_price_bias_eur_per_mwh",
            result.diagnostics,
        )

    def test_invalid_mean_reversion_raises(self):
        portfolio = VirtualPowerPlant.from_dict(
            {
                "name": "test",
                "assets": [
                    {
                        "type": "renewable",
                        "name": "r",
                        "capacity_mw": 1.0,
                    }
                ],
            }
        )
        market = MarketData(
            timestamps=("t0",), prices_eur_per_mwh=(50.0,), name="base"
        )
        with self.assertRaises(ValueError, msg="mean_reversion must be in [0, 1)"):
            MonteCarloPricing(mean_reversion=1.0).price(portfolio, [market])

        with self.assertRaises(ValueError):
            MonteCarloPricing(mean_reversion=-0.1).price(portfolio, [market])

        with self.assertRaises(ValueError):
            MonteCarloPricing(price_floor_eur_per_mwh=0.0).price(portfolio, [market])

    def test_dispatch_window_uses_rolling_policy_on_simulated_paths(self):
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

        rolling = RollingIntrinsicPricing(window_hours=2.0).price(
            portfolio, [market]
        )
        mc = MonteCarloPricing(
            num_paths=1,
            volatility=0.0,
            seed=7,
            dispatch_window_hours=2.0,
        ).price(portfolio, [market])

        self.assertEqual(mc.parameters["dispatch_policy"], "rolling_intrinsic_per_path")
        self.assertEqual(mc.diagnostics["dispatch_window_intervals"], [2])
        self.assertAlmostEqual(mc.expected_value_eur, rolling.expected_value_eur)


if __name__ == "__main__":
    unittest.main()
