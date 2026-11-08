"""Check shared-view parity and native storage lifetime boundaries."""
import random
import unittest
from unittest.mock import patch

from native_shared import SharedRoadVehicle
from tools.benchmark_native_spawning import make_city
from traffic_testbed import RoadVehicleSimulation, RoutedRoadVehicle
from tests import test_native_spawning
from tests.reference_traffic import RoadVehicleSimulation as ReferenceSimulation


class NativeSharedTests(unittest.TestCase):
    def test_default_vehicle_fields_follow_native_steps_without_publication(self):
        city, _ = make_city('signalized-crossing', 42)
        sim = RoadVehicleSimulation(spawn_interval=1000)
        self.addCleanup(sim._discard_native)
        car = sim.spawn_car(city, *city.cul_de_sacs[:2])
        before = car.distance
        sim._native_controller.engine.step(.05)
        self.assertGreater(car.distance, before)
        self.assertIsInstance(car, SharedRoadVehicle)

    def test_retired_mode_is_rejected_before_releasing_live_views(self):
        with self.assertRaisesRegex(ValueError, 'shared'):
            RoadVehicleSimulation(native_output_mode='copy')
        city, _ = make_city('signalized-crossing', 42)
        sim = RoadVehicleSimulation(spawn_interval=1000)
        self.addCleanup(sim._discard_native)
        car = sim.spawn_car(city, *city.cul_de_sacs[:2])
        engine = sim._native_controller.engine
        with self.assertRaisesRegex(ValueError, 'shared'):
            sim.native_output_mode = 'copy'
        self.assertIs(sim._native_controller.engine, engine)
        before = car.distance
        engine.step(.05)
        self.assertGreater(car.distance, before)

    def pair(self):
        city, controllers = make_city('signalized-crossing', 42)
        sims = []
        for factory, mode in ((ReferenceSimulation, 'data_first'), (RoadVehicleSimulation, 'cpp')):
            sim = factory(update_mode=mode, rng=random.Random(42), spawn_interval=.8)
            sim.signal_controllers.update(controllers)
            for j in city.cul_de_sacs:
                sim.toggle_junction(j)
            sims.append(sim)
            self.addCleanup(sim._discard_native)
        return city, *sims

    def test_every_tick_matches_python_reference_with_retained_completions(self):
        city, reference, shared = self.pair()
        compare = test_native_spawning.NativeSpawningTests().compare
        retained = []
        for _ in range(900):
            a, b = reference.update(city, .05), shared.update(city, .05)
            compare(reference, shared, a, b)
            retained.extend((car, car.distance, car.position, car.brain.wait_reason) for car in b)
            self.assertEqual(reference.stop_coordinator.claims.keys(), shared.stop_coordinator.claims.keys())
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
        with patch.object(e, 'vehicle_views', side_effect=AssertionError('state export')):
            e.step(.05)
            self.assertGreater(car.distance, before)

    def test_mutation_removal_close_and_recreation_preserve_state(self):
        city, reference, shared = self.pair()
        for _ in range(80):
            reference.update(city, .05)
            shared.update(city, .05)
        compare = test_native_spawning.NativeSpawningTests().compare
        for sim in (reference, shared):
            sim.place_vehicle(sim.cars[0].id, 20)
        compare(reference, shared)
        shared.update(city, .05)
        reference.update(city, .05)
        removed = shared.remove_vehicle(shared.cars[0].id)
        reference.remove_vehicle(removed.id)
        self.assertIs(type(removed), RoutedRoadVehicle)
        compare(reference, shared)
        car = shared.cars[0]
        before = (car.distance, car.position, car.brain.wait_reason)
        shared._discard_native()
        self.assertIs(type(car), RoutedRoadVehicle)
        self.assertEqual(before, (car.distance, car.position, car.brain.wait_reason))
        compare(reference, shared, reference.update(city, .05), shared.update(city, .05))


if __name__ == '__main__':
    unittest.main()
