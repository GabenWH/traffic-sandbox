"""A modeled Harbor Beach, not the town map or a motion simulation."""
import math
import unittest

from city import CityMap, Terrain
from cycle_routing import CycleAccess, cycle_endpoint


class HarborBeachCycleTests(unittest.TestCase):
    def setUp(self):
        self.city = CityMap(terrain=Terrain(trees=[]))
        def path(name, points, width=8):
            road = self.city.add_pedestrian_path(points, name=name, road_id=name, width=width,
                                                 endpoint_overrun_tolerance=0)
            lane = road.pedestrian_lanes[0]
            return (cycle_endpoint(lane, 'start'), cycle_endpoint(lane, 'end'))
        self.home = path('Homes', [(-120, 0), (0, 0)])
        self.beach = path('Beach promenade', [(0, 0), (400, 0)])
        self.spine = path('Cycle spine', [(0, 0), (0, 100), (400, 100), (400, 0)], width=3)
        self.freight = path('Cargo bypass', [(0, 0), (0, -150), (400, -150), (400, 0)])
        self.shop = path('Shops and tram stop', [(400, 0), (480, 0)])
        self.dock = path('Lantern Quay loading edge', [(480, 0), (580, -100)])
        self.core = path('Market core', [(480, 0), (580, 100)])
        self.permissions = {}
        wide = CycleAccess(bicycle=True, cargo=True, clear_width_ft=8)
        def approve(a, b, permission=wide):
            self.permissions[a, b] = permission
        for a, b in (self.home, self.freight, self.shop):
            approve(a, b)
        approve(*self.spine, CycleAccess(bicycle=True, cargo=True, clear_width_ft=3))
        for branch in (self.spine, self.freight):
            approve(self.home[1], branch[0])
            approve(branch[1], self.shop[0])
        delivery = CycleAccess(cargo=True, clear_width_ft=6)
        approve(self.shop[1], self.dock[0], delivery)
        approve(*self.dock, delivery)

    def router(self, clearance=4):
        return self.city.pedestrian_network.cycle_router(self.permissions,
                                                         cargo_clearance_ft=clearance)

    def test_ordinary_bike_detours_around_shorter_beach_and_stops_before_market(self):
        router = self.router()
        route = router.route(self.home[0], self.shop[1])
        self.assertEqual(route.cost, 800)
        self.assertIn(self.spine[0], route.nodes)
        self.assertNotIn(self.beach[0], route.nodes)
        self.assertIn((400, 100), next(link.points for link in route.edges
                                      if (0, 100) in link.points))
        self.assertIsNone(router.route(self.home[0], self.core[1]))
        self.assertIsNone(router.route(self.home[0], self.dock[1]))

    def test_cargo_clearance_and_delivery_permission_apply_to_segments_and_connectors(self):
        router = self.router()
        route = router.route(self.home[0], self.dock[1], cargo=True)
        self.assertIn(self.freight[0], route.nodes)
        self.assertNotIn(self.spine[0], route.nodes)
        self.assertAlmostEqual(route.cost, 900 + math.hypot(100, 100))
        self.assertIsNone(router.route(self.home[0], self.core[1], cargo=True))
        # Exact fit is legal; losing clearance or cargo designation blocks access.
        self.assertIn(self.spine[0], self.router(3).route(self.home[0], self.shop[1], cargo=True).nodes)
        for restricted in (CycleAccess(bicycle=True, cargo=True), CycleAccess(bicycle=True, clear_width_ft=8)):
            with self.subTest(restricted=restricted):
                self.permissions[self.freight[1], self.shop[0]] = restricted
                self.assertIsNone(self.router().route(self.home[0], self.shop[1], cargo=True))

    def test_permission_cannot_make_a_modeled_three_foot_path_wider(self):
        self.permissions[self.spine] = CycleAccess(bicycle=True, cargo=True, clear_width_ft=8)
        self.assertIn(self.freight[0], self.router().route(self.home[0], self.shop[1], cargo=True).nodes)

    def test_approvals_are_directed_and_do_not_change_walker_or_motor_routes(self):
        motor = self.city.add_road([(-120, 500), (480, 500)], forward_lane_count=1,
                                   reverse_lane_count=0, endpoint_overrun_tolerance=0)
        vehicle_graph = self.city.mobility.layers['vehicles'].graph
        lane = motor.lanes[0]
        before = self.city.find_vehicle_route(lane, lane)
        self.assertIsNotNone(before)
        self.assertEqual(len(motor.lanes), 1)
        def walk():
            return self.city.find_pedestrian_route((480, 0), (-120, 0))
        previous = walk()
        self.assertEqual(previous.length, 600)
        router = self.router()
        self.assertIsNone(router.route(self.shop[1], self.home[0]))
        self.assertIsNone(router.route(self.shop[1], self.home[0], cargo=True))
        self.assertEqual(walk(), previous)
        self.assertIs(self.city.mobility.layers['vehicles'].graph, vehicle_graph)
        self.assertEqual(before, self.city.find_vehicle_route(lane, lane))

    def test_unapproved_junction_is_not_inferred_even_where_segments_touch(self):
        del self.permissions[self.home[1], self.spine[0]]
        del self.permissions[self.home[1], self.freight[0]]
        self.assertIsNone(self.router().route(self.home[0], self.shop[1]))

    def test_empty_overlay_is_closed_and_existing_snapshot_does_not_change(self):
        previous = self.router()
        self.permissions.clear()
        closed = self.router()
        for mode in (False, True):
            self.assertIsNone(closed.route(self.home[0], self.shop[1], cargo=mode))
            self.assertIsNotNone(previous.route(self.home[0], self.shop[1], cargo=mode))

    def test_reject_stale_or_invented_edge_and_invalid_clearances(self):
        for clearance in (0, -1, math.inf, math.nan, True):
            with self.subTest(clearance=clearance), self.assertRaises(ValueError):
                self.router(clearance)
        self.permissions[self.home[0], self.dock[1]] = CycleAccess(bicycle=True)
        with self.assertRaisesRegex(ValueError, 'pedestrian edge'):
            self.router()
