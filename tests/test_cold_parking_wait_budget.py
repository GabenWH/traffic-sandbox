"""Restoring capacity waiters must not synchronously rebuild walking options."""
import unittest

from city_simulation import CitySimulation
from commute_schedule import CommutePolicy
from persistent_fleet import FleetVehicle
from persistence import world_from_dict
from tests.test_background_city import city_runtime,worker,saved_world


class ColdParkingWaitBudgetTests(unittest.TestCase):
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
        original=restored.transit.journey_path;queries=[]
        def journey(*args,**kw):
            queries.append((args,kw));return original(*args,**kw)
        restored.transit.journey_path=journey
        restored.update(.05)
        self.assertLessEqual(len(queries),4,'A saved full-lot waiter bypassed the walking search budget')
        self.assertTrue(p.id in restored.parking_trips.waits or p.id in restored._pending_departures)
        self.assertFalse(restored.transit.traffic.cars)
        restored.transit.journey_path=original
        restored.update(2)
        self.assertEqual(restored.parking_trips.waits[p.id]['reason'],'full')
