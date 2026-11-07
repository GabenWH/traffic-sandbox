"""Restoring capacity waiters must not synchronously rebuild walking options."""
import unittest
from unittest.mock import patch

from city_simulation import CitySimulation
from commute_schedule import CommutePolicy
from persistent_fleet import FleetVehicle
from persistence import world_from_dict
from tests.test_background_city import city_runtime,worker,saved_world


class ColdParkingWaitBudgetTests(unittest.TestCase):
    def test_registering_cold_full_wait_uses_the_shared_walking_query_budget(self):
        r=city_runtime(CommutePolicy(departure_window=0,parking_walk_queries=1))
        self.addCleanup(r.close);p=worker(r)
        r.fleet.last_dispatch_status='full'
        r._inside_update=True
        try:
            with patch.object(r.transit,'walking_cost',wraps=r.transit.walking_cost) as cost:
                r.parking_trips.defer(p.id,'commute')
            self.assertLessEqual(cost.call_count,1)
        finally:r._inside_update=False
        self.assertIn(p.id,r._pending_departures,'An incomplete wait search must resume later')
        r.update(10)
        self.assertTrue(p.id in r.parking_trips.waits or p.state!='home')

    def test_failed_walker_does_not_inherit_previous_car_failure(self):
        r=city_runtime(CommutePolicy(departure_window=0))
        self.addCleanup(r.close);p=worker(r,car=False)
        r.fleet.last_dispatch_status='full'
        with patch.object(r.transit,'request_trip',side_effect=ValueError('no walking route')):
            self.assertFalse(r._safe_depart(p))
            self.assertNotIn(p.id,r.parking_trips.waits)
            r.update(.05)
            self.assertNotIn(p.id,r.parking_trips.waits)
        r.update(70)
        self.assertEqual(p.state,'commuting')

    def test_restored_full_lots_check_capacity_without_rebuilding_walking_routes(self):
        r=city_runtime(CommutePolicy(departure_window=0,fallback_trip_seconds=0))
        self.addCleanup(r.close);p=worker(r);car=r.fleet.vehicles[p.car_id]
        sites=['job',*r.parking_trips.access.candidates('job')]
        for i,sid in enumerate(sites):
            serial=0
            while r.fleet._available_space(car,sid) is not False:
                r.fleet.add(FleetVehicle(f'full-{i}-{serial}','car',sid));serial+=1
        self.assertFalse(r._safe_depart(p))
        self.assertEqual(r.parking_trips.waits[p.id]['reason'],'full')
        restored=CitySimulation(world_from_dict(saved_world(r)).city_map)
        self.addCleanup(restored.close)
        original=restored.transit.walking_cost;queries=[]
        def journey(*args,**kw):
            queries.append((args,kw));return original(*args,**kw)
        restored.transit.walking_cost=journey
        restored.update(.05)
        self.assertLessEqual(len(queries),4,'A saved full-lot waiter bypassed the walking search budget')
        self.assertTrue(p.id in restored.parking_trips.waits or p.id in restored._pending_departures)
        self.assertFalse(restored.transit.traffic.cars)
        restored.transit.walking_cost=original
        restored.update(2)
        self.assertEqual(restored.parking_trips.waits[p.id]['reason'],'full')
