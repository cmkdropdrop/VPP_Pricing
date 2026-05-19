"""Tests for GAN-based scenario pricing."""

import unittest
from math import isfinite

from vpp_pricing.comparison import compare_methods
from vpp_pricing.market import MarketData
from vpp_pricing.methods import get_method
from vpp_pricing.methods.gan import GANPricing
from vpp_pricing.portfolio import VirtualPowerPlant


def _simple_portfolio() -> VirtualPowerPlant:
    return VirtualPowerPlant.from_dict(
        {
            "name": "gan_test",
            "assets": [
                {
                    "type": "renewable",
                    "name": "wind",
                    "capacity_mw": 1.0,
                    "availability": 1.0,
                }
            ],
        }
    )


def _simple_markets() -> list[MarketData]:
    return [
        MarketData(
            timestamps=("t0", "t1", "t2", "t3"),
            prices_eur_per_mwh=(20.0, 50.0, 10.0, 80.0),
            name="base",
            probability=0.7,
        ),
        MarketData(
            timestamps=("t0", "t1", "t2", "t3"),
            prices_eur_per_mwh=(-5.0, 30.0, 95.0, 140.0),
            name="stress",
            probability=0.3,
        ),
    ]


class GANPricingTests(unittest.TestCase):
    def test_gan_pricing_produces_requested_paths_and_diagnostics(self):
        result = GANPricing(
            num_paths=5,
            epochs=5,
            batch_size=3,
            generator_hidden_dim=4,
            discriminator_hidden_dim=4,
            seed=11,
        ).price(_simple_portfolio(), _simple_markets())

        self.assertEqual(result.method_name, "gan")
        self.assertEqual(result.num_scenarios, 5)
        self.assertTrue(isfinite(result.expected_value_eur))
        self.assertEqual(result.parameters["num_paths"], 5)
        self.assertEqual(result.diagnostics["num_training_scenarios"], 2)
        self.assertIn("gan_final_generator_loss", result.diagnostics)
        self.assertIn("generated_market_price_mean_eur_per_mwh", result.diagnostics)

    def test_gan_is_reproducible_with_seed(self):
        kwargs = {
            "num_paths": 4,
            "epochs": 6,
            "batch_size": 2,
            "generator_hidden_dim": 4,
            "discriminator_hidden_dim": 4,
            "seed": 123,
        }
        first = GANPricing(**kwargs).price(_simple_portfolio(), _simple_markets())
        second = GANPricing(**kwargs).price(_simple_portfolio(), _simple_markets())

        self.assertEqual(
            [scenario.prices_eur_per_mwh for scenario in first.scenario_results],
            [scenario.prices_eur_per_mwh for scenario in second.scenario_results],
        )
        self.assertAlmostEqual(first.expected_value_eur, second.expected_value_eur)

    def test_gan_dispatch_window_uses_rolling_policy(self):
        result = GANPricing(
            num_paths=3,
            epochs=4,
            batch_size=2,
            generator_hidden_dim=4,
            discriminator_hidden_dim=4,
            seed=7,
            dispatch_window_hours=2.0,
        ).price(_simple_portfolio(), _simple_markets())

        self.assertEqual(
            result.parameters["dispatch_policy"],
            "rolling_intrinsic_per_generated_path",
        )
        self.assertEqual(result.diagnostics["dispatch_window_intervals"], [2])

    def test_gan_registry_instantiates_method(self):
        method = get_method("gan", num_paths=2, epochs=2, batch_size=1)

        self.assertIsInstance(method, GANPricing)

    def test_invalid_gan_parameters_raise(self):
        with self.assertRaises(ValueError):
            GANPricing(latent_dim=0).price(_simple_portfolio(), _simple_markets())
        with self.assertRaises(ValueError):
            GANPricing(empirical_blend=1.5).price(
                _simple_portfolio(), _simple_markets()
            )

    def test_comparison_warns_about_small_gan_training_set(self):
        result = compare_methods(
            _simple_portfolio(),
            _simple_markets(),
            [
                GANPricing(
                    num_paths=3,
                    epochs=4,
                    batch_size=2,
                    generator_hidden_dim=4,
                    discriminator_hidden_dim=4,
                    seed=1,
                )
            ],
        )

        warnings = result.mispricing_warnings()
        self.assertTrue(
            any("trained on only 2" in warning for warning in warnings),
            f"Expected small training-set warning, got: {warnings}",
        )


if __name__ == "__main__":
    unittest.main()
