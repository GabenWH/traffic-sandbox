import unittest
from city import CityMap, Terrain
from pedestrian_mobility import PedestrianNetwork


class PedestrianMobilityTests(unittest.TestCase):
    def test_pedestrian_lanes_are_separate_and_bidirectional_on_one_way_road(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)], forward_lane_count=1, reverse_lane_count=0)
        network = PedestrianNetwork(city.roads, city.intersections)
        self.assertEqual(len(network.lanes), 2)
        self.assertEqual(len(road.lanes), 1)
        self.assertTrue(all(lane.road_id == road.id for lane in network.lanes))
        forward = network.route((20, 9), (180, 9))
        backward = network.route((180, 9), (20, 9))
        self.assertAlmostEqual(forward.length, 160, delta=.01)
        self.assertAlmostEqual(backward.length, 160, delta=.01)
        self.assertEqual(len(city.mobility.layers), 2)

    def test_walking_routes_connect_existing_junctions_without_building_nodes(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,50),(100,50)])
        city.add_road([(50,0),(50,100)])
        network = PedestrianNetwork(city.roads, city.intersections)
        count_before = len(network.layer.graph.nodes)
        route = network.route((5,67), (67,95))
        self.assertGreater(route.length, 0)
        self.assertTrue(any(link.kind == 'junction' for link in route.links))
        self.assertEqual(count_before, len(network.layer.graph.nodes))

    def test_crossing_wait_point_is_before_entering_junction_link(self):
        from models import point_at_polyline_distance
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,50),(100,50)])
        city.add_road([(50,0),(50,100)])
        route = PedestrianNetwork(city.roads, city.intersections).route((5,67), (67,95))
        junction = next(link for link in route.links
                        if link.kind == 'junction' and __import__('math').dist(*link.points) > 1)
        waiting = point_at_polyline_distance(list(route.points), route.length*route.first_crossing_fraction)
        self.assertAlmostEqual(waiting[0], junction.points[0][0], delta=1e-6)
        self.assertAlmostEqual(waiting[1], junction.points[0][1], delta=1e-6)

    def test_highway_is_not_given_an_assumed_sidewalk(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,0),(300,0)], name='Freeway [motorway]')
        network = PedestrianNetwork(city.roads, city.intersections)
        self.assertEqual(network.lanes, [])


if __name__ == '__main__':
    unittest.main()
