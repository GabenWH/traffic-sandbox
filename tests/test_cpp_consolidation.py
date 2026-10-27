"""One native driver, explicit world edits, and demand-driven Python queries."""
import random
import unittest
from unittest.mock import patch

from city import CityMap, Terrain
from car_brain import CarBrain
from freeway_simulator import parse_args
from traffic_testbed import RoadVehicleSimulation, RoutedRoadVehicle
from traffic_occupancy import TrafficOccupancyIndex
from intersection_controls import FixedTimeSignalController, SignalPlan, SignalPhase
from tests.test_native_signalized_intersections import make_scenario


class CppConsolidationTests(unittest.TestCase):
    def test_only_cpp_is_available_and_is_the_application_default(self):
        self.assertEqual(RoadVehicleSimulation().update_mode, 'cpp')
        self.assertEqual(parse_args([]).traffic_engine, 'cpp')
        for old in ('legacy', 'data_first', 'native', 'unknown'):
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'cpp'):
                RoadVehicleSimulation(update_mode=old)

    def test_no_python_driving_or_occupancy_maintenance_on_ticks(self):
        for output in ('copy', 'shared'):
            with self.subTest(output=output):
                city = CityMap(terrain=Terrain(trees=[]))
                city.add_road([(0, 100), (1000, 100)])
                traffic = RoadVehicleSimulation(native_output_mode=output, spawn_interval=1000)
                leader = traffic.spawn_car(city, *city.cul_de_sacs)
                traffic.place_vehicle(leader.id, 100)
                follower = traffic.spawn_car(city, *city.cul_de_sacs)
                traffic._native_backend(city)
                index = traffic.occupancy
                with patch.object(traffic, '_observe_signal_occupancy', side_effect=AssertionError('Python signal body scan')), \
                     patch.object(index, 'is_current', side_effect=AssertionError('per-car Python check')), \
                     patch.object(index, 'publish_changes', side_effect=AssertionError('eager publication')), \
                     patch.object(index, 'rebuild', side_effect=AssertionError('eager rebuild')), \
                     patch.object(CarBrain, 'decide', side_effect=AssertionError('Python driver')), \
                     patch.object(RoutedRoadVehicle, 'advance', side_effect=AssertionError('Python motion')):
                    for _ in range(10):
                        traffic.update(city, .05)
                with patch.object(index, 'rebuild', wraps=index.rebuild) as refresh:
                    gap = index.lead_gap(follower, 200)
                    self.assertAlmostEqual(gap, leader.distance-follower.distance-14)
                    self.assertEqual(refresh.call_count, 1)
                    self.assertAlmostEqual(index.lead_gap(follower, 200), gap)
                    self.assertEqual(refresh.call_count, 1)
                traffic._discard_native()

    def test_python_vehicle_and_driver_edits_are_imported_without_polling(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (1000, 100)])
        traffic = RoadVehicleSimulation(spawn_interval=1000)
        car = traffic.spawn_car(city, *city.cul_de_sacs)
        traffic.update(city, .05)
        car.brain.merge_style = 'cautious'
        car.speed_cap_mph = 5
        car.speed = 1
        self.assertIsNone(traffic._native_controller)
        traffic.update(city, .05)
        self.assertLess(car.speed, 5*22/15)
        self.assertEqual(car.brain.merge_style, 'cautious')
        traffic._discard_native()

    def test_yellow_commitment_survives_a_world_edit_and_backend_recreation(self):
        for output in ('copy', 'shared'):
            city, traffic, car, (start, _, connection) = make_scenario(controller=False, speed=25)
            traffic.native_output_mode = output
            traffic.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
                SignalPhase(.1, {connection.id}, 5, .1),)))
            traffic.place_vehicle(car.id, start-car.length/2-8)
            traffic.elapsed_time = .1
            traffic.update(city, .05)
            self.assertTrue(car.brain._yellow_go)
            car.speed = 0  # Explicit edit must preserve the already latched decision.
            traffic.update(city, .05)
            self.assertTrue(car.brain._yellow_go)
            self.assertGreater(car.speed, 0)
            traffic._discard_native()

    def test_expected_red_wait_does_not_age_into_a_deadlock(self):
        city, traffic, car, _ = make_scenario(controller=False)
        for _ in range(120):
            traffic.update(city, .05)
        self.assertEqual(car.brain.wait_reason, 'red signal')
        self.assertEqual(traffic.deadlock_resolver.stall_seconds, 0)
        self.assertIsNone(traffic.deadlock_resolver.winner_id)

    def test_targeted_query_sees_scalar_edits_while_backend_is_absent(self):
        for output in ('copy', 'shared'):
            city = CityMap(terrain=Terrain(trees=[]))
            city.add_road([(0, 100), (1000, 100)])
            traffic = RoadVehicleSimulation(native_output_mode=output)
            leader = traffic.spawn_car(city, *city.cul_de_sacs)
            traffic.place_vehicle(leader.id, 100)
            follower = traffic.spawn_car(city, *city.cul_de_sacs)
            traffic.update(city, 0)
            self.assertEqual(traffic.occupancy.lead_gap(follower, 500), 86)
            leader.distance = 200
            self.assertEqual(traffic.occupancy.lead_gap(follower, 500), 186)
            leader.distance = 300
            self.assertEqual(traffic.occupancy.lead_gap(follower, 500), 286)
            self.assertTrue(traffic.occupancy.is_current(leader))
            traffic._discard_native()

    def test_green_short_link_can_clear_previous_claimed_junction(self):
        import json
        from pathlib import Path
        from persistence import world_from_dict
        from models import ControlDefinition, ControlType
        city = world_from_dict(json.loads((Path(__file__).parent / 'fixtures/slip_lanes.json').read_text())).city_map
        traffic = RoadVehicleSimulation(spawn_interval=1000)
        ends = {j.position: j for j in city.cul_de_sacs}
        car = traffic.spawn_car(city, ends[(2630.,1846.)], ends[(3356.,1770.)])
        previous, following = car.controlled_movements[:2]
        following[2].control = ControlDefinition(ControlType.SIGNAL, 'main')
        traffic.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
            SignalPhase(120, {following[2].id}, 0, 0),)))
        traffic.place_vehicle(car.id, following[0]-car.length/2)
        car.speed = 0
        self.assertTrue(traffic.stop_coordinator.claim_temporary_winner(car.id, previous[2]))
        before = car.distance
        for _ in range(5):
            traffic.update(city, .05)
        self.assertGreater(car.distance, before)
        self.assertGreater(car.speed, 0)
        self.assertIsNone(traffic.deadlock_resolver.winner_id)
        traffic._discard_native()

    def test_admitted_identity_is_stable_and_source_edits_update_roster_facts(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (1000, 100)])
        traffic = RoadVehicleSimulation()
        car = traffic.spawn_car(city, *city.cul_de_sacs)
        self.assertEqual(traffic._roster_view.get()[2], 1)
        with self.assertRaisesRegex(AttributeError, 'ID is read-only'):
            car.id = 'renamed'
        car.source_type = 'external'
        self.assertEqual(traffic._roster_view.get()[2], 0)
        traffic.update(city, 0)
        traffic._discard_native()

    def test_replaced_brain_cannot_resurrect_a_removed_vehicle(self):
        for output in ('copy', 'shared'):
            city = CityMap(terrain=Terrain(trees=[]))
            city.add_road([(0, 100), (1000, 100)])
            traffic = RoadVehicleSimulation(native_output_mode=output)
            leader = traffic.spawn_car(city, *city.cul_de_sacs)
            traffic.place_vehicle(leader.id, 100)
            follower = traffic.spawn_car(city, *city.cul_de_sacs)
            old = leader.brain
            leader.brain = CarBrain()
            traffic.remove_vehicle(leader.id)
            self.assertIsNone(traffic.occupancy.lead_gap(follower, 500))
            old.desired_speed = 2
            self.assertIsNone(traffic.occupancy.lead_gap(follower, 500))
            self.assertNotIn(id(leader), traffic.occupancy._cars)
            traffic._discard_native()

    def test_deadlock_settings_can_be_edited_after_native_start(self):
        city = CityMap(terrain=Terrain(trees=[]))
        traffic = RoadVehicleSimulation()
        traffic.update(city, .05)
        traffic.deadlock_resolver.stall_threshold = .125
        traffic.update(city, .05)
        self.assertEqual(traffic.deadlock_resolver.stall_threshold, .125)
        traffic.deadlock_resolver.reset()
        traffic.update(city, 0)
        self.assertEqual(traffic.deadlock_resolver.stall_seconds, 0)
        traffic._discard_native()

    def test_native_failure_is_reported_without_a_python_fallback(self):
        city = CityMap(terrain=Terrain(trees=[]))
        with patch('native_traffic._library', side_effect=RuntimeError('compiler unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'compiler unavailable'):
                RoadVehicleSimulation().update(city, .05)
