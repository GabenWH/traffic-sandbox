"""Gameplay routes can be saved across derived multilane topology."""
import unittest

from city import CityMap, Terrain
from gameplay_persistence import _links, _route_dump, _route_load
from mobility import lane_position_at_distance
from models import IntersectionKind
from persistence import world_from_dict, world_to_dict


class MultilaneGameplayPersistenceTests(unittest.TestCase):
    def city(self, roundabout=False):
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,100),(2000,100)],forward_lane_count=2,reverse_lane_count=2)
        city.add_road([(1000,-500),(1000,700)],forward_lane_count=2,reverse_lane_count=2)
        if roundabout:
            city.standard_intersections[0].kind=IntersectionKind.ROUNDABOUT
            city.rebuild_mobility_network()
        return city

    def round_trip(self, city, route):
        self.assertIsNotNone(route)
        encoded=_route_dump(route)
        world=world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)
        restored=world_from_dict(world).city_map
        decoded=_route_load(encoded,_links(restored))
        self.assertEqual(_route_dump(decoded),encoded)
        return decoded

    def test_lane_specific_ports_and_movements_restore_from_saved_world(self):
        city=self.city()
        road=next(r for r in city.roads if r.centerline[0]==(0,100))
        lane=next(l for l in road.lanes if l.direction=='forward' and l.lane_index==0)
        east=next(j for j in city.cul_de_sacs if j.position==(2000,100))
        # Remove endpoint wrappers here to focus on derived lane ports/movements.
        destination_road=next(r for r in city.roads if r.centerline[-1]==(2000,100))
        destination_lane=next(l for l in destination_road.lanes if l.direction=='forward' and l.lane_index==0)
        route=city.find_vehicle_route_between(lane_position_at_distance(lane,200),lane_position_at_distance(destination_lane,200))
        self.assertTrue(any(e.kind=='road_port' and ':lane:' in e.value.port.id for e in route.edges))
        self.assertTrue(any(e.kind=='lane_connection' and ':lane:' in e.value.id for e in route.edges))
        self.round_trip(city,route)

    def test_junction_endpoints_and_roundabout_lanes_restore(self):
        city=self.city(roundabout=True)
        west=next(j for j in city.cul_de_sacs if j.position==(0,100))
        east=next(j for j in city.cul_de_sacs if j.position==(2000,100))
        route=city.find_vehicle_route_between(west,east)
        self.assertTrue(any(e.kind=='route_endpoint' for e in route.edges))
        self.assertTrue(any(e.kind=='lane' and str(getattr(e.value,'road_id','')).startswith('roundabout:') for e in route.edges))
        self.round_trip(city,route)


    def test_active_lane_change_survives_gameplay_save_and_reload(self):
        from gameplay_persistence import dump_transport, restore_transport
        from traffic_testbed import RoadVehicleSimulation
        from transit import TransitSimulation
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,100),(5000,100)],forward_lane_count=2,reverse_lane_count=2)
        east=max(city.cul_de_sacs,key=lambda j:j.position[0])
        lane=next(l for l in city.roads[0].lanes if l.direction=='forward' and l.lane_index==1)
        sim=RoadVehicleSimulation(spawn_interval=1000,speed_mph=60);sim._native_backend(city)
        self.addCleanup(sim._discard_native)
        transit=TransitSimulation(city,sim)
        for name,distance,speed in (('slow',700,20),('fast',550,60)):
            route=city.find_vehicle_route_between(lane_position_at_distance(lane,distance),east)
            car=sim.admit_route(route,vehicle_id=name,source_id='source',destination_id=east.id,speed_cap_mph=speed)
            self.assertIsNotNone(car)
        for _ in range(50):
            sim.update(city,.05);transit.time=sim.elapsed_time
            if getattr(car,'_lane_change_occupancy',None) and abs(car.position[1]-lane.points[0][1])>3:break
        self.assertIsNotNone(getattr(car,'_lane_change_occupancy',None))
        before,before_heading=car.position,car.heading
        data=dump_transport(transit,managed={'slow','fast'})
        world=world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)
        loaded=world_from_dict(world).city_map
        replacement=RoadVehicleSimulation(spawn_interval=1000,speed_mph=60)
        self.addCleanup(replacement._discard_native)
        restored=TransitSimulation(loaded,replacement)
        actors=restore_transport(restored,data)
        after=actors['fast']
        for actual,expected in zip(after.position,before):self.assertAlmostEqual(actual,expected,places=7)
        for actual,expected in zip(after.heading,before_heading):self.assertAlmostEqual(actual,expected,places=7)
        replacement.update(loaded,.05)
        self.assertGreaterEqual(after.position[0],before[0])
        self.assertLess(abs(after.position[1]-before[1]),1)
        self.assertIsNotNone(getattr(after,'_lane_change_occupancy',None))
        after.place(1500)
        placed=after.position
        replacement.update(loaded,.05)
        self.assertGreaterEqual(after.position[0],placed[0])
        self.assertLess(after.position[0]-placed[0],5)


if __name__=='__main__':unittest.main()
