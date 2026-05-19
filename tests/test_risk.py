import unittest

from vpp_pricing.risk import (
    cashflow_distribution_diagnostics,
    effective_sample_size,
    lower_tail_support,
)


class RiskDiagnosticsTests(unittest.TestCase):
    def test_effective_sample_size_reflects_weight_concentration(self):
        self.assertAlmostEqual(effective_sample_size([0.25, 0.25, 0.25, 0.25]), 4.0)
        self.assertAlmostEqual(effective_sample_size([0.9, 0.1]), 1.219512, places=6)

    def test_lower_tail_support_uses_fractional_boundary_mass(self):
        tail = lower_tail_support(
            values=[100.0, -50.0, 10.0],
            probabilities=[0.8, 0.1, 0.1],
            alpha=0.15,
        )

        self.assertEqual(tail["count"], 2.0)
        self.assertAlmostEqual(tail["probability_mass"], 0.15)
        self.assertGreater(tail["effective_sample_size"], 1.0)

    def test_distribution_diagnostics_include_tail_quality(self):
        diagnostics = cashflow_distribution_diagnostics(
            [100.0, -50.0, 10.0],
            [0.8, 0.1, 0.1],
            alpha=0.15,
        )

        self.assertIn("cashflow_effective_sample_size", diagnostics)
        self.assertIn("cashflow_lower_tail_effective_sample_size", diagnostics)
        self.assertEqual(diagnostics["cashflow_lower_tail_sample_count"], 2.0)


if __name__ == "__main__":
    unittest.main()
