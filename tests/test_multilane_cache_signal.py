"""Crossovers between multilane behavior and persistent native caches."""
import ctypes as C
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from city import CityMap, Terrain
from intersection_controls import FixedTimeSignalController, SignalPhase, SignalPlan
from mobility import lane_position_at_distance, vehicle_link_points, vehicle_route_points
from models import ControlDefinition, ControlType, polyline_length
from native_spawning import LaneChange
from pathfinding import Path as RoutePath
from traffic_route_state import RouteState
from traffic_testbed import (
    RoadVehicleSimulation,
    _controlled_movement_ranges,
    _route_occupancy_segments,
)


def lane_of(link):
    return getattr(link.value, 'lane', link.value)


def first_lane(route):
    return lane_of(next(link for link in route.edges if link.kind == 'lane'))


def without_empty_port_links(route):
    # Port and lane-access links can have zero-length geometry. Remove them
    # to build routes with byte-identical native geometry and sections while
    # preserving the real endpoint markers and lane links.
    edges = tuple(link for link in route.edges
                  if link.kind not in ('road_port', 'lane_access')
                  or polyline_length(vehicle_link_points(link)) > 0)
    return RoutePath(tuple(range(len(edges) + 1)), edges, route.cost)


def route_proxy(route):
    return SimpleNamespace(
        route=route,
        points=vehicle_route_points(route),
        route_segments=_route_occupancy_segments(route),
        controlled_movements=_controlled_movement_ranges(route),
        _route_cache=RouteState(),
    )


def admit(sim, route, name):
    return sim.admit_route(route, vehicle_id=name, source_id='west', destination_id='east')


def remove_without_discard(sim, backend, car):
    # Removal publishes changes to the Python view too. Keep that publication
    # from treating its own mirrored writes as a new external edit.
    backend.publishing = True
    try:
        sim.remove_vehicle(car.id)
    finally:
        backend.publishing = False
    assert sim._native_controller is backend


def native_route_id(backend, car):
    row = LaneChange()
    backend.engine._call('nt_lane_change_state', backend.engine._handles[car.id], C.byref(row))
    return row.route


