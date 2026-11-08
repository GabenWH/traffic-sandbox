"""Blocked drivers can take a real bus before searching overflow parking."""
import unittest
from unittest.mock import patch

from commute_schedule import CommutePolicy
from mobility import lane_position_at_distance
from transit import Bus, BusLine, BusStop
from test_background_city import city_runtime, worker
from test_parking_fallback import fill_job
from test_transit import TransitTests


class BlockedDriverBusTests(unittest.TestCase):
    def runtime(self, *, fuel=100):
        runtime = city_runtime(CommutePolicy(departure_window=0))
        self.addCleanup(runtime.close)
        lane = next(l for l in runtime.city.roads[0].lanes if l.direction == 'forward')
        for name, distance, site in [('A', 200, 'a'), ('B', 3200, 'job')]:
            runtime.transit.add_stop(BusStop(name, lane_position_at_distance(lane, distance),
                                           runtime.sites[site]['walk_point']))
        runtime.transit.add_line(BusLine('L', ('A', 'B'), headway_seconds=60))
        runtime.transit.add_bus(Bus('bus', 'L', fuel_liters=fuel))
        return runtime

    def test_full_parking_uses_bus_before_overflow_and_keeps_car_home(self):
        runtime = self.runtime()
        person = worker(runtime)
        fill_job(runtime)
        car = runtime.fleet.vehicles[person.car_id]
        original_space = car.parking_space_id
        def primary_only(*args, **kwargs):
            yield 'job'
            if kwargs.get('max_distance') is not None:
                return
            raise AssertionError('searched overflow after a viable bus fallback')
        with patch.object(runtime.parking_trips, 'options', primary_only):
            self.assertTrue(runtime._safe_depart(person))
        self.assertEqual(runtime.fleet.last_dispatch_status, 'transit')
        self.assertTrue(runtime.transit.people[person.id].itinerary)
        self.assertEqual(runtime.parking_trips.plans[person.id]['stage'], 'fallback')
        self.assertEqual((car.site, car.phase, car.parking_space_id), ('a', 'parked', original_space))
        runtime.update(900)
        self.assertEqual(person.state, 'work')
        self.assertTrue(any(e['event'] == 'board' for e in runtime.transit.events))
        self.assertEqual(car.site, 'a')
        runtime.update(1100)
        self.assertEqual(person.state, 'home')
        self.assertEqual(car.site, 'a')

    def test_empty_bus_does_not_claim_a_transit_fallback(self):
        runtime = self.runtime(fuel=0)
        person = worker(runtime)
        fill_job(runtime)
        self.assertTrue(runtime._safe_depart(person))  # Existing walk/overflow recovery remains valid.
        self.assertNotEqual(runtime.fleet.last_dispatch_status, 'transit')

    def test_free_parking_within_50m_is_used_before_bus(self):
        from math import dist
        from parking_trips import PARKING_BEFORE_BUS_FEET
        runtime = self.runtime()
        person = worker(runtime)
        fill_job(runtime)
        nearby = list(runtime.parking_trips.options('job', max_distance=PARKING_BEFORE_BUS_FEET))
        self.assertGreater(len(nearby), 1)
        for site in nearby[1:]:
            self.assertLessEqual(dist(runtime.fleet.sites[site]['walk_point'],
                                      runtime.sites['job']['walk_point']), PARKING_BEFORE_BUS_FEET)
        with patch.object(runtime.parking_trips, '_fallback', side_effect=AssertionError('bus before nearby parking')):
            self.assertTrue(runtime._safe_depart(person))
        self.assertIn(runtime.fleet.vehicles[person.car_id].destination, nearby[1:])

    def test_required_bus_is_real_ride_even_when_walking_is_faster(self):
        transit = TransitTests().system()
        self.addCleanup(transit.traffic._discard_native)
        origin, destination = (100, 15), (144, 15)
        self.assertFalse(any(kind == 'ride' for kind, value in transit.journey_path(origin, destination).edges))
        path = transit.journey_path(origin, destination, require_bus=True)
        self.assertTrue(any(kind == 'ride' for kind, value in path.edges))
        person = transit.request_trip(1, origin, destination, require_bus=True)
        self.assertTrue(person.itinerary)

    def test_no_service_cannot_satisfy_required_bus(self):
        transit = TransitTests().system(fuel=0)
        self.addCleanup(transit.traffic._discard_native)
        with self.assertRaises(ValueError):
            transit.request_trip(1, (100, 15), (144, 15), require_bus=True)
        self.assertNotIn(1, transit.people)
