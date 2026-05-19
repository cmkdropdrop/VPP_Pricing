import unittest

from vpp_pricing.assets import BatteryStorage, FlexibleLoad
from vpp_pricing.market import MarketData


class AssetDispatchTests(unittest.TestCase):
    def test_battery_arbitrages_low_to_high_prices_with_terminal_soc(self):
        market = MarketData(
            timestamps=("t0", "t1"),
            prices_eur_per_mwh=(10.0, 100.0),
            timestep_hours=1.0,
        )
        battery = BatteryStorage(
            name="battery",
            capacity_mwh=2.0,
            power_mw=1.0,
            round_trip_efficiency=1.0,
            initial_soc_mwh=1.0,
            terminal_soc_mwh=1.0,
            grid_points=3,
        )

        dispatch = battery.dispatch(market)

        self.assertEqual(dispatch.power_mw, (-1.0, 1.0))
        self.assertAlmostEqual(dispatch.total_cashflow_eur, 90.0)

    def test_flexible_load_consumes_cheapest_hours_first(self):
        market = MarketData(
            timestamps=("expensive", "cheap", "mid"),
            prices_eur_per_mwh=(100.0, 10.0, 50.0),
            timestep_hours=1.0,
        )
        load = FlexibleLoad(
            name="flex",
            energy_mwh=2.0,
            min_power_mw=0.0,
            max_power_mw=1.0,
        )

        dispatch = load.dispatch(market)

        self.assertEqual(dispatch.power_mw, (-0.0, -1.0, -1.0))
        self.assertAlmostEqual(dispatch.total_cashflow_eur, -60.0)
        self.assertGreater(dispatch.metadata["flex_value_eur"], 0.0)


if __name__ == "__main__":
    unittest.main()