class MultilaneRouteCacheTests(unittest.TestCase):
    def scene(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (4000, 100)], forward_lane_count=2, reverse_lane_count=2)
        west, east = sorted(city.cul_de_sacs, key=lambda junction: junction.position[0])
        simulation = RoadVehicleSimulation(spawn_interval=1000)
        backend = simulation._native_backend(city)
        self.addCleanup(simulation._discard_native)
        flexible = city.find_vehicle_route_between(west, east)
        self.assertIsNotNone(flexible)
        lane = first_lane(flexible)
        start = lane_position_at_distance(lane, 0)
        end = lane_position_at_distance(lane, polyline_length(lane.points))
        return city, west, east, lane, start, end, simulation, backend, flexible

    def test_value_cache_distinguishes_exact_and_flexible_endpoints_in_both_orders(self):
        for reverse in (False, True):
            with self.subTest(reverse_registration_order=reverse):
                city, west, east, lane, start, end, sim, backend, junction = self.scene()
                raw_paths = (
                    junction,
                    city.find_vehicle_route_between(west, end),
                    city.find_vehicle_route_between(start, east),
                    city.find_vehicle_route_between(start, end),
                )
                self.assertTrue(all(path is not None for path in raw_paths))
                paths = tuple(without_empty_port_links(path) for path in raw_paths)
                self.assertTrue(all(path is not None for path in paths))
                self.assertEqual([(p.edges[0].kind == 'route_endpoint',
                                   p.edges[-1].kind == 'route_endpoint') for p in paths],
                                 [(True, True), (True, False), (False, True), (False, False)])
                proxies = [route_proxy(path) for path in paths]
                for proxy in proxies[1:]:
                    self.assertEqual(tuple(proxy.points), tuple(proxies[0].points))
                    self.assertEqual(proxy.route_segments, proxies[0].route_segments)
                    self.assertEqual(proxy.controlled_movements, proxies[0].controlled_movements)
                order = list(reversed(proxies)) if reverse else proxies
                ids = [backend.engine.register_route(proxy) for proxy in order]
                self.assertEqual(len(set(ids)), 4)
                # Value caching still deduplicates independently built equivalent paths.
                same_junction = without_empty_port_links(city.find_vehicle_route_between(west, east))
                self.assertEqual(backend.engine.register_route(route_proxy(same_junction)),
                                 backend.engine.register_route(proxies[0]))

                blocker = admit(sim, paths[3], 'blocker')
                self.assertIsNotNone(blocker)
                self.assertIs(first_lane(blocker.route), lane)
                self.assertIsNone(admit(sim, paths[1], 'exact-end-blocked'))
                self.assertIsNone(admit(sim, paths[2], 'exact-start-blocked'))
                alternate = admit(sim, paths[0], 'flexible')
                self.assertIsNotNone(alternate)
                self.assertIsNot(first_lane(alternate.route), lane)

                remove_without_discard(sim, backend, blocker)
                exact = admit(sim, paths[1], 'exact-after-flexible')
                self.assertIsNotNone(exact)
                self.assertIs(first_lane(exact.route), lane)
                self.assertEqual(exact.route.edges[-1].kind, 'lane')
                self.assertAlmostEqual(exact.points[-1][0], end.point[0])
                self.assertAlmostEqual(exact.points[-1][1], end.point[1])

    def test_reused_external_route_id_cannot_reuse_an_old_lane_alternative(self):
        city, west, east, lane, start, end, sim, backend, flexible = self.scene()
        engine = backend.engine
        engine.route_cache_limit = 1
        blocker = admit(sim, city.find_vehicle_route_between(start, end), 'blocker')
        self.assertIsNotNone(blocker)
        first = admit(sim, flexible, 'first')
        self.assertIsNotNone(first)
        self.assertIsNot(first_lane(first.route), lane)
        original_id = backend.external_routes[id(flexible)][1]
        remove_without_discard(sim, backend, first)
        engine.trim_routes()
        self.assertNotIn(original_id, engine._routes.values())

        short_end = lane_position_at_distance(lane, polyline_length(lane.points) / 2)
        exact = city.find_vehicle_route_between(west, short_end)
        self.assertIsNotNone(exact)
        self.assertIs(first_lane(exact), lane)
        # An exact destination on the blocked lane has no valid alternative.
        # A stale alternative would instead admit the car to the old full route.
        self.assertIsNone(admit(sim, exact, 'short-exact'))
        self.assertEqual(backend.external_routes[id(exact)][1], original_id)

    def test_released_compiled_alternative_is_not_reused_after_its_id_is_reassigned(self):
        city, west, east, lane, start, end, sim, backend, flexible = self.scene()
        engine = backend.engine
        blocker = admit(sim, city.find_vehicle_route_between(start, end), 'blocker')
        self.assertIsNotNone(blocker)
        first = admit(sim, flexible, 'first')
        self.assertIsNotNone(first)
        alternate_lane = first_lane(first.route)
        self.assertIsNot(alternate_lane, lane)
        source_id = backend.external_routes[id(flexible)][1]
        alternate_id = native_route_id(backend, first)
        self.assertNotEqual(source_id, alternate_id)
        remove_without_discard(sim, backend, first)
        self.assertEqual(engine._call('nt_route_release', alternate_id), 1)

        # Occupy the freed slot with a different partial route in the same lane.
        partial_start = lane_position_at_distance(alternate_lane, 1000)
        partial_end = lane_position_at_distance(alternate_lane, 2000)
        partial = city.find_vehicle_route_between(partial_start, partial_end)
        self.assertEqual(engine.register_route(route_proxy(partial)), alternate_id)

        second = admit(sim, flexible, 'second')
        self.assertIsNotNone(second)
        self.assertIs(first_lane(second.route), alternate_lane)
        self.assertNotEqual(native_route_id(backend, second), alternate_id)
        self.assertAlmostEqual(second.points[0][0], alternate_lane.points[0][0])
        self.assertAlmostEqual(second.points[-1][0], alternate_lane.points[-1][0])
        self.assertAlmostEqual(second.points[-1][1], alternate_lane.points[-1][1])


    def test_native_route_queries_preserve_exact_and_junction_origins_in_both_orders(self):
        # Probe a separate engine to identify which lane the native junction
        # query initially chooses without warming the cache under test.
        _, probe_west, probe_east, _, _, _, _, probe_backend, _ = self.scene()
        native_junction = probe_backend.find_route(probe_west, probe_east)
        native_lane_index = first_lane(native_junction).lane_index

        for exact_first in (False, True):
            with self.subTest(exact_first=exact_first):
                city, west, east, _, _, _, sim, backend, _ = self.scene()
                source_lane = next(lane for lane in city.roads[0].lanes
                                   if lane.direction == 'forward'
                                   and lane.lane_index == native_lane_index)
                origin = lane_position_at_distance(source_lane, 0)
                if exact_first:
                    exact = backend.find_route(origin, east)
                    flexible = backend.find_route(west, east)
                else:
                    flexible = backend.find_route(west, east)
                    exact = backend.find_route(origin, east)
                self.assertIsNotNone(exact)
                self.assertIsNotNone(flexible)

                # Inspect admissions separately, so neither car's occupancy
                # can influence the lane chosen by the other one.
                exact_car = admit(sim, exact, 'exact-query')
                self.assertIsNotNone(exact_car)
                exact_lane = first_lane(exact_car.route)
                remove_without_discard(sim, backend, exact_car)
                flexible_car = admit(sim, flexible, 'junction-query')
                self.assertIsNotNone(flexible_car)
                flexible_lane = first_lane(flexible_car.route)
                remove_without_discard(sim, backend, flexible_car)

                self.assertNotEqual(exact.edges[0].kind, 'route_endpoint')
                self.assertEqual(flexible.edges[0].kind, 'route_endpoint')
                self.assertIs(exact_lane, source_lane)
                forward_lanes = [lane for lane in city.roads[0].lanes if lane.direction == 'forward']
                outside = max(forward_lanes, key=lambda lane: lane.lane_index)
                self.assertIs(flexible_lane, outside)

    def test_inactive_alternatives_remain_bounded_for_distinct_exact_trips(self):
        city = CityMap(terrain=Terrain(trees=[]))
        for low, high, count in ((0, 1000, 2), (1000, 1500, 1), (1500, 5000, 2)):
            city.add_road([(low, 100), (high, 100)],
                          forward_lane_count=count, reverse_lane_count=count)
        west = min(city.cul_de_sacs, key=lambda junction: junction.position[0])
        final_road = max(city.roads, key=lambda road: road.centerline[0][0])
        final_lane = next(lane for lane in final_road.lanes
                          if lane.direction == 'forward' and lane.lane_index == 0)
        sim = RoadVehicleSimulation(spawn_interval=1000)
        backend = sim._native_backend(city)
        self.addCleanup(sim._discard_native)
        backend.engine.route_cache_limit = 1

        first_destination = lane_position_at_distance(final_lane, 300)
        first_route = city.find_vehicle_route_between(west, first_destination)
        source_lane = first_lane(first_route)
        blocker_route = city.find_vehicle_route_between(
            lane_position_at_distance(source_lane, 0),
            lane_position_at_distance(source_lane, polyline_length(source_lane.points)))
        blocker = admit(sim, blocker_route, 'blocker')
        self.assertIsNotNone(blocker)

        max_id = -1
        for index in range(160):
            destination = lane_position_at_distance(final_lane, 300 + index * 10)
            route = city.find_vehicle_route_between(west, destination)
            self.assertIsNotNone(route)
            self.assertIs(first_lane(route), source_lane)
            car = admit(sim, route, f'exact-{index}')
            self.assertIsNotNone(car, f'trip {index} must use a reachable alternate lane')
            self.assertIsNot(first_lane(car.route), source_lane)
            max_id = max(max_id, backend.external_routes[id(route)][1], native_route_id(backend, car))
            remove_without_discard(sim, backend, car)
        self.assertLess(max_id, 140, 'inactive native lane-alternative routes should reuse slots')


