import unittest
from town_simulation import build_town


class TownTests(unittest.TestCase):
    def test_vehicle_identity_returns_and_resource_conservation(self):
        town = build_town(population=12, work_start=60, work_end=3600)
        ids = set(town.fleet.vehicles)
        objects = dict(town.fleet.vehicles)
        town.update(9000)
        report = town.report()
        self.assertEqual(set(town.fleet.vehicles), ids)
        self.assertTrue(all(town.fleet.vehicles[k] is v for k,v in objects.items()))
        self.assertEqual(report['population'], 12)
        self.assertGreater(report['workers_arrived'], 0)
        self.assertGreater(report['produced_food'], 0)
        self.assertGreater(report['deliveries'], 0)
        self.assertAlmostEqual(report['resource_balance_error'], 0, places=5)
        town.update(77400)
        self.assertEqual(town.report()['at_home'], 12)
        self.assertTrue(all(v.phase == 'parked' for v in town.fleet.vehicles.values()))
        self.assertTrue(all(v.trips >= 2 for v in town.fleet.vehicles.values() if v.kind == 'car'))

    def test_checkpoint_rejects_active_traffic(self):
        town = build_town(population=12, work_start=60, work_end=3600)
        town.update(120)
        with self.assertRaisesRegex(ValueError, 'quiescent'):
            town.checkpoint()

    def test_quiescent_checkpoint_round_trip(self):
        from town_simulation import TownSimulation
        town = build_town(population=12, work_start=60, work_end=3600)
        saved = town.checkpoint()
        restored = TownSimulation.from_checkpoint(saved)
        self.assertEqual(restored.report(), town.report())
        restored.update(60)
        self.assertAlmostEqual(restored.report()['resource_balance_error'], 0, places=5)

    def test_no_fuel_does_not_teleport_a_registered_car(self):
        town = build_town(population=12, work_start=60, work_end=3600)
        car = next(v for v in town.fleet.vehicles.values() if v.kind == 'car')
        site = car.site
        car.fuel_liters = 0
        self.assertFalse(town.fleet.dispatch(car.id, 'work'))
        self.assertEqual(car.site, site)
        self.assertEqual(car.phase, 'parked')
        self.assertEqual(car.trips, 0)

    def test_workers_do_not_produce_before_arrival(self):
        town = build_town(population=12, work_start=600, work_end=3600)
        town.update(60)
        self.assertEqual(town.report()['produced_food'], 0)
        self.assertEqual(town.report()['at_work'], 0)

    def test_returning_car_uses_closest_road_direction(self):
        town = build_town(population=12, work_start=600, work_end=3600)
        car = next(v for v in town.fleet.vehicles.values() if v.kind == 'car')
        car.site = 'work'
        self.assertTrue(town.fleet.dispatch(car.id, 'home-0'))
        # The westbound lane is a direct return; forcing the eastbound bus
        # stop lane would send the car to the cul-de-sac and back around.
        self.assertLess(car._actor.total_length, 5700)
        self.assertLess(car._actor.points[-1][0], car._actor.points[0][0])
        self.assertLess(car._actor.points[0][1], 0)


if __name__ == '__main__':
    unittest.main()
