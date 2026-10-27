"""Route progress changes local cursors, while route facts remain reusable."""

import unittest
from types import SimpleNamespace

from models import ManeuverType
from simulation_cache import CachedValue, CacheReadError, UndeclaredDependencyError
from traffic_route_state import RouteGeometry, RouteState
from traffic_testbed import _position_and_heading


def connection(name, *, role="", kind=ManeuverType.THROUGH):
    return SimpleNamespace(id=name, roundabout_role=role,
                           maneuver=SimpleNamespace(kind=kind),
                           control_offset=0, source_output=SimpleNamespace(id=name))


class CountedTuple(tuple):
    reads = 0

    def __iter__(self):
        for value in super().__iter__():
            self.reads += 1
            yield value

    def __getitem__(self, item):
        self.reads += 1
        return super().__getitem__(item)


class TrafficRouteStateTests(unittest.TestCase):
    def test_warm_route_read_still_declares_its_source_to_composed_caches(self):
        state = RouteState()
        first = (0, 30, connection("first"))
        second = (0, 40, connection("second"))
        state.sync((first,), ())
        self.assertIs(state.next_route(0), first)
        undeclared = CachedValue("missing route source", dependencies=(),
                                 build=lambda: state.next_route(0))
        with self.assertRaises(UndeclaredDependencyError):
            undeclared.get()
        composed = CachedValue("next route", dependencies=state._facts.dependencies,
                               build=lambda: state.next_route(0))
        self.assertIs(composed.get(), first)
        state.sync((second,), ())
        self.assertIs(composed.get(), second)

    def test_warm_route_read_rejects_an_unpublished_source_mutation(self):
        state = RouteState()
        state.sync(((0, 30, connection("first")),), ())
        state.next_route(0)
        with state._revision.mutate():
            with self.assertRaises(CacheReadError):
                state.next_route(0)

    def test_geometry_keeps_reference_heading_at_rounded_corner(self):
        from math import sqrt

        points = ((0, 0), (0, 1), (3, 0), (5, 5))
        distance = 1 + sqrt(10)
        actual = RouteGeometry().position_and_heading(points, distance)
        expected = _position_and_heading(points, distance)
        self.assertEqual(actual[1], expected[1])

    def test_claimed_ranges_include_each_visit_to_the_same_connection(self):
        repeated, other = connection("repeat"), connection("other")
        movements = ((10, 30, repeated), (40, 50, other), (60, 80, repeated))
        state = RouteState()
        state.sync(movements, ())
        self.assertEqual(list(state.claimed_ranges((repeated,))),
                         [movements[0], movements[2]])

    def test_steady_progress_does_not_scan_completed_movements(self):
        movements = CountedTuple((i * 100, i * 100 + 30, connection(str(i)))
                                 for i in range(1000))
        state = RouteState()
        state.sync(movements, ())
        self.assertIs(state.next_route(50010), movements[500])
        movements.reads = 0
        for distance in (50011, 50012, 50013):
            self.assertIs(state.next_route(distance), movements[500])
            self.assertIs(state.next_controlled(distance, 14, lambda _: False), movements[500])
        self.assertLess(movements.reads, 25)

    def test_control_claim_changes_reconsider_the_current_range(self):
        first, second = connection("first"), connection("second")
        movements = ((10, 30, first), (32, 50, second))
        state = RouteState()
        state.sync(movements, ())
        claims = {id(first)}
        has_claim = lambda item: id(item) in claims
        self.assertIs(state.next_controlled(15, 14, has_claim), movements[1])
        claims.clear()
        self.assertIs(state.next_controlled(15, 14, has_claim), movements[0])
        self.assertIs(state.next_controlled(37, 14, has_claim), movements[1])
        self.assertIs(state.next_controlled(0, 14, has_claim), movements[0])

    def test_exit_and_u_turn_are_skipped_only_by_control_cursor(self):
        movements = ((0, 10, connection("exit", role="exit")),
                     (10, 20, connection("u", kind=ManeuverType.U_TURN)),
                     (20, 30, connection("straight")))
        state = RouteState()
        state.sync(movements, ())
        self.assertIs(state.next_route(0), movements[0])
        self.assertIs(state.next_controlled(0, 14, lambda _: False), movements[2])
        self.assertIs(state.next_roundabout(-7), movements[0])
        self.assertIsNone(state.next_roundabout(10))

    def test_incoming_signal_and_chain_facts_refresh_on_route_replacement(self):
        movement = (100, 120, connection("exit", role="exit"))
        following = (125, 145, connection("following"))
        segments = ((0, 80, ("lane", "a"), 0),
                    (80, 100, ("lane", "b"), 0))
        state = RouteState()
        state.sync((movement, following), segments)
        self.assertEqual(state.incoming(movement), ("lane", "b"))
        self.assertEqual(state.signal_start(movement), 80)
        self.assertEqual(list(state.following(movement)), [following])
        state.sync((movement, following), ((0, 100, ("road_port", "port"), 0),))
        self.assertEqual(state.incoming(movement), ("road_port", "port"))
        self.assertIsNone(state.signal_start(movement))

    def test_geometry_matches_reference_at_corners_rewinds_and_endpoints(self):
        points = ((0, 0), (0, 0), (30, 0), (30, 40), (90, 40))
        geometry = RouteGeometry()
        for distance in (0, 1, 30, 30.01, 70, 130, 500, 10, -1):
            actual = geometry.position_and_heading(points, distance)
            expected = _position_and_heading(points, distance)
            for got, wanted in zip((*actual[0], *actual[1]), (*expected[0], *expected[1])):
                self.assertAlmostEqual(got, wanted, places=10)
        replacement = ((0, 0), (0, 100))
        self.assertEqual(geometry.position_and_heading(replacement, 50), ((0, 50), (0, 1)))

    def test_geometry_steady_motion_reads_only_local_points(self):
        points = CountedTuple((i * 10, i % 3) for i in range(1001))
        geometry = RouteGeometry()
        geometry.position_and_heading(points, 5000)
        points.reads = 0
        for distance in (5001, 5002, 5003):
            actual = geometry.position_and_heading(points, distance)
            expected = _position_and_heading(tuple(tuple.__iter__(points)), distance)
            for got, wanted in zip(actual[0], expected[0]):
                self.assertAlmostEqual(got, wanted, places=8)
        self.assertLess(points.reads, 15)


if __name__ == "__main__":
    unittest.main()
