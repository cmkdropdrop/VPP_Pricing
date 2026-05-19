import unittest

from vpp_pricing.market import MarketData
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


if __name__ == "__main__":
    unittest.main()
