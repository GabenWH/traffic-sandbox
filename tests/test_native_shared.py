"""Check shared-view parity and native storage lifetime boundaries."""
import random
import unittest
from unittest.mock import patch

from native_shared import SharedRoadVehicle
from tools.benchmark_native_spawning import make_city
from traffic_testbed import RoadVehicleSimulation, RoutedRoadVehicle
from tests import test_native_spawning


class NativeSharedTests(unittest.TestCase):
    def pair(self):
        city, controllers = make_city('signalized-crossing', 42)
        sims = []
        for mode in ('copy', 'shared'):
            sim = RoadVehicleSimulation(update_mode='cpp', native_output_mode=mode,
                                        rng=random.Random(42), spawn_interval=.8)
            sim.signal_controllers.update(controllers)
            for j in city.cul_de_sacs:
                sim.toggle_junction(j)
            sims.append(sim)
            self.addCleanup(sim._discard_native)
        return city, *sims

    def test_every_tick_matches_copy_with_completion_and_retained_objects(self):
        city, copied, shared = self.pair()
        compare = test_native_spawning.NativeSpawningTests().compare
        retained = []
        for _ in range(900):
            a, b = copied.update(city, .05), shared.update(city, .05)
            compare(copied, shared, a, b)
            retained.extend((car, car.distance, car.position, car.brain.wait_reason) for car in b)
            self.assertEqual(copied.stop_coordinator.claims.keys(), shared.stop_coordinator.claims.keys())
        self.assertTrue(retained)
        for car, distance, position, reason in retained:
            self.assertIs(type(car), RoutedRoadVehicle)
            self.assertEqual((car.distance, car.position, car.brain.wait_reason), (distance, position, reason))

    def test_fields_are_live_without_sync_or_state_export(self):
        city, _, shared = self.pair()
        shared.update(city, 1)
        e = shared._native_controller.engine
        car = shared.cars[0]
        before = car.distance
        self.assertIsInstance(car, SharedRoadVehicle)
        with patch.object(e, 'sync', side_effect=AssertionError('field copy')), \
             patch.object(e, 'vehicle_views', side_effect=AssertionError('state export')):
            e.step(.05)
            self.assertGreater(car.distance, before)

    def test_mutation_removal_close_and_mode_switch_preserve_state(self):
        city, copied, shared = self.pair()
        for _ in range(80):
            copied.update(city, .05)
            shared.update(city, .05)
        compare = test_native_spawning.NativeSpawningTests().compare
        for sim in (copied, shared):
            sim.place_vehicle(sim.cars[0].id, 20)
        compare(copied, shared)
        shared.update(city, .05)
        copied.update(city, .05)
        removed = shared.remove_vehicle(shared.cars[0].id)
        copied.remove_vehicle(removed.id)
        self.assertIs(type(removed), RoutedRoadVehicle)
        compare(copied, shared)
        car = shared.cars[0]
        before = (car.distance, car.position, car.brain.wait_reason)
        shared.native_output_mode = 'copy'
        self.assertIs(type(car), RoutedRoadVehicle)
        self.assertEqual(before, (car.distance, car.position, car.brain.wait_reason))
        compare(copied, shared, copied.update(city, .05), shared.update(city, .05))


if __name__ == '__main__':
    unittest.main()
