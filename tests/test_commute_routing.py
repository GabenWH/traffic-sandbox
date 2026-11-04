import concurrent.futures
import importlib.util
import threading
import unittest

from city import CityMap,Terrain
from mobility import lane_position_at_distance
from models import polyline_length


def route_city():
    city=CityMap(terrain=Terrain(trees=[]))
    source=city.add_road([(20,100),(220,100)],road_id='source')
    city.add_road([(220,100),(620,100)],road_id='direct')
    city.add_road([(220,100),(220,500),(620,500),(620,100)],road_id='alternative')
    destination=city.add_road([(620,100),(820,100)],road_id='destination')
    lane=lambda r:next(l for l in r.lanes if l.direction=='forward')
    a=lane_position_at_distance(lane(source),20)
    b=lane_position_at_distance(lane(destination),polyline_length(lane(destination).points)-20)
    return city,a,b


class BackgroundRoutingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('commute_routing'),'Background routing is missing')

    def test_same_destination_shares_a_tree_without_copying_python_graph(self):
        from commute_routing import BackgroundRoutes
        city,a,b=route_city();service=BackgroundRoutes(city)
        def forbidden(*args,**kwargs):raise AssertionError('A route must not copy the live graph')
        city.mobility.combined_graph=forbidden
        route=service.get_route('one','home','job',[a],[b],blocking=True)
        other=service.get_route('two','home','job',[a],[b],blocking=True)
        self.assertIsNotNone(route);self.assertIsNotNone(other)
        self.assertIn('direct',[getattr(getattr(e.value,'lane',e.value),'road_id',None) for e in route.edges])
        self.assertEqual(service.report()['routing_trees_built'],1)
        self.assertEqual(service.report()['routing_queries_completed'],2)

    def test_blocked_worker_does_not_block_request_and_queue_is_bounded(self):
        from commute_routing import BackgroundRoutes,PENDING
        city,a,b=route_city();gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            held=pool.submit(gate.wait)
            try:
                service=BackgroundRoutes(city,executor=pool,max_pending=1)
                service.begin_update(0)
                self.assertIs(service.get_route('one','a','b',[a],[b]),PENDING)
                self.assertIs(service.get_route('two','a','b',[a],[b]),PENDING)
                self.assertEqual(service.report()['routing_pending'],1)
            finally:gate.set();held.result(timeout=2)

    def test_submission_budget_prevents_a_departure_burst_from_flooding_worker(self):
        from commute_routing import BackgroundRoutes,PENDING
        city,a,b=route_city();gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait)
            try:
                service=BackgroundRoutes(city,executor=pool,submissions_per_update=2)
                service.begin_update(0)
                for i in range(12):self.assertIs(service.get_route(str(i),'a','b',[a],[b]),PENDING)
                self.assertEqual(service.report()['routing_pending'],2)
            finally:gate.set()

    def test_direct_partial_lane_has_correct_geometry_and_direction(self):
        from commute_routing import BackgroundRoutes
        city,a,_=route_city();b=lane_position_at_distance(a.lane,a.distance+30)
        service=BackgroundRoutes(city)
        path=service.get_route('car','a','b',[a],[b],blocking=True)
        from mobility import vehicle_route_points
        self.assertEqual(vehicle_route_points(path),(a.point,b.point))
        self.assertAlmostEqual(path.cost,30/(25*22/15))

    def test_road_edit_discards_pending_snapshot(self):
        from commute_routing import BackgroundRoutes,PENDING
        city,a,b=route_city();gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait)
            service=BackgroundRoutes(city,executor=pool)
            try:
                self.assertIs(service.get_route('one','a','b',[a],[b]),PENDING)
                city.rebuild_mobility_network();service.sync()
                self.assertEqual(service.report()['routing_pending'],0)
                self.assertGreater(service.report()['routing_stale_results'],0)
            finally:gate.set()

    def test_congestion_changes_the_following_days_route(self):
        from commute_routing import BackgroundRoutes
        city,a,b=route_city();service=BackgroundRoutes(city)
        roads=lambda p:{getattr(getattr(e.value,'lane',e.value),'road_id',None) for e in p.edges}
        first=service.get_route('car','a','b',[a],[b],day=0,blocking=True)
        self.assertIn('direct',roads(first))
        direct=next(l for r in city.roads if r.id=='direct' for l in r.lanes if l.direction=='forward')
        service.learning.record('lane:'+direct.id,1000,day=0)
        today=service.get_route('car','a','b',[a],[b],day=0,blocking=True)
        tomorrow=service.get_route('car','a','b',[a],[b],day=1,blocking=True)
        self.assertIn('direct',roads(today))
        self.assertNotIn('direct',roads(tomorrow));self.assertIn('alternative',roads(tomorrow))

    def test_completed_abandoned_requests_do_not_fill_the_pending_queue(self):
        from commute_routing import BackgroundRoutes,PENDING
        city,a,b=route_city();gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait);service=BackgroundRoutes(city,max_pending=1,executor=pool)
            try:
                self.assertIs(service.get_route('one','a','b',[a],[b]),PENDING)
                gate.set()
                # Waiting is confined to the test: frames only poll done().
                next(iter(service._requests.values())).result(timeout=2)
                service.begin_update(0)
                route=service.get_route('two','a','b',[a],[b],blocking=True)
                self.assertIsNot(route,PENDING);self.assertIsNotNone(route)
            finally:gate.set()

    def test_fleet_waits_at_home_until_plan_ready_and_records_completed_links(self):
        from commute_routing import BackgroundRoutes
        from persistent_fleet import PersistentFleet,FleetVehicle
        from transit import TransitSimulation
        from types import SimpleNamespace
        city,a,b=route_city();transit=TransitSimulation(city)
        sites={key:dict(road_position=position,parking_capacity=4,walk_point=position.point,
                       building=SimpleNamespace(inventory=SimpleNamespace(amounts={})))
               for key,position in [('home',a),('job',b)]}
        fleet=PersistentFleet(transit,sites);fleet.add(FleetVehicle('car','car','home'))
        gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait)
            fleet.routing=BackgroundRoutes(city,executor=pool);fleet.background=True
            try:
                self.assertFalse(fleet.dispatch('car','job'))
                self.assertEqual(fleet.vehicles['car'].site,'home')
                self.assertEqual(fleet.vehicles['car'].phase,'parked')
                self.assertFalse(transit.traffic.cars)
            finally:gate.set()
            # Explicit dispatch outside an update may wait for its requested plan.
            fleet.background=False
            self.assertTrue(fleet.dispatch('car','job'))
        for _ in range(2000):
            transit.update(.05);fleet.observe()
            if fleet.vehicles['car'].phase=='parked':break
        self.assertEqual(fleet.vehicles['car'].site,'job')
        samples=fleet.routing.learning.samples[0]
        self.assertTrue(any(key.startswith('lane:') and row[0]>0 for key,row in samples.items()))

    def test_road_ports_record_their_own_time_not_the_adjoining_lanes_time(self):
        from commute_routing import BackgroundRoutes,link_key
        from mobility import vehicle_link_points
        from persistent_fleet import PersistentFleet,FleetVehicle
        from types import SimpleNamespace
        city=CityMap(terrain=Terrain(trees=[]))
        first=city.add_road([(20,100),(1020,100)],road_id='first',forward_lane_count=2,reverse_lane_count=2)
        last=city.add_road([(1020,100),(2020,100)],road_id='last',forward_lane_count=2,reverse_lane_count=2)
        a=lane_position_at_distance(first.lanes[0],20)
        b=lane_position_at_distance(last.lanes[0],800)
        service=BackgroundRoutes(city);route=service.get_route('car','a','b',[a],[b],blocking=True)
        transit=SimpleNamespace(time=0.);fleet=PersistentFleet(transit,{})
        fleet.routing=service;v=FleetVehicle('car','car','a');v._actor=SimpleNamespace(distance=0.)
        fleet._track_trip(v,route)
        # Known 10 ft/s progress lets us independently check each recorded port.
        ports=0
        for link in route.edges:
            length=polyline_length(vehicle_link_points(link))
            v._actor.distance+=length;transit.time=v._actor.distance/10
            fleet._observe_trip(v)
            if link.kind=='road_port' and length>1e-8:
                ports+=1
                total,count=service.learning.samples[0][link_key(link)]
                self.assertAlmostEqual(total/count,length/10,places=7)
        self.assertGreater(ports,0)
