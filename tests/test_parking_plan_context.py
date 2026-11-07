"""Reusing endpoints must not mix commute and service-trip experience."""
import unittest
from commute_schedule import CommutePolicy
from town_services import Business
from tests.test_background_city import city_runtime,worker,prime
from tests.test_parking_fallback import fill_job


class ParkingPlanContextTests(unittest.TestCase):
    def runtime(self):
        r=city_runtime(CommutePolicy(departure_window=0,fallback_trip_seconds=0))
        self.addCleanup(r.close);p=worker(r);prime(r,p)
        r.fleet.admission.entrances[r.fleet._lot_key('a')]=100
        r.fleet.background=True
        return r,p

    def test_limited_commute_then_shopping_keeps_visit_out_of_commute_history(self):
        r,p=self.runtime()
        self.assertFalse(r._safe_depart(p))
        self.assertEqual(r.fleet.last_dispatch_status,'limited')
        self.assertEqual(r.parking_trips.preferences.to_dict()['parking'],[])
        r.fleet.background=False;r.fleet.admission.entrances.clear()
        r.configure_services([Business('job','market',{},None,0,{})])
        r.sites['a']['building'].inventory.amounts['food']=0
        r.sites['job']['building'].inventory.amounts['food']=10
        fill_job(r)
        self.assertTrue(r.request_shopping(p.id,'job','food',3))
        self.assertEqual(r.parking_trips.plans[p.id]['purpose'],'visit')
        self.assertEqual(r.parking_trips.preferences.to_dict()['parking'],[])

    def test_limited_visit_then_commute_records_real_parking_experience(self):
        r,p=self.runtime()
        self.assertFalse(r.parking_trips.start(p,'a','job',purpose='visit'))
        self.assertEqual(r.fleet.last_dispatch_status,'limited')
        r.fleet.background=False;r.fleet.admission.entrances.clear()
        fill_job(r)
        self.assertTrue(r._safe_depart(p))
        self.assertEqual(r.parking_trips.plans[p.id]['purpose'],'commute')
        rows=r.parking_trips.preferences.prior_parking(p.id,home='a',workplace='job',day=1)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].reason,'full')

    def test_rejected_visit_keeps_existing_commute_capacity_wait(self):
        from persistent_fleet import FleetVehicle
        r=city_runtime(CommutePolicy(departure_window=0,fallback_trip_seconds=0))
        self.addCleanup(r.close);p=worker(r);v=r.fleet.vehicles[p.car_id]
        for i,sid in enumerate(['job',*r.parking_trips.access.candidates('job')]):
            n=0
            while r.fleet._available_space(v,sid) is not False:
                r.fleet.add(FleetVehicle(f'full-{i}-{n}','car',sid));n+=1
        self.assertFalse(r._safe_depart(p));r.update(.05)
        self.assertIn(p.id,r.parking_trips.waits)
        self.assertFalse(r.parking_trips.start(p,'a','job',purpose='visit'))
        self.assertIn(p.id,r.parking_trips.waits)
        self.assertTrue(r.fleet.dispatch('full-0-0','b'))
        r.update(5)
        self.assertEqual(p.state,'commuting')
        self.assertEqual(r.parking_trips.plans[p.id]['purpose'],'commute')
        self.assertNotIn(p.id,r.parking_trips.waits)
