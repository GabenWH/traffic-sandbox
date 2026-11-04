import concurrent.futures
import importlib.util
import json
import threading
import unittest

from city import Building,CityMap,Parcel,Terrain,ZoneType
from models import BuildablePhase
from persistence import world_to_dict,world_from_dict


def city_runtime(policy=None):
    from city_simulation import CitySimulation
    city=CityMap(terrain=Terrain(trees=[]));city.add_road([(20,30),(4500,30)])
    for ident,x,residents,jobs in [('a',200,4,0),('b',600,4,0),('job',3200,0,20)]:
        parcel=Parcel(x,90,40,40,ZoneType.COMMERCIAL if jobs else ZoneType.RESIDENTIAL)
        city.parcels.append(parcel);city.buildings.append(Building(ident,parcel,id=ident,residents=residents,jobs=jobs,phase=BuildablePhase.OPERATIONAL))
    runtime=CitySimulation(city,commute_policy=policy)
    runtime.work_start=0;runtime.work_end=1000
    return runtime


def worker(runtime,home='a',car=True):
    h=runtime.invite_household(home,1,car=car)
    runtime.assign_workplace(h.members[0],'job')
    return runtime.residents[h.members[0]]


def prime(runtime,person):
    from mobility import nearest_lane_position
    def accesses(site):
        p=runtime.sites[site]['road_position']
        road=next(r for r in runtime.city.roads if r.id==p.lane.road_id)
        return [nearest_lane_position(l,p.point)[0] for l in road.lanes]
    runtime.fleet.routing.get_route(person.car_id,person.home,person.workplace,
        accesses(person.home),accesses(person.workplace),blocking=True)


def saved_world(runtime):
    return json.loads(json.dumps(world_to_dict(runtime.city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)))


class BackgroundCityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('commute_schedule'),'City background scheduling is missing')

    def test_blocked_routing_worker_does_not_stop_an_existing_vehicle(self):
        from commute_schedule import CommutePolicy
        from commute_routing import BackgroundRoutes
        from persistent_fleet import FleetVehicle
        runtime=city_runtime(CommutePolicy(departure_window=0));p=worker(runtime)
        runtime.fleet.add(FleetVehicle('already-moving','van','a'))
        self.assertTrue(runtime.fleet.dispatch('already-moving','job'))
        actor=runtime.fleet.vehicles['already-moving']._actor;before=actor.distance
        gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait)
            runtime.fleet.routing=BackgroundRoutes(runtime.city,executor=pool)
            try:
                runtime.update(1)
                self.assertEqual(runtime.time,1)
                self.assertGreater(actor.distance,before)
                self.assertEqual(p.state,'home')
                self.assertEqual(runtime.fleet.vehicles[p.car_id].phase,'parked')
                self.assertEqual(runtime.report()['commute_waiting'],1)
            finally:gate.set()

    def test_departure_cap_applies_to_walking_workers(self):
        from commute_schedule import CommutePolicy
        runtime=city_runtime(CommutePolicy(departure_window=0,starts_per_second=2,burst=1))
        for _ in range(4):worker(runtime,'a',False)
        for _ in range(4):worker(runtime,'b',False)
        runtime.update(2)
        self.assertLessEqual(runtime.report()['commute_departures'],5)
        self.assertGreaterEqual(runtime.report()['commute_departures'],3)
        self.assertTrue(any(p.state=='home' for p in runtime.residents.values()))

    def test_completed_car_plan_gets_a_fair_slot_among_walking_departures(self):
        from commute_schedule import CommutePolicy
        from commute_routing import BackgroundRoutes
        runtime=city_runtime(CommutePolicy(departure_window=0,starts_per_second=1,burst=1))
        driver=worker(runtime,'a')
        walkers=[worker(runtime,'a',False) for _ in range(3)]+[worker(runtime,'b',False) for _ in range(4)]
        gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait);runtime.fleet.routing=BackgroundRoutes(runtime.city,executor=pool)
            try:
                runtime.update(.05)
                gate.set()
                for future in list(runtime.fleet.routing._requests.values()):future.result(timeout=2)
                runtime.update(1.1)
                self.assertEqual(driver.state,'commuting')
                self.assertEqual(sum(p.state=='commuting' for p in walkers),1)
            finally:gate.set()

    def test_busy_entrance_does_not_block_another_household(self):
        from commute_schedule import CommutePolicy
        runtime=city_runtime(CommutePolicy(departure_window=0,starts_per_second=100,burst=10))
        people=[worker(runtime,'a'),worker(runtime,'a'),worker(runtime,'b')]
        for p in people:prime(runtime,p)
        runtime.update(.2)
        departed=[runtime.fleet.vehicles[p.car_id].phase=='driving' for p in people]
        self.assertEqual(departed,[True,False,True])

    def test_active_vehicle_limit_keeps_ready_commuter_parked(self):
        from commute_schedule import CommutePolicy
        runtime=city_runtime(CommutePolicy(departure_window=0,max_active_vehicles=1))
        people=[worker(runtime,'a'),worker(runtime,'b')]
        for p in people:prime(runtime,p)
        runtime.update(.2)
        self.assertEqual(len(runtime.transit.traffic.cars),1)
        self.assertEqual(sum(p.state=='home' for p in people),1)

    def test_pending_route_and_learning_survive_world_save(self):
        from commute_schedule import CommutePolicy
        from commute_routing import BackgroundRoutes
        from city_simulation import CitySimulation
        runtime=city_runtime(CommutePolicy(departure_window=0));p=worker(runtime)
        gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait);runtime.fleet.routing=BackgroundRoutes(runtime.city,executor=pool)
            try:
                runtime.update(.05)
                runtime.fleet.routing.learning.record('lane:example',50,day=0)
                data=saved_world(runtime)
                self.assertTrue(data['gameplay']['commutes']['pending'])
                restored=CitySimulation(world_from_dict(data).city_map)
                self.assertEqual(restored.report()['commute_waiting'],1)
                self.assertEqual(restored.fleet.routing.learning.samples[0]['lane:example'],[50.,1])
                self.assertEqual(restored.fleet.vehicles[p.car_id].site,p.home)
            finally:gate.set()
        restored.update(300)
        self.assertEqual(restored.residents[p.id].state,'work')
        self.assertEqual(restored.fleet.vehicles[p.car_id].site,'job')

    def test_workplace_closure_cancels_a_pending_departure(self):
        from commute_schedule import CommutePolicy
        runtime=city_runtime(CommutePolicy(departure_window=0));p=worker(runtime)
        runtime._pending_departures[p.id]=(False,0.)
        runtime.sites['job']['building'].jobs=0;runtime.sync_buildings();runtime.update(.1)
        self.assertEqual(p.state,'home')
        self.assertEqual(runtime.report()['commute_waiting'],0)

    def test_return_shift_uses_the_same_offset_as_the_departure(self):
        from commute_schedule import CommutePolicy
        runtime=city_runtime(CommutePolicy(departure_window=7200));p=worker(runtime,car=False)
        offset=runtime.commute_policy.offset(p.id,p.workplace)
        runtime._events.clear();runtime._scheduled.clear();runtime._schedule_shift(p)
        leave=next(e[0] for e in runtime._events if e[2]=='leave')
        returned=next(e[0] for e in runtime._events if e[2]=='return_person')
        self.assertEqual(leave,offset)
        self.assertEqual(returned,runtime.work_end+offset)

    def test_event_splits_do_not_reset_the_fifty_ms_work_budget(self):
        from commute_schedule import CommutePolicy
        from commute_routing import BackgroundRoutes
        policy=CommutePolicy(departure_window=0,checks_per_update=1,route_submissions=1)
        runtime=city_runtime(policy)
        for home in ('a','a','b','b'):worker(runtime,home)
        for i in range(1,10):runtime._once('split:'+str(i),i*.005,'builders')
        gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait)
            runtime.fleet.routing=BackgroundRoutes(runtime.city,executor=pool,submissions_per_update=1)
            try:
                runtime.update(.05)
                self.assertEqual(runtime.report()['routing_queries_submitted'],1)
                runtime.update(.15)
                self.assertEqual(runtime.report()['routing_queries_submitted'],4)
            finally:gate.set()

    def test_road_edit_while_worker_is_blocked_preserves_pending_commuter(self):
        from commute_schedule import CommutePolicy
        from commute_routing import BackgroundRoutes
        runtime=city_runtime(CommutePolicy(departure_window=0));p=worker(runtime)
        gate=threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(gate.wait);runtime.fleet.routing=BackgroundRoutes(runtime.city,executor=pool)
            try:
                runtime.update(.05)
                runtime.city.rebuild_mobility_network();runtime.sync_network();runtime.update(.05)
                self.assertEqual(p.state,'home')
                self.assertEqual(runtime.fleet.vehicles[p.car_id].phase,'parked')
                self.assertGreater(runtime.report()['routing_stale_results'],0)
            finally:gate.set()
        # The injected executor has ended; normal gameplay resumes its own worker.
        runtime.fleet.routing.executor=None
        runtime.update(300)
        self.assertEqual(p.state,'work')
        self.assertEqual(runtime.fleet.vehicles[p.car_id].site,'job')

    def test_large_update_crossing_midnight_uses_prior_day_observations(self):
        from commute_schedule import CommutePolicy
        runtime=city_runtime(CommutePolicy(departure_window=0));p=worker(runtime)
        prime(runtime,p);runtime.update(86401)
        model=runtime.fleet.routing.learning
        self.assertEqual(model.model_day,1)
        self.assertTrue(model.estimates)
        self.assertTrue(all(value>=0 for value in model.estimates.values()))
        self.assertEqual(len(runtime.residents),1)
        self.assertEqual(runtime.fleet.vehicles[p.car_id].id,p.car_id)
