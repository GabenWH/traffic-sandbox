"""Future mode choice gets saved, route-scoped prior-day parking experience."""
import json
import unittest
from dataclasses import asdict

from commute_schedule import CommutePolicy
from city_simulation import CitySimulation
from persistence import world_from_dict
from tests.test_background_city import city_runtime,worker,saved_world
from tests.test_parking_fallback import fill_job


class CommutePreferenceTests(unittest.TestCase):
    def setUp(self):
        self.runtime=city_runtime(CommutePolicy(departure_window=0))
        self.addCleanup(self.runtime.close)
        self.person=worker(self.runtime)
        self.model=getattr(self.runtime.parking_trips,'preferences',None)
        self.assertIsNotNone(self.model,'Commute-preference scaffolding is missing')

    def record(self,day=0,home='a',workplace='job',reason='full'):
        return self.model.record_parking(self.person.id,home=home,workplace=workplace,day=day,reason=reason)

    def prior(self,day,home='a',workplace='job'):
        return self.model.prior_parking(self.person.id,home=home,workplace=workplace,day=day)

    def test_today_is_excluded_and_next_day_can_read_parking_experience(self):
        self.record()
        self.assertEqual(self.prior(0),())
        tomorrow=self.prior(1)
        self.assertEqual(len(tomorrow),1)
        self.assertEqual((tomorrow[0].day,tomorrow[0].home,tomorrow[0].workplace,tomorrow[0].reason),(0,'a','job','full'))

    def test_changed_home_or_workplace_does_not_inherit_unrelated_experience(self):
        self.record()
        self.assertEqual(self.prior(1,home='b'),())
        self.assertEqual(self.prior(1,workplace='another-job'),())

    def test_retries_record_one_daily_trip_observation(self):
        self.record();self.record(reason='overflow');self.record()
        self.assertEqual(len(self.prior(1)),1)

    def test_history_is_bounded_and_old_experience_ages_out(self):
        for day in range(30):self.record(day=day)
        self.assertEqual(len(self.prior(30)),14)
        self.assertEqual(self.prior(44),())
        self.assertEqual(len(self.model.to_dict()['parking']),14)

    def test_neutral_profile_and_custom_weights_round_trip(self):
        from commute_preferences import CommutePreferences,ModePreferences
        self.assertEqual(asdict(self.model.profile(self.person.id)),{'car':1.,'walk':1.,'transit':1.})
        self.model.set_profile(self.person.id,ModePreferences(car=.25,walk=2.,transit=3.))
        self.record()
        restored=CommutePreferences.from_dict(json.loads(json.dumps(self.model.to_dict())))
        self.assertEqual(asdict(restored.profile(self.person.id)),{'car':.25,'walk':2.,'transit':3.})
        self.assertEqual(restored.prior_parking(self.person.id,home='a',workplace='job',day=1),self.prior(1))

    def test_actual_overflow_records_experience_without_changing_preferred_mode(self):
        fill_job(self.runtime)
        self.assertTrue(self.runtime._safe_depart(self.person))
        car=self.runtime.fleet.vehicles[self.person.car_id]
        self.assertEqual(self.person.mode,'car')
        self.assertEqual(car.phase,'driving')
        self.assertNotEqual(car.destination,'job')
        self.assertEqual(self.prior(0),())
        self.assertEqual(len(self.prior(1)),1)
        self.assertEqual(self.prior(1)[0].reason,'full')

    def test_preferences_remain_inactive_on_tomorrows_departure(self):
        from commute_preferences import ModePreferences
        self.record()
        self.model.set_profile(self.person.id,ModePreferences(car=0.,walk=100.,transit=100.))
        r=self.runtime
        r.time=r.transit.time=r.transit.traffic.elapsed_time=86400.
        r.transit.engine._call('nt_clock',r.time,0.,0.)
        self.assertTrue(r._safe_depart(self.person))
        self.assertEqual(self.person.mode,'car')
        self.assertEqual(r.fleet.vehicles[self.person.car_id].phase,'driving')

    def test_return_trips_and_visits_do_not_record_commute_parking_trouble(self):
        fill_job(self.runtime)
        self.assertTrue(self.runtime.parking_trips.start(self.person,'a','job',purpose='visit'))
        self.assertEqual(self.prior(1),())

    def test_city_save_load_preserves_profile_and_today_observation(self):
        from commute_preferences import ModePreferences
        self.model.set_profile(self.person.id,ModePreferences(car=.5,walk=2.,transit=4.))
        self.record()
        restored=CitySimulation(world_from_dict(saved_world(self.runtime)).city_map)
        self.addCleanup(restored.close)
        model=restored.parking_trips.preferences
        self.assertEqual(asdict(model.profile(self.person.id)),{'car':.5,'walk':2.,'transit':4.})
        self.assertEqual(model.prior_parking(self.person.id,home='a',workplace='job',day=0),())
        self.assertEqual(len(model.prior_parking(self.person.id,home='a',workplace='job',day=1)),1)

    def test_legacy_save_without_preferences_stays_valid(self):
        data=saved_world(self.runtime)
        data['gameplay']['commutes']['parking'].pop('preferences',None)
        restored=CitySimulation(world_from_dict(data).city_map)
        self.addCleanup(restored.close)
        self.assertEqual(restored.parking_trips.preferences.prior_parking(self.person.id,home='a',workplace='job',day=1),())

    def test_invalid_saved_profiles_and_future_observations_are_rejected(self):
        data=saved_world(self.runtime)
        data['gameplay']['commutes']['parking']['preferences']={
            'schema':1,'profiles':[],'parking':[dict(person=self.person.id,home='a',workplace='job',day=1,reason='full')]}
        with self.assertRaises(ValueError):CitySimulation(world_from_dict(data).city_map)
        from commute_preferences import CommutePreferences
        for value in (-1.,float('nan'),True):
            with self.subTest(weight=value),self.assertRaises(ValueError):
                CommutePreferences.from_dict({'profiles':[dict(person=0,weights=dict(car=value,walk=1.,transit=1.))]})

