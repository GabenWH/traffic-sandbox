"""A completed visitor must release admission ownership for the next waiter."""
import unittest

from commute_schedule import CommutePolicy
from persistent_fleet import FleetVehicle
from tests.test_background_city import city_runtime, worker


class ParkingServiceWaitTests(unittest.TestCase):
    def test_later_capacity_release_admits_second_waiting_service_return(self):
        runtime = city_runtime(CommutePolicy(departure_window=0,
            parking_walk_seconds=0, fallback_trip_seconds=0))
        self.addCleanup(runtime.close)
        people = [worker(runtime), worker(runtime)]
        for person in people:
            person.worker = False
        runtime._events.clear()
        runtime._scheduled.clear()
        runtime._pending_departures.clear()
        # Complete their outbound journeys before the home lot fills.
        for person in people:
            person.state = 'commuting'
            self.assertTrue(runtime.fleet.dispatch(person.car_id, 'job'))
            runtime.update(5)
        runtime.update(150)
        self.assertTrue(all(runtime.fleet.vehicles[p.car_id].site == 'job' for p in people))
        for index in range(runtime.sites['a']['parking_capacity']):
            runtime.fleet.add(FleetVehicle('home-blocker-'+str(index), 'van', 'a'))
        for person in people:
            runtime.visits[person.id] = dict(site='job', purpose='meal', origin='a', previous='home')
            person.state = 'waiting_meal'
            runtime._leave_service(person.id)
        self.assertTrue(all(p.state == 'service_return_pending' for p in people))

        self.assertTrue(runtime.fleet.dispatch('home-blocker-0', 'b'))
        runtime.update(300)
        self.assertEqual(people[0].state, 'home')
        self.assertEqual(people[1].state, 'service_return_pending')

        self.assertTrue(runtime.fleet.dispatch('home-blocker-1', 'b'))
        runtime.update(300)
        self.assertEqual(people[1].state, 'home')
        self.assertEqual(runtime.fleet.vehicles[people[1].car_id].site, 'a')
        self.assertFalse(runtime.parking_trips.waits)
        self.assertFalse(runtime.parking_trips._capacity_inflight)
        self.assertFalse(runtime.parking_trips._woken_lots)
