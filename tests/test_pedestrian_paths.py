"""Standalone pedestrian paths share routing topology without vehicle access."""
import copy
import unittest

from city import CityMap, Terrain
from persistence import world_from_dict, world_to_dict


class PedestrianPathTests(unittest.TestCase):
    def test_path_has_one_center_walkway_and_no_vehicle_ports(self):
        city = CityMap(terrain=Terrain(trees=[]))
        path = city.add_pedestrian_path([(0, 0), (300, 0)], name='Campus walk', width=6)
        self.assertEqual(path.lanes, [])
        self.assertEqual(path.route_inputs, ())
        self.assertEqual(path.route_outputs, ())
        self.assertEqual(path.width, 6)
        self.assertEqual(path.pedestrian_sides, ('center',))
        self.assertEqual(path.pedestrian_lanes[0].points, ((0, 0), (300, 0)))
        self.assertEqual(city.mobility.layers['vehicles'].graph.nodes, ())
        self.assertAlmostEqual(city.find_pedestrian_route((20, 0), (180, 0)).length, 160)
        self.assertAlmostEqual(city.find_pedestrian_route((180, 0), (20, 0)).length, 160)

    def test_path_connects_two_streets_only_for_walkers(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (600, 0)], endpoint_overrun_tolerance=0)
        city.add_road([(0, 500), (600, 500)], endpoint_overrun_tolerance=0)
        city.add_pedestrian_path([(300, 0), (300, 500)], endpoint_overrun_tolerance=0)
        route = city.find_pedestrian_route((100, 15), (500, 485))
        self.assertGreater(route.length, 500)
        self.assertTrue(any(link.kind == 'junction' for link in route.links))
        bottom = next(r for r in city.roads if r.centerline[0] == (0, 0))
        top = next(r for r in city.roads if r.centerline[0] == (0, 500))
        self.assertIsNone(city.find_vehicle_route(bottom.lanes[0], top.lanes[0]))

    def test_paths_connect_split_save_and_remove(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_pedestrian_path([(0, 0), (600, 0)], endpoint_overrun_tolerance=0)
        city.add_pedestrian_path([(300, -300), (300, 300)], endpoint_overrun_tolerance=0)
        self.assertEqual(len(city.roads), 4)
        self.assertGreater(city.find_pedestrian_route((10, 0), (300, 290)).length, 500)
        data = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        loaded = world_from_dict(copy.deepcopy(data)).city_map
        self.assertTrue(all(r.pedestrian_sides == ('center',) and not r.lanes for r in loaded.roads))
        self.assertAlmostEqual(loaded.find_pedestrian_route((10, 0), (300, 290)).length,
                               city.find_pedestrian_route((10, 0), (300, 290)).length)
        for road in list(loaded.roads):
            loaded.remove_road(road)
        self.assertEqual(loaded.pedestrian_network.lanes, [])

    def test_elevated_path_does_not_connect_at_ground_crossing(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (600, 0)], endpoint_overrun_tolerance=0)
        city.add_pedestrian_path([(300, -300), (300, 300)], elevations=[30, 30],
                                 endpoint_overrun_tolerance=0)
        self.assertEqual(len(city.roads), 2)
        with self.assertRaisesRegex(ValueError, 'No walking route'):
            city.find_pedestrian_route((100, 15), (300, 290))

    def test_native_movement_uses_pedestrian_only_path(self):
        from native_traffic import NativeTrafficEngine
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_pedestrian_path([(0, 0), (300, 0)])
        route = city.find_pedestrian_route((0, 0), (44, 0))
        with NativeTrafficEngine() as engine:
            lane = engine.register_pedestrian_lane(route.points, route.first_crossing_fraction)
            engine.spawn_pedestrian(11, lane, 4.4)
            engine.step(1)
            self.assertAlmostEqual(engine.pedestrian_states()[0].x, 4.4)
            engine.step(10)
            self.assertEqual(engine.pedestrian_states(), [])
            self.assertEqual([p.id for p in engine.completed_pedestrians()], [11])

    def test_center_path_cannot_be_configured_as_a_vehicle_lane(self):
        city = CityMap(terrain=Terrain(trees=[]))
        with self.assertRaises(ValueError):
            city.add_road([(0, 0), (300, 0)], pedestrian_sides=('center',))
        with self.assertRaises(ValueError):
            city.add_road([(0, 0), (300, 0)], forward_lane_count=0,
                          reverse_lane_count=0, pedestrian_sides=())


if __name__ == '__main__':
    unittest.main()
