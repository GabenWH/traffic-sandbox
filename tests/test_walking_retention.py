"""Retained query paths must stay bounded without breaking live native walkers."""
import gc
import unittest

from city import CityMap, Terrain
from transit import TransitSimulation
from gameplay_persistence import dump_transport, restore_transport


def walking_city():
    city=CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0,0),(9000,0)])
    return city


class WalkingRetentionTests(unittest.TestCase):
    def test_more_distinct_queries_than_capacity_do_not_accumulate_paths(self):
        sim=TransitSimulation(walking_city())
        for i in range(550):sim._walk((10+i,15),(8900,15))
        self.assertLessEqual(len(sim._walk_cache),512)

    def test_native_registry_does_not_retain_gc_tracked_point_tuples(self):
        sim=TransitSimulation(walking_city())
        sim.request_trip(1,(100,15),(8500,15))
        key=next(iter(sim._walk_routes))
        self.assertFalse(gc.is_tracked(key[0]),'Native route lookup must not retain the Python point graph')

    def test_recent_route_is_reused_while_older_route_is_evicted(self):
        sim=TransitSimulation(walking_city())
        a=((10,15),(8900,15));b=((11,15),(8900,15))
        first=sim._walk(*a);sim._walk(*b)
        for i in range(2,512):sim._walk((10+i,15),(8900,15))
        self.assertIs(sim._walk(*a),first)
        sim._walk((1000,15),(8900,15))
        self.assertIn(a,sim._walk_cache)
        self.assertFalse(b in sim._walk_cache)

    def test_live_walk_survives_query_eviction_and_transport_restore(self):
        city=walking_city();sim=TransitSimulation(city)
        sim.request_trip(1,(100,15),(8500,15))
        sim.update(1)
        for i in range(550):sim._walk((200+i,15),(8900,15))
        self.assertFalse(((100,15),(8500,15)) in sim._walk_cache)
        saved=dump_transport(sim)
        self.assertGreater(len(saved['walkers'][0]['points']),1)
        restored=TransitSimulation(city);restore_transport(restored,saved)
        restored.update(2100)
        self.assertEqual(restored.people[1].phase,'arrived')
        self.assertEqual(len(restored._walk_routes),1)


if __name__=='__main__':unittest.main()

class WalkingCacheBoundsTests(unittest.TestCase):
    def route(self, count=2):
        from pedestrian_mobility import WalkingRoute
        return WalkingRoute(tuple((float(i),0.) for i in range(count)),(),float(count-1),-1.)

    def test_geometry_budget_evicts_before_entry_capacity(self):
        from walking_cache import WalkingRouteCache
        cache=WalkingRouteCache(max_entries=10,max_units=3)
        cache['a']=self.route();cache['b']=self.route()
        self.assertEqual(set(cache),{'b'})
        self.assertEqual(cache.units,2)

    def test_oversized_query_is_returned_but_not_retained(self):
        from walking_cache import WalkingRouteCache
        sim=TransitSimulation(walking_city())
        sim._walk_cache=WalkingRouteCache(max_entries=10,max_units=1)
        route=sim._walk((100,15),(8500,15))
        self.assertGreater(route.length,8000)
        self.assertEqual(len(sim._walk_cache),0)

    def test_mapping_snapshot_can_read_all_values_without_iterator_mutation(self):
        from walking_cache import WalkingRouteCache
        cache=WalkingRouteCache(max_entries=4,max_units=20)
        cache['a']=self.route();cache['b']=self.route();cache['c']=self.route()
        self.assertEqual(set(dict(cache)),{'a','b','c'})
        self.assertEqual(len(list(cache.values())),3)

    def test_replacing_deleting_and_clearing_release_accounted_geometry(self):
        from walking_cache import WalkingRouteCache
        cache=WalkingRouteCache(max_entries=3,max_units=10)
        cache['a']=self.route(3);cache['a']=self.route(2);cache['b']=self.route(3)
        self.assertEqual(cache.units,5)
        del cache['a'];self.assertEqual(cache.units,3)
        cache.clear();self.assertEqual((len(cache),cache.units),(0,0))

    def test_exact_geometry_key_preserves_coordinates_and_crossing(self):
        from walking_cache import walking_geometry_key,walking_geometry_points
        points=((1.25,-3.),(1.250000000000001,-3.),(8000.,1e-10))
        key=walking_geometry_key(points,.37)
        self.assertFalse(gc.is_tracked(key[0]))
        self.assertEqual(walking_geometry_points(key),points)
        self.assertEqual(key[1],.37)
        self.assertNotEqual(key,walking_geometry_key(points[:-1],.37))
