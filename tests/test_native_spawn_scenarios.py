"""Sustained native-generated traffic, independently simulated in both engines."""
import copy
import json
import os
from pathlib import Path
import random
import unittest

import test_native_spawning as comparison
from merge_lab import scenario_catalog
from persistence import world_from_dict
from traffic_testbed import RoadVehicleSimulation
from traffic_route_state import RouteState, RouteGeometry


def twin(reference):
    cars = []
    for car in reference.cars:
        other = copy.copy(car)
        other.brain = copy.copy(car.brain)
        other._route_cache, other._geometry = RouteState(), RouteGeometry()
        cars.append(other)
    result = RoadVehicleSimulation(update_mode='native', spawn_interval=reference.spawn_interval,
                                   max_cars=reference.max_cars, speed_mph=reference.speed_mph,
                                   active_junction_ids=list(reference.active_junction_ids), cars=cars,
                                   _spawn_elapsed=dict(reference._spawn_elapsed))
    result.rng.setstate(reference.rng.getstate())
    result.elapsed_time, result._spawned_count = reference.elapsed_time, reference._spawned_count
    result.stop_coordinator.arrivals = dict(reference.stop_coordinator.arrivals)
    result.stop_coordinator.claims = dict(reference.stop_coordinator.claims)
    result.stop_coordinator._claims_by_car = {key: dict(value) for key, value in reference.stop_coordinator._claims_by_car.items()}
    result.deadlock_resolver = copy.copy(reference.deadlock_resolver)
    result.deadlock_resolver._waiting_seconds = dict(reference.deadlock_resolver._waiting_seconds)
    return result


class NativeSpawnScenarioTests(unittest.TestCase):
    compare = comparison.NativeSpawningTests.compare
    def run_scenario(self, city, reference):
        reference.update_mode = 'data_first'
        reference.spawn_interval = 1
        junctions = reference.active_junctions(city)
        for i, junction in enumerate(junctions):
            reference._spawn_elapsed[junction.id] = i / max(1, len(junctions))
        native = twin(reference)
        ticks = round(float(os.environ.get('NATIVE_SPAWN_SECONDS', '80')) / .05)
        peak = len(native.cars)
        try:
            for tick in range(ticks):
                self.compare(reference, native, reference.update(city, .05), native.update(city, .05))
                peak = max(peak, len(native.cars))
            self.assertEqual(reference._spawned_count, native._spawned_count)
        finally:
            native._discard_native()
        return peak

    def test_full_native_spawn_merge_lab(self):
        for scenario in scenario_catalog():
            with self.subTest(scenario=scenario.name):
                self.run_scenario(*scenario.build(42))

    def test_full_native_spawn_uploaded_maps(self):
        for filename in ('slip_lanes.json', 'roundabout_test.json'):
            with self.subTest(map=filename):
                city = world_from_dict(json.loads((Path(__file__).parent / 'fixtures' / filename).read_text())).city_map
                reference = RoadVehicleSimulation(rng=random.Random(42))
                for junction in city.cul_de_sacs:
                    reference.toggle_junction(junction)
                self.assertGreater(self.run_scenario(city, reference), 0)
