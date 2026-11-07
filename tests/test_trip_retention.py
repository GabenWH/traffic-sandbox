import gc
import random
import unittest
from event_queue import EventQueue
from retention import BoundedCache,EventHistory
from test_background_city import city_runtime,worker,saved_world
from commute_schedule import CommutePolicy

class TripRetentionTests(unittest.TestCase):
    def runtime(self):
        r=city_runtime(CommutePolicy(departure_window=0));self.addCleanup(r.close);return r

    def test_cancellation_preserves_heap_order_and_releases_payload(self):
        rng=random.Random(42);q=EventQueue()
        for i in range(500):q.push((rng.randrange(100),i,'test',[str(i),i]))
        removed=set(rng.sample(range(500),350))
        for i in removed:q.cancel(str(i))
        expected=sorted(list(q))
        actual=[q.pop_next() for _ in range(len(q))]
        self.assertEqual(expected,actual);self.assertFalse(q.positions)

    def test_retries_and_resolution_do_not_leave_deadlines(self):
        r=self.runtime();p=worker(r);r.fleet.last_dispatch_status='inaccessible'
        for _ in range(100):r.parking_trips.defer(p.id,'commute')
        deadlines=[e for e in r._events if e[2]=='trip_deadline']
        self.assertEqual(len(deadlines),1)
        r.parking_trips.resolved(p.id);gc.collect()
        self.assertFalse(any(e[2]=='trip_deadline' for e in r._events))
        self.assertFalse(any(k.startswith('trip_deadline:') for k in r._scheduled))

    def test_old_save_discards_obsolete_deadlines(self):
        from city_simulation import CitySimulation
        from persistence import world_from_dict
        r=self.runtime();p=worker(r);r.fleet.last_dispatch_status='inaccessible'
        r.parking_trips.defer(p.id,'commute')
        r._once('trip_deadline:old',999,'trip_deadline',[p.id,-1])
        restored=CitySimulation(world_from_dict(saved_world(r)).city_map);self.addCleanup(restored.close)
        self.assertEqual(sum(e[2]=='trip_deadline' for e in restored._events),1)
        self.assertNotIn('trip_deadline:old',restored._scheduled)

    def test_same_daily_commute_reuses_registered_geometry(self):
        r=self.runtime();p=worker(r)
        for day in range(3):
            r.update(day*86400-r.time);r._schedule_shift(p);r.update(1800)
            self.assertEqual(p.state,'home')
            self.assertEqual(r.fleet.vehicles[p.car_id].trips,(day+1)*2)
            self.assertEqual(len(r.transit.engine._routes),2)
            self.assertFalse(r.parking_trips.plans)
            self.assertFalse(r.fleet._travel)
        self.assertFalse(hasattr(r.transit.engine,'_route_sources'))

    def test_walking_eviction_keeps_active_lanes_and_reuses_idle_slots(self):
        r=self.runtime();t=r.transit;t.walk_route_limit=1
        points=[(100.,0.),(1000.,0.)]
        a=t.engine.register_pedestrian_lane(points)
        t._walk_routes['a']=a;t.engine.spawn_pedestrian(100,a,4.4)
        b=t.engine.register_pedestrian_lane([(100.,10.),(1000.,10.)])
        t._walk_routes['b']=b;t.engine.spawn_pedestrian(101,b,4.4)
        t._trim_walk_routes();self.assertEqual(len(t._walk_routes),2)
        t.engine.step(300);t._trim_walk_routes()
        self.assertEqual(len(t._walk_routes),1)
        c=t.engine.register_pedestrian_lane([(100.,20.),(1000.,20.)])
        self.assertEqual(c,a)

    def test_cache_and_history_bounds(self):
        cache=BoundedCache(max_entries=2)
        cache['a']=1;cache['b']=2;cache['a'];cache['c']=3
        self.assertEqual(list(cache),['a','c'])
        history=EventHistory();history.limit=16
        for i in range(100):history.append(i)
        self.assertLessEqual(len(history),16);self.assertEqual(history[-1],99)

    def test_vehicle_route_eviction_preserves_active_and_reuses_idle_slots(self):
        from native_traffic import NativeTrafficEngine,_Spawn
        from traffic_route_state import RouteState
        from types import SimpleNamespace
        import ctypes as C
        engine=NativeTrafficEngine(25);self.addCleanup(engine.close)
        engine.route_cache_limit=1
        def proxy(y):
            return SimpleNamespace(points=((0.,y),(1000.,y)),route=None,route_segments=(),
                                   controlled_movements=(),_route_cache=RouteState())
        a=engine.register_route(proxy(0))
        spawn=_Spawn(a,a,0,0,0,0,0.,0.,15.,6.,-1.,0.,0.,-1.)
        engine._call('nt_admit',C.byref(spawn),b'active')
        b=engine.register_route(proxy(10))
        self.assertEqual(len(engine._routes),2)
        engine._call('nt_remove',a);engine.trim_routes()
        self.assertEqual(len(engine._routes),1)
        c=engine.register_route(proxy(20))
        self.assertEqual(c,a)