class MultilaneSignalCacheTests(unittest.TestCase):
    def scene(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (1200, 100)], forward_lane_count=3, reverse_lane_count=3)
        city.add_road([(600, -200), (600, 400)])
        west = next(j for j in city.cul_de_sacs if j.position == (0, 100))
        east = next(j for j in city.cul_de_sacs if j.position == (1200, 100))
        policy = next(c for c in city.standard_intersections[0].lane_connections
                      if c.source_output.heading[0] > .9 and c.maneuver.kind.value == 'through')
        sim = RoadVehicleSimulation(spawn_interval=1000)
        self.addCleanup(sim._discard_native)
        return city, west, east, policy, sim

    @staticmethod
    def controller(*movement_ids):
        return FixedTimeSignalController(SignalPlan((SignalPhase(120, set(movement_ids), 0, 0),)))

    def test_live_policy_edit_and_signal_aliases_update_every_derived_lane(self):
        city, west, east, policy, sim = self.scene()
        backend = sim._native_backend(city)
        engine = backend.engine
        sim.update(city, .05)
        derived = [connection for connection in engine._connections
                   if getattr(connection, '_policy_source', connection) is policy]
        self.assertEqual(len(derived), 3)
        indices = [engine._connection_ids[id(connection)] for connection in derived]
        self.assertTrue(all(connection.control.kind is ControlType.UNCONTROLLED for connection in derived))

        policy.control = ControlDefinition(ControlType.SIGNAL, 'gate')
        sim.signal_controllers['gate'] = self.controller(policy.id)
        with patch.object(engine, 'set_control', wraps=engine.set_control) as calls:
            sim.update(city, .05)
        self.assertEqual({id(call.args[0]) for call in calls.call_args_list},
                         {id(connection) for connection in derived})
        self.assertEqual(calls.call_count, len(derived))
        self.assertTrue(all(connection.control == policy.control for connection in derived))
        self.assertEqual([engine._signal_aspects[i] for i in indices], [1, 1, 1])

        sim.signal_controllers['gate'] = self.controller(derived[1].id)
        sim.update(city, .05)
        self.assertEqual([engine._signal_aspects[i] for i in indices], [0, 1, 0])

        # A controller-ID edit must revoke old permissions even when the signal
        # state itself has not changed and the native control kind remains SIGNAL.
        policy.control = ControlDefinition(ControlType.SIGNAL, 'other')
        sim.update(city, .05)
        self.assertEqual([engine._signal_aspects[i] for i in indices], [0, 0, 0])
        policy.control = ControlDefinition(ControlType.STOP)
        with patch.object(engine, 'set_control', wraps=engine.set_control) as calls:
            sim.update(city, .05)
        self.assertEqual({id(call.args[0]) for call in calls.call_args_list},
                         {id(connection) for connection in derived})
        self.assertTrue(all(connection.control.kind is ControlType.STOP for connection in derived))

        class NoScan(list):
            def __iter__(self):
                raise AssertionError('unchanged tick scanned all connections')

        connections = engine._connections
        engine._connections = NoScan(connections)
        try:
            with patch.object(engine, 'set_control', wraps=engine.set_control) as calls:
                for _ in range(4):
                    sim.update(city, .05)
            self.assertEqual(calls.call_count, 0)
        finally:
            engine._connections = connections

    def test_existing_cars_stop_for_a_live_policy_edit_then_all_clear_green(self):
        city, west, east, policy, sim = self.scene()
        cars = [sim.spawn_car(city, west, east) for _ in range(3)]
        self.assertTrue(all(car is not None for car in cars))
        for car in cars:
            self.assertIs(getattr(car.controlled_movements[0][2], '_policy_source', None), policy)
            car.place(250)
            car.speed = 0
        backend = sim._native_backend(city)
        backend.configure()
        policy.control = ControlDefinition(ControlType.SIGNAL, 'gate')
        for _ in range(400):
            sim.update(city, .05)
        self.assertIs(sim._native_controller, backend)
        self.assertTrue(all(car.position[0] < 600 and car.speed < .1 for car in cars))

        sim.signal_controllers['gate'] = self.controller(policy.id)
        for _ in range(260):
            sim.update(city, .05)
        self.assertTrue(all(car.position[0] > 650 for car in cars))


if __name__ == '__main__':
    unittest.main()
