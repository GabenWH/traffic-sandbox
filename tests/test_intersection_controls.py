"""Behavior tests for runtime all-way-stop arbitration."""

import cProfile
from dataclasses import replace
import unittest

from city import CityMap, Terrain
from intersection_controls import AllWayStopCoordinator, movements_conflict
from mobility import VEHICLE_LAYER, build_vehicle_layer
from models import ControlDefinition, ControlType, IntersectionKind, RoadPort


class MovementConflictCacheTests(unittest.TestCase):
    def make_city(self, *, roundabout=False):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        if roundabout:
            city.standard_intersections[0].kind = IntersectionKind.ROUNDABOUT
            city.rebuild_mobility_network()
        return city

    def connections(self, city):
        graph = city.mobility.layers[VEHICLE_LAYER].graph
        return [
            transition.edge.value
            for node in graph.nodes
            for transition in graph.transitions_from(node)
            if transition.edge.kind == "lane_connection"
        ]

    def test_compiled_movements_do_not_recompare_road_ports(self):
        for roundabout in (False, True):
            with self.subTest(roundabout=roundabout):
                connections = self.connections(self.make_city(roundabout=roundabout))
                profiler = cProfile.Profile()
                with profiler:
                    results = [
                        movements_conflict(a, b)
                        for a in connections for b in connections
                    ]
                self.assertEqual(set(results), {False, True})
                port_comparisons = sum(
                    entry.callcount for entry in profiler.getstats()
                    if entry.code == RoadPort.__eq__.__code__
                )
                self.assertEqual(port_comparisons, 0)

    def test_compiled_results_match_standalone_movements(self):
        for roundabout in (False, True):
            with self.subTest(roundabout=roundabout):
                connections = self.connections(self.make_city(roundabout=roundabout))
                standalone = [replace(connection) for connection in connections]
                for i, a in enumerate(connections):
                    for j, b in enumerate(connections):
                        self.assertEqual(
                            movements_conflict(a, b),
                            movements_conflict(standalone[i], standalone[j]),
                        )

    def test_recompiling_refreshes_conflicts_after_path_edit(self):
        city = self.make_city()
        connections = city.standard_intersections[0].lane_connections
        a, b = next(
            (a, b) for a in connections for b in connections
            if not movements_conflict(a, b)
        )
        a.path = [(0, 0), (100, 100)]
        b.path = [(0, 100), (100, 0)]

        build_vehicle_layer(city.roads, city.intersections)

        self.assertTrue(movements_conflict(a, b))
        self.assertTrue(movements_conflict(b, a))

    def test_new_network_does_not_reuse_old_conflicts(self):
        city = self.make_city()
        old = self.connections(city)
        city.add_road([(0, 0), (600, 600)])
        new = self.connections(city)
        for a in new:
            for b in old:
                self.assertEqual(
                    movements_conflict(a, b),
                    movements_conflict(replace(a), replace(b)),
                )

    def test_standalone_movements_use_current_paths(self):
        connections = self.connections(self.make_city())
        a, b = next(
            (replace(a), replace(b)) for a in connections for b in connections
            if a.intersection_id == b.intersection_id
            and not movements_conflict(a, b)
        )
        self.assertFalse(movements_conflict(a, b))
        a.path = [(0, 0), (100, 100)]
        b.path = [(0, 100), (100, 0)]
        self.assertTrue(movements_conflict(a, b))


class AllWayStopCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (400, 100)])
        city.add_road([(200, 0), (200, 200)])
        self.junction = city.standard_intersections[0]
        for connection in self.junction.lane_connections:
            connection.control = ControlDefinition(ControlType.STOP)
        self.connections = self.junction.lane_connections

    def test_first_fully_stopped_car_gets_priority(self) -> None:
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("later", self.connections[1], 2.0)
        coordinator.observe_stop("first", self.connections[0], 1.0)

        self.assertTrue(coordinator.can_claim("first", self.connections[0]))
        self.assertFalse(coordinator.can_claim("later", self.connections[1]))

    def test_tied_arrivals_are_deterministic(self) -> None:
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("z-car", self.connections[0], 1.0)
        coordinator.observe_stop("a-car", self.connections[0], 1.0)

        self.assertTrue(coordinator.can_claim("a-car", self.connections[0]))
        self.assertFalse(coordinator.can_claim("z-car", self.connections[0]))

    def test_claim_blocks_others_until_released(self) -> None:
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("first", self.connections[0], 1.0)
        self.assertTrue(coordinator.claim("first", self.connections[0]))
        coordinator.observe_stop("second", self.connections[1], 2.0)

        self.assertFalse(coordinator.can_claim("second", self.connections[1]))
        coordinator.release("first")
        self.assertTrue(coordinator.can_claim("second", self.connections[1]))

    def test_temporary_winner_can_break_waiting_order_but_not_active_claim(self) -> None:
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("older", self.connections[0], 1.0)
        coordinator.observe_stop("winner", self.connections[1], 2.0)

        self.assertTrue(coordinator.claim_temporary_winner(
            "winner", self.connections[1]))

        coordinator.observe_stop("next", self.connections[2], 3.0)
        self.assertFalse(coordinator.claim_temporary_winner(
            "next", self.connections[2]))


if __name__ == "__main__":
    unittest.main()
