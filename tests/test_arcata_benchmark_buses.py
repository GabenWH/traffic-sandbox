import unittest
from types import SimpleNamespace
from city import CityMap, Terrain
from mobility import lane_position_at_distance
from transit import TransitSimulation
from tools.arcata_buses import add_benchmark_buses

class BenchmarkBusTests(unittest.TestCase):
    def test_connected_bus_service_uses_existing_lanes(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0,0),(6000,0)])
        island = city.add_road([(0,3000),(100,3000)])
        lane = next(l for l in road.lanes if l.direction=='forward')
        transit = TransitSimulation(city)
        self.addCleanup(transit.traffic._discard_native)
        sites = {}
        for number in range(10):
            position = lane_position_at_distance(lane,100+number*600)
            sites[str(number)] = dict(road_position=position,walk_point=(position.point[0],15))
        runtime = SimpleNamespace(city=city,transit=transit,sites=sites,time=0,initial_fuel=0,_access_times={})
        # An isolated access must not become the hub just because it is central.
        island_lane = next(l for l in island.lanes if l.direction=='forward')
        sites['isolated'] = dict(road_position=lane_position_at_distance(island_lane,50),walk_point=(50,3015))
        result = add_benchmark_buses(runtime)
        self.assertNotIn('isolated',result['stop_sites'])
        self.assertEqual((result['lines'],result['buses'],result['stops']),(3,12,10))
        self.assertEqual(len(transit.lines),3)
        self.assertEqual(len(transit.buses),12)
        self.assertEqual(runtime.initial_fuel,12000)
        self.assertTrue(all(line.headway_seconds==300 for line in transit.lines.values()))
        self.assertTrue(all(bus.capacity==60 for bus in transit.buses.values()))
