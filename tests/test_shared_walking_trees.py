"""Walking eligibility shares trees without retaining hypothetical geometry."""
from concurrent.futures import ThreadPoolExecutor
from math import dist
import unittest
from unittest.mock import patch

from city import CityMap, Terrain
from native_routing import NativeRouteGraph, NativeRouteTree
from native_walking import NativeWalkingGraph


class SharedWalkingTreeTests(unittest.TestCase):
    def network(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0), (150, 50), (300, 50)])
        return city.pedestrian_network

    def test_many_origins_share_one_destination_tree_and_endpoint_projection(self):
        network = self.network()
        target = (280, 67)
        network.cost((20, 17), target)
        native = network._native
        with patch.object(NativeRouteGraph, 'tree', side_effect=AssertionError('tree rebuilt')), \
             patch.object(native, '_project', wraps=native._project) as project:
            for origin in ((30, 17), (40, 17), (50, 17)):
                self.assertGreater(network.cost(origin, target), 0)
                self.assertGreater(network.route(origin, target).length, 0)
        self.assertEqual(project.call_count, 3, 'Only new origins need projection')

    def test_cost_only_never_reconstructs_a_path_or_route_geometry(self):
        network = self.network()
        with patch.object(NativeRouteTree, 'path', side_effect=AssertionError('unused path built')), \
             patch.object(NativeWalkingGraph, 'route', side_effect=AssertionError('unused geometry built')):
            length = network.cost((20, 7), (280, 77))
        self.assertAlmostEqual(length, network.route((20, 7), (280, 77)).length)

    def test_cost_and_materialized_route_match_old_astar_in_both_directions(self):
        network = self.network()
        network.cost((20, 17), (280, 67))
        native = network._native
        points = [(10, 7), (90, 22), (130, 60), (280, 77), (300, 50)]
        for origin in points:
            for target in points:
                if origin == target:
                    continue
                projections, steps = native.astar_route(origin, target)
                expected = (dist(origin, projections[0]) + dist(projections[1], target)
                            + sum(end-start for _, start, end in steps))
                with self.subTest(origin=origin, target=target):
                    self.assertAlmostEqual(network.cost(origin, target), expected)
                    self.assertAlmostEqual(network.route(origin, target).length, expected)

    def test_cache_limits_and_concurrent_readers_keep_results_valid(self):
        network = self.network()
        network.cost((10, 17), (280, 67))
        native = network._native
        native.tree_limit = 2
        native.projection_limit = 4
        for i in range(12):
            network.cost((10+i, 17), (280-i, 67))
        self.assertLessEqual(len(native._trees), 2)
        self.assertLessEqual(len(native._projections), 4)
        expected = network.route((10, 17), (280, 67))
        with ThreadPoolExecutor(max_workers=4) as pool:
            routes = list(pool.map(lambda _: network.route((10, 17), (280, 67)), range(20)))
        self.assertEqual(routes, [expected]*20)