class CommuteScaffoldEdgeTests(unittest.TestCase):
    def test_return_parking_recalibration_does_not_become_outbound_history(self):
        from persistent_fleet import FleetVehicle
        r=city_runtime(CommutePolicy(departure_window=0))
        self.addCleanup(r.close);p=worker(r);p.state='work'
        car=r.fleet.vehicles[p.car_id];car.site='job'
        car.parking_space_id=r.fleet._available_space(car,'job');r.fleet.restore_parking()
        for i in range(r.sites['a']['parking_lot'].capacity):
            r.fleet.add(FleetVehicle('home-occupant-'+str(i),'car','a'))
        self.assertTrue(r._safe_depart(p,True))
        self.assertEqual(r.parking_trips.preferences.prior_parking(p.id,home='job',workplace='a',day=1),())
        self.assertEqual(r.parking_trips.preferences.to_dict()['parking'],[])

    def test_normal_primary_parking_does_not_create_trouble_memory(self):
        r=city_runtime(CommutePolicy(departure_window=0));self.addCleanup(r.close);p=worker(r)
        self.assertTrue(r._safe_depart(p))
        self.assertEqual(r.parking_trips.preferences.to_dict()['parking'],[])

    def test_schema_bool_duplicate_profiles_and_unknown_residents_are_invalid(self):
        from commute_preferences import CommutePreferences
        bad=[{'schema':True},
             {'profiles':[dict(person=2,weights={}),dict(person=2,weights={})]},
             {'profiles':[dict(person=9,weights={})]}]
        for data in bad:
            with self.subTest(data=data),self.assertRaises(ValueError):
                CommutePreferences.from_dict(data,resident_ids={2})
