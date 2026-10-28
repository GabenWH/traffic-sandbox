"""Road ownership, lifecycle and routing of pedestrian lanes."""
import copy
import unittest

from city import CityMap, Terrain
from pedestrian_mobility import PedestrianNetwork
from persistence import world_to_dict, world_from_dict, WorldFormatError


class RoadPedestrianTests(unittest.TestCase):
    def test_graph_uses_owned_lane_objects_and_configured_sides(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)], pedestrian_sides=('left',), pedestrian_offset=5)
        self.assertEqual(len(road.pedestrian_lanes), 1)
        self.assertIs(city.pedestrian_network.lanes[0], road.pedestrian_lanes[0])
        self.assertEqual(road.pedestrian_lanes[0].points[0], (0, 17))
        self.assertIn('pedestrians', city.mobility.layers)
        self.assertAlmostEqual(city.find_pedestrian_route((20, 17), (180, 17)).length, 160)
        self.assertAlmostEqual(city.find_pedestrian_route((180, 17), (20, 17)).length, 160)
        self.assertEqual(len(road.lanes), 2)

    def test_rebuild_and_split_preserve_ownership_and_configuration(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)], pedestrian_sides=('right',), pedestrian_offset=4)
        first, second = road.split((150, 0))
        for part in (first, second):
            self.assertEqual(part.pedestrian_sides, ('right',))
            self.assertEqual(part.pedestrian_offset, 4)
            self.assertEqual(part.pedestrian_lanes[0].road_id, part.id)
        road.centerline = [(0, 0), (600, 0)]
        city.rebuild_mobility_network()
        self.assertIs(city.pedestrian_network.lanes[0], road.pedestrian_lanes[0])
        self.assertEqual(road.pedestrian_lanes[0].points[-1], (600, -16))
        road.pedestrian_sides = ()
        city.rebuild_mobility_network()
        self.assertEqual(city.pedestrian_network.lanes, [])

    def test_save_round_trip_and_legacy_defaults(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (300, 0)], pedestrian_sides=('right',), pedestrian_offset=7)
        data = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        loaded = world_from_dict(copy.deepcopy(data)).city_map
        self.assertEqual(loaded.roads[0].pedestrian_sides, ('right',))
        self.assertEqual(loaded.roads[0].pedestrian_offset, 7)
        self.assertIs(loaded.pedestrian_network.lanes[0], loaded.roads[0].pedestrian_lanes[0])
        legacy = copy.deepcopy(data)
        del legacy['world']['roads'][0]['pedestrian_sides']
        del legacy['world']['roads'][0]['pedestrian_offset']
        self.assertEqual(len(world_from_dict(legacy).city_map.roads[0].pedestrian_lanes), 2)
        for invalid in (['left', 'left'], ['middle'], 'left', [True]):
            bad = copy.deepcopy(data)
            bad['world']['roads'][0]['pedestrian_sides'] = invalid
            with self.assertRaises(WorldFormatError):
                world_from_dict(bad)

    def test_no_walkway_road_is_not_added_by_graph_compiler(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)], pedestrian_sides=())
        self.assertEqual(PedestrianNetwork(city.roads, city.intersections).lanes, [])
        self.assertEqual(road.pedestrian_lanes, [])

    def test_road_removal_drops_owned_lanes_but_preserves_other_layers(self):
        from mobility import MobilityLayer
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)])
        transit = MobilityLayer()
        city.mobility.set_layer('transit', transit)
        city.remove_road(road)
        self.assertEqual(city.pedestrian_network.lanes, [])
        self.assertEqual(city.mobility.layers['pedestrians'].graph.nodes, ())
        self.assertIs(city.mobility.layers['transit'], transit)

    def test_explicit_walkway_configuration_overrides_legacy_name_default(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)], name='Road [motorway]',
                             pedestrian_sides=('left',))
        self.assertEqual(len(road.pedestrian_lanes), 1)
        self.assertIs(city.pedestrian_network.lanes[0], road.pedestrian_lanes[0])

    def test_invalid_offset_rejected(self):
        for offset in (-1, float('nan'), float('inf'), True):
            city = CityMap(terrain=Terrain(trees=[]))
            with self.assertRaises(ValueError):
                city.add_road([(0, 0), (300, 0)], pedestrian_offset=offset)


if __name__ == '__main__':
    unittest.main()
