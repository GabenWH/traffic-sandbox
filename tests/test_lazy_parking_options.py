"""Successful parking admission must not construct unused walking alternatives."""
import unittest

from commute_schedule import CommutePolicy
from persistent_fleet import FleetVehicle
from tests.test_background_city import city_runtime, worker


class LazyParkingOptionsTests(unittest.TestCase):
    def runtime(self):
        runtime = city_runtime(CommutePolicy(departure_window=0))
        self.addCleanup(runtime.close)
        return runtime

    def test_free_primary_lot_departure_does_not_build_alternative_walks(self):
        runtime = self.runtime()
        person = worker(runtime)
        existing_walks = set(runtime.transit._walk_cache)
        self.assertTrue(runtime._safe_depart(person))
        vehicle = runtime.fleet.vehicles[person.car_id]
        self.assertEqual(vehicle.phase, 'driving')
        self.assertEqual(vehicle.destination, 'job')
        self.assertIsNotNone(vehicle.reserved_space_id)
        self.assertEqual(set(runtime.transit._walk_cache), existing_walks,
                         'A free primary lot needs no hypothetical walking routes')

    def test_overflow_departure_does_not_build_unused_later_walks(self):
        runtime = self.runtime()
        person = worker(runtime)
        lot = runtime.sites['job']['parking_lot']
        for index in range(lot.capacity):
            runtime.fleet.add(FleetVehicle('occupant-'+str(index), 'van', 'job'))
        existing_walks = set(runtime.transit._walk_cache)
        self.assertTrue(runtime._safe_depart(person))
        vehicle = runtime.fleet.vehicles[person.car_id]
        self.assertEqual(vehicle.phase, 'driving')
        self.assertNotEqual(vehicle.destination, 'job')
        self.assertIsNotNone(vehicle.reserved_space_id)
        # One lot-access eligibility route and one exact-space route suffice.
        self.assertLessEqual(len(set(runtime.transit._walk_cache) - existing_walks), 2)

    def test_partial_options_can_be_replayed_without_evaluating_the_tail(self):
        runtime = self.runtime()
        first = iter(runtime.parking_trips.options('job'))
        self.assertEqual(next(first), 'job')
        self.assertEqual(len(runtime.transit._walk_cache), 0)
        alternative = next(first)
        self.assertEqual(len(runtime.transit._walk_cache), 0,
                         'Eligibility needs a shared distance, not cached route geometry')
        second = iter(runtime.parking_trips.options('job'))
        self.assertEqual(next(second), 'job')
        self.assertEqual(next(second), alternative)
        self.assertEqual(len(runtime.transit._walk_cache), 0)
        # Independently advancing iterators must not duplicate or skip sites.
        complete = list(runtime.parking_trips.options('job'))
        self.assertGreater(len(complete), 2)
        self.assertEqual(len(complete), len(set(complete)))
        self.assertEqual(list(first), complete[2:])
        self.assertEqual(list(second), complete[2:])

    def test_clearing_options_rechecks_the_new_walking_limit(self):
        runtime = self.runtime()
        options = iter(runtime.parking_trips.options('job'))
        self.assertEqual(next(options), 'job')
        next(options)
        runtime.configure_commutes(CommutePolicy(departure_window=0, parking_walk_seconds=0))
        self.assertEqual(list(runtime.parking_trips.options('job')), ['job'])

    def test_complete_cached_options_do_not_wait_for_another_destinations_budget(self):
        runtime = city_runtime(CommutePolicy(departure_window=0, parking_walk_queries=1))
        self.addCleanup(runtime.close)
        complete = list(runtime.parking_trips.options('job'))
        other = iter(runtime.parking_trips.options('b', bounded=True))
        self.assertEqual(next(other), 'b')
        next(other)  # Spend the allowance on a different destination.
        self.assertEqual(list(runtime.parking_trips.options('job', bounded=True)), complete)

    def test_visit_searches_do_not_inherit_commuter_planning_retries(self):
        runtime = city_runtime(CommutePolicy(departure_window=0, fallback_trip_seconds=0))
        self.addCleanup(runtime.close)
        person = worker(runtime)
        vehicle = runtime.fleet.vehicles[person.car_id]
        for index, sid in enumerate(['job', *runtime.parking_trips.access.candidates('job')]):
            serial = 0
            while runtime.fleet._available_space(vehicle, sid) is not False:
                runtime.fleet.add(FleetVehicle(f'visit-full-{index}-{serial}', 'car', sid))
                serial += 1
        runtime._inside_update = True
        try:
            self.assertFalse(runtime.parking_trips.start(person, 'a', 'job', purpose='visit'))
        finally:
            runtime._inside_update = False
        self.assertEqual(runtime.fleet.last_dispatch_status, 'full',
                         'Service callers have different retries; do not apply the commute-only budget')

    def test_cold_full_lots_share_a_bounded_search_budget_across_event_fragments(self):
        runtime = city_runtime(CommutePolicy(departure_window=0, fallback_trip_seconds=0))
        self.addCleanup(runtime.close)
        person = worker(runtime)
        vehicle = runtime.fleet.vehicles[person.car_id]
        sites = ['job', *runtime.parking_trips.access.candidates('job')]
        for index, sid in enumerate(sites):
            serial = 0
            while runtime.fleet._available_space(vehicle, sid) is not False:
                runtime.fleet.add(FleetVehicle(f'full-{index}-{serial}', 'car', sid))
                serial += 1
        existing = len(runtime.transit._walk_cache)
        for i in range(1, 10):
            runtime._once('fragment:'+str(i), i*.005, 'builders')
        runtime.update(.05)
        self.assertLessEqual(len(runtime.transit._walk_cache)-existing, 4,
                             'Cold alternatives must not all search in one movement quantum')
        self.assertEqual(person.state, 'home')
        self.assertIn(person.id, runtime._pending_departures)
        from city_simulation import CitySimulation
        from persistence import world_from_dict
        from tests.test_background_city import saved_world
        restored = CitySimulation(world_from_dict(saved_world(runtime)).city_map)
        self.addCleanup(restored.close)
        self.assertIn(person.id, restored._pending_departures)
        restored.update(10)
        self.assertEqual(restored.parking_trips.waits[person.id]['reason'], 'full')
        runtime.update(10)
        self.assertEqual(runtime.parking_trips.waits[person.id]['reason'], 'full')
        self.assertNotIn(person.id, runtime._pending_departures)


if __name__ == '__main__':
    unittest.main()
