import unittest
from city import CityMap, Terrain
from mobility import lane_position_at_distance
from traffic_testbed import RoadVehicleSimulation


class SharedSpeedLimitTests(unittest.TestCase):
    def test_all_vehicle_types_obey_road_limit(self):
        city=CityMap(terrain=Terrain(trees=[]))
        r=city.add_road([(0,0),(3000,0)],speed_limit_mph=10)
        lane=r.lanes[0]
        route=city.find_vehicle_route_between(lane_position_at_distance(lane,100),lane_position_at_distance(lane,2500))
        for kind in ('car','truck','bus'):
            sim=RoadVehicleSimulation(update_mode='cpp',speed_mph=40)
            sim.sync_network(city)
            car=sim.admit_route(route,vehicle_id=kind,source_id='a',destination_id='b',source_type=kind)
            for _ in range(100):
                sim.update(city,.05)
                self.assertLessEqual(car.speed,10*22/15+1e-6)
            self.assertGreater(car.distance,0)

    def test_brakes_before_entering_a_lower_limit_road(self):
        city=CityMap(terrain=Terrain(trees=[]))
        fast=city.add_road([(0,0),(3000,0)],speed_limit_mph=40)
        slow=city.add_road([(3000,0),(6000,0)],speed_limit_mph=10)
        a=next(l for l in fast.lanes if l.direction=='forward')
        b=next(l for l in slow.lanes if l.direction=='forward')
        route=city.find_vehicle_route_between(lane_position_at_distance(a,100),lane_position_at_distance(b,2000))
        sim=RoadVehicleSimulation(update_mode='cpp',speed_mph=40)
        sim.sync_network(city)
        car=sim.admit_route(route,vehicle_id='bus',source_id='fast',destination_id='slow',source_type='bus')
        entered=False;slowed=False
        for _ in range(1600):
            sim.update(city,.05)
            if 2700<car.position[0]<3000 and car.speed<35*22/15:slowed=True
            if car.position[0]>3050:
                entered=True
                self.assertLessEqual(car.speed,10*22/15+.1)
        self.assertTrue(entered)
        self.assertTrue(slowed)

    def test_osm_numeric_limits_and_saved_road_configuration(self):
        from tools.run_arcata_scale_test import posted_speed_mph
        from persistence import world_to_dict,world_from_dict
        self.assertEqual(posted_speed_mph({'maxspeed':'5 mph'}),5)
        self.assertAlmostEqual(posted_speed_mph({'maxspeed':'50'}),50/1.609344)
        self.assertIsNone(posted_speed_mph({'maxspeed':'signs'}))
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,0),(3000,0)],speed_limit_mph=20)
        saved=world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)
        loaded=world_from_dict(saved).city_map
        self.assertEqual(loaded.roads[0].speed_limit_mph,20)
        self.assertTrue(all(l.speed_limit_mph==20 for l in loaded.roads[0].lanes))
