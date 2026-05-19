import unittest

from vpp_pricing.assets import BatteryStorage, FlexibleLoad, RenewableAsset
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
        self.assertAlmostEqual(dispatch.metadata["throughput_mwh"], 2.0)
        self.assertAlmostEqual(dispatch.metadata["equivalent_cycles"], 0.5)

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

    def test_flexible_load_flex_value_excludes_constant_consumption_value(self):
        market = MarketData(
            timestamps=("expensive", "cheap"),
            prices_eur_per_mwh=(100.0, 0.0),
            timestep_hours=1.0,
        )
        load = FlexibleLoad(
            name="flex",
            energy_mwh=1.0,
            min_power_mw=0.0,
            max_power_mw=1.0,
            value_eur_per_mwh=200.0,
        )

        dispatch = load.dispatch(market)

        self.assertEqual(dispatch.power_mw, (-0.0, -1.0))
        self.assertAlmostEqual(dispatch.total_cashflow_eur, 200.0)
        self.assertAlmostEqual(dispatch.metadata["baseline_cost_eur"], 50.0)
        self.assertAlmostEqual(dispatch.metadata["optimized_cost_eur"], 0.0)
        self.assertAlmostEqual(dispatch.metadata["flex_value_eur"], 50.0)
        self.assertAlmostEqual(
            dispatch.metadata["gross_consumption_value_eur"], 200.0
        )

    def test_renewable_metadata_reports_curtailment_and_capture_price(self):
        market = MarketData(
            timestamps=("neg", "pos"),
            prices_eur_per_mwh=(-20.0, 80.0),
            timestep_hours=1.0,
        )
        asset = RenewableAsset(
            name="wind",
            capacity_mw=10.0,
            availability=1.0,
            curtail_below_price_eur_per_mwh=0.0,
        )

        dispatch = asset.dispatch(market)

        self.assertEqual(dispatch.power_mw, (0.0, 10.0))
        self.assertAlmostEqual(dispatch.metadata["available_mwh"], 20.0)
        self.assertAlmostEqual(dispatch.metadata["dispatched_mwh"], 10.0)
        self.assertAlmostEqual(dispatch.metadata["curtailed_mwh"], 10.0)
        self.assertAlmostEqual(
            dispatch.metadata["capture_price_eur_per_mwh"], 80.0
        )


if __name__ == "__main__":
    unittest.main()
