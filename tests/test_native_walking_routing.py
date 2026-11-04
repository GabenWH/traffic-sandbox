"""Walking must use immutable native snapshots, including during concurrent reads."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import unittest

from city import CityMap, Terrain
from pedestrian_mobility import PedestrianNetwork
from pathfinding import DirectedGraph


class NativeWalkingRoutingTests(unittest.TestCase):
    def network(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0), (150, 50), (300, 50)])
        return city, city.pedestrian_network

    def test_queries_do_not_copy_or_search_python_graph(self):
        _, network = self.network()
        with patch.object(DirectedGraph, 'extend', side_effect=AssertionError('Python graph copy')), \
             patch.object(DirectedGraph, 'find_path', side_effect=AssertionError('Python graph search')):
            forward = network.route((20, 17), (280, 67))
            backward = network.route((280, 67), (20, 17))
        self.assertAlmostEqual(forward.length, backward.length)
        self.assertEqual(len(forward.points), len(backward.points))
        for a, b in zip(forward.points, reversed(backward.points)):
            self.assertAlmostEqual(a[0], b[0])
            self.assertAlmostEqual(a[1], b[1])
        self.assertGreater(len(forward.points), 2)

    def test_concurrent_queries_have_independent_results(self):
        _, network = self.network()
        pairs = [((10+i, 17), (290-i, 67)) for i in range(40)]
        expected = [network.route(*pair) for pair in pairs]
        with ThreadPoolExecutor(max_workers=4) as executor:
            actual = list(executor.map(lambda pair: network.route(*pair), pairs))
        self.assertEqual(actual, expected)

    def test_world_rebuild_replaces_snapshot(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        city.add_road([(200, 0), (300, 0)])
        old = city.pedestrian_network
        with self.assertRaisesRegex(ValueError, 'No walking route'):
            old.route((20, 17), (280, 17))
        city.add_road([(100, 0), (200, 0)])
        self.assertGreater(city.find_pedestrian_route((20, 17), (280, 17)).length, 0)
        with self.assertRaises(ValueError):
            old.route((20, 17), (280, 17))

    def test_empty_and_zero_length_fail_cleanly(self):
        with self.assertRaises(ValueError):
            PedestrianNetwork([], []).route((0, 0), (1, 1))
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)])
        point = road.pedestrian_lanes[0].points[0]
        with self.assertRaisesRegex(ValueError, 'zero length'):
            city.find_pedestrian_route(point, point)

    def test_native_distances_match_reference_dijkstra_at_junctions(self):
        from math import dist
        from mobility import nearest_lane_position
        from models import polyline_length
        from pedestrian_mobility import _node
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (200, 50)])
        city.add_road([(50, 0), (50, 200)])
        city.add_road([(0, 150), (200, 150)])
        network = city.pedestrian_network
        points = [(10, 67), (180, 33), (67, 180), (33, 10), (180, 167), (10, 133)]
        for a in points:
            for b in points:
                if a == b:
                    continue
                start, access = min((nearest_lane_position(lane, a) for lane in network.lanes), key=lambda x: x[1])
                end, exit_distance = min((nearest_lane_position(lane, b) for lane in network.lanes), key=lambda x: x[1])
                graph = DirectedGraph()
                graph.extend(network.layer.graph)
                for name, distance in [('start', 0), ('end', polyline_length(start.lane.points))]:
                    graph.add_edge('origin', _node(start.lane, name), abs(start.distance-distance), None)
                for name, distance in [('start', 0), ('end', polyline_length(end.lane.points))]:
                    graph.add_edge(_node(end.lane, name), 'destination', abs(end.distance-distance), None)
                if start.lane.id == end.lane.id:
                    graph.add_edge('origin', 'destination', abs(start.distance-end.distance), None)
                expected = graph.find_path('origin', 'destination').cost + access + exit_distance
                with self.subTest(start=a, end=b):
                    route = network.route(a, b)
                    self.assertAlmostEqual(route.length, expected)
                    self.assertAlmostEqual(sum(dist(p, q) for p, q in zip(route.points, route.points[1:])), expected)
