"""Live differential coverage of the native driver; no recorded decisions.

Python supplies identical admission requests, as it will in the application.
Every subsequent native observation, decision and movement is computed in C++.
"""
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from city import CityMap, Terrain
from native_traffic import NativeTrafficEngine
from persistence import world_from_dict
from tests.reference_traffic import TestTrafficSimulation, as_reference


class NativeExtendedParityTests(unittest.TestCase):
    def assert_states(self, native, expected, context):
        actual = native.snapshot(include_completed=True)
        self.assertEqual(set(actual), {c.id for c in expected}, context)
        for car in expected:
            state = actual[car.id]
            where = str((context, car.id))
            for field, value in (
                ('distance', car.distance), ('speed', car.speed),
                ('desired_speed', car.brain.desired_speed),
                ('stopped_elapsed', car.brain.stopped_elapsed),
            ):
                self.assertAlmostEqual(getattr(state, field), value, delta=1e-7, msg=where + field)
            for field in ('position', 'heading'):
                for a, b in zip(getattr(state, field), getattr(car, field)):
                    self.assertAlmostEqual(a, b, delta=1e-7, msg=where + field)
            for field, value in (
                ('state', car.brain.state.value), ('signal', car.brain.signal_intent.value),
                ('reason', car.brain.wait_reason), ('phantom', car.brain.phantom_target),
                ('claim', None if car.claimed_movement is None else car.claimed_movement.id),
            ):
                self.assertEqual(getattr(state, field), value, where + field)

    def drive(self, city, traffic, ticks, *, edit=None, dt=0.05):
        as_reference(traffic)
        traffic.debugger = None
        completed_count = 0
        with NativeTrafficEngine.from_simulation(traffic) as native:
            original_spawn = traffic.spawn_car

            def spawn(*args, **kwargs):
                car = original_spawn(*args, **kwargs)
                if car is not None:
                    native.spawn(car)
                return car

            with patch.object(traffic, 'spawn_car', side_effect=spawn):
                for tick in range(ticks):
                    if edit:
                        edit(tick, native)
                    completed = traffic.update(city, dt)
                    native.step(dt)
                    self.assert_states(native, list(traffic.cars) + completed, tick)
                    self.assertEqual({key for key, s in native.snapshot(include_completed=True).items()
                                      if not s.alive}, {c.id for c in completed})
                    completed_count += len(completed)
        return completed_count

    def cross(self, stop):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        city.standard_intersections[0].set_all_way_stop(stop)
        traffic = TestTrafficSimulation(spawn_interval=1000, rng=random.Random(42))
        ends = city.cul_de_sacs
        for i, source in enumerate(ends):
            self.assertIsNotNone(traffic.spawn_car(city, source, ends[(i + 2) % len(ends)]))
        return city, traffic

    def test_uncontrolled_crossing_through_completion(self):
        self.assertEqual(self.drive(*self.cross(False), 900), 4)

    def test_import_after_python_has_stopped_and_claimed(self):
        for checkpoint in (90, 140, 200):
            with self.subTest(checkpoint=checkpoint):
                city, traffic = self.cross(True)
                as_reference(traffic)
                for _ in range(checkpoint):
                    traffic.update(city, 0.05)
                self.drive(city, traffic, 300)

    def test_zero_time_and_reordered_roster(self):
        city, traffic = self.cross(True)
        traffic.reorder_vehicles(reversed([car.id for car in traffic.cars]))
        self.drive(city, traffic, 3, dt=0)
        self.drive(city, traffic, 400)

    def test_all_way_stop_through_completion(self):
        self.assertEqual(self.drive(*self.cross(True), 900), 4)

    def test_live_control_and_speed_changes(self):
        city, traffic = self.cross(True)
        def edit(tick, native):
            if tick == 30:
                traffic.speed_mph = 12
                native.set_speed(12)
                city.standard_intersections[0].set_all_way_stop(False)
                for connection in city.standard_intersections[0].lane_connections:
                    if id(connection) in native._connection_ids:
                        native.set_control(connection, connection.control.kind)
        self.drive(city, traffic, 500, edit=edit)

    def test_following_rewind_resize_and_removal(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (500, 0), (650, 100)])
        traffic = TestTrafficSimulation(spawn_interval=1000)
        a = traffic.spawn_car(city, *city.cul_de_sacs)
        traffic.place_vehicle(a.id, 100)
        b = traffic.spawn_car(city, *city.cul_de_sacs)
        self.assertIsNotNone(b)
        def edit(tick, native):
            if tick == 30:
                traffic.resize_vehicle(a.id, length=30, width=8)
                native.resize(a.id, 30, 8)
            if tick == 50:
                traffic.place_vehicle(a.id, 180)
                native.place(a.id, 180)
            if tick == 60:
                traffic.place_vehicle(b.id, 5)
                native.place(b.id, 5)
            if tick == 100:
                traffic.remove_vehicle(a.id)
                native.remove(a.id)
        self.drive(city, traffic, 400, edit=edit)

    def test_large_timestep_matches_python_substeps(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (500, 0), (650, 100)])
        traffic = TestTrafficSimulation(spawn_interval=1000)
        self.assertIsNotNone(traffic.spawn_car(city, *city.cul_de_sacs))
        # Stop before completion: completion buffers represent the last call.
        self.drive(city, traffic, 20, dt=0.2)

    def test_completion_in_first_substep_is_retained_until_next_call(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        traffic = TestTrafficSimulation(spawn_interval=1000)
        car = traffic.spawn_car(city, *city.cul_de_sacs)
        traffic.place_vehicle(car.id, car.total_length - 0.1)
        self.assertEqual(self.drive(city, traffic, 3, dt=0.2), 1)

    def test_cautious_drivers_and_speed_caps(self):
        from merge_lab import scenario_catalog
        scenario = next(s for s in scenario_catalog() if s.name == 'roundabout-simultaneous-entry')
        city, traffic = scenario.build(19)
        for car in traffic.cars:
            car.brain.merge_style = 'cautious'
            car.speed_cap_mph = 8
        self.drive(city, traffic, 700)

    def test_imported_committed_deadlock_winner_waits_for_blocker(self):
        from car_brain import BehaviorState
        city = world_from_dict(json.loads(
            (Path(__file__).parent / 'fixtures/slip_lanes.json').read_text())).city_map
        traffic = TestTrafficSimulation(spawn_interval=1000, update_mode='data_first')
        ends = {j.position: j for j in city.cul_de_sacs}
        joining = traffic.spawn_car(city, ends[(2630.0, 1846.0)], ends[(3356.0, 1770.0)])
        circulating = traffic.spawn_car(city, ends[(2968.0, 1586.0)], ends[(3356.0, 1770.0)])
        first, entry = joining.controlled_movements[:2]
        target = next(s for s in circulating.route_segments if s[2] == entry[2].merge_target)
        traffic.place_vehicle(joining.id, first[0] - joining.length / 2 - 5)
        joining.speed = 0
        joining.brain.state = BehaviorState.ENTERING_INTERSECTION
        traffic.place_vehicle(circulating.id, target[0] - 65)
        circulating.speed = 17.6
        self.assertTrue(traffic.stop_coordinator.claim_temporary_winner(joining.id, first[2]))
        joining._claimed_movement = first[2]
        resolver = traffic.deadlock_resolver
        resolver.stall_seconds = 5
        resolver.winner_id, resolver.winner_movement_id = joining.id, first[2].id
        resolver._waiting_seconds[joining.id] = 4.75
        def remove_blocker(tick, native):
            if tick == 2:
                traffic.remove_vehicle(circulating.id)
                native.remove(circulating.id)
        self.drive(city, traffic, 50, edit=remove_blocker)

    def test_sync_updates_existing_render_vehicles_and_reports_completion(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        traffic = TestTrafficSimulation(spawn_interval=1000)
        car = traffic.spawn_car(city, *city.cul_de_sacs)
        with NativeTrafficEngine.from_simulation(traffic) as native:
            native.step(0.1)
            state = native.snapshot()[car.id]
            self.assertEqual(native.sync([car]), [])
            self.assertEqual(car.position, state.position)
            self.assertEqual(car.distance, state.distance)
            self.assertEqual(car.brain.desired_speed, state.desired_speed)
            native.place(car.id, car.total_length - 0.1)
            native.step(0.2)
            self.assertEqual(native.sync([car]), [car])
            self.assertEqual(car.position, car.points[-1])

    def test_uploaded_slip_lane_and_roundabout_maps(self):
        for filename in ('slip_lanes.json', 'roundabout_test.json'):
            with self.subTest(map=filename):
                city = world_from_dict(json.loads(
                    (Path(__file__).parent / 'fixtures' / filename).read_text())).city_map
                traffic = TestTrafficSimulation(rng=random.Random(42))
                for junction in city.cul_de_sacs:
                    traffic.toggle_junction(junction)
                self.assertGreater(self.drive(city, traffic, 1600), 0)

    def test_native_step_has_no_python_driver_callbacks(self):
        from car_brain import CarBrain
        from traffic_testbed import RoutedRoadVehicle
        city, traffic = self.cross(True)
        with NativeTrafficEngine.from_simulation(traffic) as native:
            with patch.object(CarBrain, 'decide', side_effect=AssertionError('Python decision')):
                with patch.object(RoutedRoadVehicle, 'advance', side_effect=AssertionError('Python movement')):
                    for _ in range(100):
                        native.step(0.05)
            self.assertTrue(any(s.distance > 0 for s in native.snapshot().values()))

    def test_empty_invalid_input_and_closed_engine(self):
        with NativeTrafficEngine() as native:
            native.step(0)
            native.step(0.2)
            self.assertEqual(native.snapshot(), {})
            for dt in (-1, float('nan'), float('inf')):
                with self.assertRaises(ValueError):
                    native.step(dt)
        with self.assertRaises(RuntimeError):
            native.step(0.05)

    def test_comparison_rejects_corrupted_native_state(self):
        city, traffic = self.cross(False)
        with NativeTrafficEngine.from_simulation(traffic) as native:
            native.place(traffic.cars[0].id, 10)
            with self.assertRaises(AssertionError):
                self.assert_states(native, traffic.cars, 'deliberately corrupted distance')
