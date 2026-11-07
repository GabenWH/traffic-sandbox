"""Parking waits retain deadlines, physical recovery, and release notifications."""
import unittest

from city_simulation import CitySimulation
from commute_schedule import CommutePolicy
from persistent_fleet import FleetVehicle
from persistence import world_from_dict
from tests.test_background_city import city_runtime, worker, saved_world


class ParkingWaitRecoveryTests(unittest.TestCase):
    def runtime(self, **policy):
        runtime = city_runtime(CommutePolicy(departure_window=0, **policy))
        self.addCleanup(runtime.close)
        return runtime

    def fill(self, runtime, site, prefix):
        for index in range(runtime.fleet.sites[site]['parking_capacity']):
            runtime.fleet.add(FleetVehicle(prefix+str(index), 'van', site))

    def test_expired_return_at_car_stays_visible_and_recovers_after_space_release(self):
        runtime = self.runtime(fallback_trip_seconds=0)
        person = worker(runtime)
        self.fill(runtime, 'job', 'work-occupant-')
        runtime.update(900)
        self.assertEqual(person.state, 'work')
        self.assertTrue(runtime._safe_depart(person, True))
        self.assertEqual(runtime.parking_trips.plans[person.id]['stage'], 'walk_to_car')
        # The destination was free when the driver set out to retrieve the car.
        self.fill(runtime, 'a', 'home-blocker-')
        runtime.update(100)
        self.assertEqual(runtime.parking_trips.waits[person.id]['kind'], 'resume')
        runtime.update(86400)
        self.assertEqual(runtime.report()['commute_unmet'], 1)
        blocked = [row for row in runtime.report()['blocked_trips'] if row['person'] == person.id]
        self.assertEqual(len(blocked), 1, 'An overdue driver away from home must remain visibly recoverable')

        self.assertTrue(runtime.fleet.dispatch('home-blocker-0', 'b'))
        runtime.update(300)
        self.assertEqual(person.state, 'home')
        self.assertEqual(runtime.fleet.vehicles[person.car_id].site, 'a')
        self.assertEqual(runtime.report()['commute_unmet'], 1)
        self.assertFalse(any(row['person'] == person.id for row in runtime.report()['blocked_trips']))

    def test_outbound_wait_after_retrieving_car_keeps_original_shift_deadline(self):
        runtime = self.runtime(fallback_trip_seconds=0)
        runtime.work_end = 200
        person = worker(runtime, car=False)
        person.mode, person.car_id = 'car', 'nearby-car'
        # An already parked car is within walking reach of home but not work.
        runtime.fleet.add(FleetVehicle(person.car_id, 'car', 'b', driver=person.id))
        self.assertTrue(runtime._safe_depart(person))
        self.assertEqual(runtime.parking_trips.plans[person.id]['stage'], 'walk_to_car')
        for index, endpoint in enumerate(runtime.parking_trips.options('job')):
            self.fill(runtime, endpoint, 'work-blocker-'+str(index)+'-')
        runtime.update(190)
        wait = runtime.parking_trips.waits[person.id]
        self.assertEqual(wait['kind'], 'resume')
        self.assertEqual(wait['deadline'], 200)
        runtime.update(11)
        self.assertEqual(runtime.report()['commute_unmet'], 1)

    def test_save_immediately_after_release_wakes_restored_waiter(self):
        runtime = self.runtime(parking_walk_seconds=0, fallback_trip_seconds=0)
        person = worker(runtime)
        self.fill(runtime, 'job', 'occupant-')
        runtime.update(1)
        self.assertEqual(runtime.report()['commute_waiting'], 1)
        self.assertTrue(runtime.fleet.dispatch('occupant-0', 'b'))
        # Save before the city's next update consumes the release notification.
        restored = CitySimulation(world_from_dict(saved_world(runtime)).city_map)
        self.addCleanup(restored.close)
        restored.update(10)
        self.assertEqual(restored.residents[person.id].state, 'commuting')
        self.assertEqual(restored.fleet.vehicles[person.car_id].phase, 'driving')
        self.assertEqual(restored.report()['commute_waiting'], 0)
