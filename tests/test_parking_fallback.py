"""Regression coverage for full parking, explicit outcomes and car/walk legs."""
import json
import unittest
from dataclasses import replace

from commute_schedule import CommutePolicy
from persistent_fleet import FleetVehicle
from test_background_city import city_runtime, worker, saved_world


def fill_job(runtime):
    lot = runtime.sites['job']['parking_lot']
    for index in range(lot.capacity):
        runtime.fleet.add(FleetVehicle('occupant-'+str(index), 'van', 'job'))


class ParkingFallbackTests(unittest.TestCase):
    def make_runtime(self):
        runtime = city_runtime(CommutePolicy(departure_window=0))
        self.addCleanup(runtime.close)
        return runtime

    def test_full_workplace_does_not_leave_a_reachable_worker_at_home(self):
        runtime = self.make_runtime()
        person = worker(runtime)
        fill_job(runtime)
        runtime.update(900)
        self.assertEqual(person.state, 'work')
        self.assertEqual(runtime.workers_arrived, 1)
        self.assertEqual(runtime.report()['commute_waiting'], 0)
        self.assertEqual(len({v.id for v in runtime.fleet.vehicles.values()}), len(runtime.fleet.vehicles))

    def test_missing_vehicle_access_uses_a_walkable_trip(self):
        runtime = self.make_runtime()
        person = worker(runtime)
        runtime.sites['job']['road_position'] = None
        runtime.update(900)
        self.assertEqual(person.state, 'work')
        self.assertEqual(runtime.workers_arrived, 1)
        runtime.update(1000)
        self.assertEqual(person.state, 'home')
        self.assertEqual(runtime.fleet.vehicles[person.car_id].site, person.home)

    def test_unresolved_shift_is_recorded_instead_of_discarded(self):
        runtime = self.make_runtime()
        person = worker(runtime)
        # Remove the walking connection as well as the vehicle endpoint.
        runtime.sites['job']['walk_point'] = (100000., 100000.)
        runtime.sites['job']['road_position'] = None
        fill_job(runtime)
        runtime.update(1001)
        outcomes = [e for e in runtime.events if e['event'] == 'trip_unmet']
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]['person'], person.id)
        self.assertEqual(outcomes[0]['destination'], 'job')
        self.assertEqual(runtime.report()['commute_waiting'], 0)
        self.assertEqual(runtime.report()['commute_unmet'], 1)

    def test_static_access_failure_is_not_retried_every_quarter_second(self):
        runtime = self.make_runtime()
        person = worker(runtime)
        runtime.sites['job']['walk_point'] = (100000., 100000.)
        runtime.sites['job']['road_position'] = None
        original = runtime.fleet.dispatch
        attempts = []
        def dispatch(*args, **kwargs):
            attempts.append((runtime.time, args))
            return original(*args, **kwargs)
        runtime.fleet.dispatch = dispatch
        runtime.update(1)
        before = len(attempts)
        runtime.update(60)
        self.assertEqual(len(attempts), before)
        self.assertEqual(person.state, 'home')
        self.assertEqual(runtime.report()['commute_waiting'], 1)
        self.assertGreaterEqual(runtime.report()['blocked_trips'][0]['wait_seconds'], 60)

    def test_overflow_arrival_requires_walk_and_return_retrieves_same_car(self):
        runtime = self.make_runtime()
        person = worker(runtime)
        fill_job(runtime)
        vehicle = runtime.fleet.vehicles[person.car_id]
        for _ in range(4000):
            runtime.update(.05)
            if vehicle.trips:
                break
        self.assertEqual(vehicle.phase, 'parked')
        self.assertNotEqual(vehicle.site, person.workplace)
        self.assertEqual(person.state, 'commuting')
        self.assertEqual(runtime.workers_arrived, 0)
        parking = vehicle.site
        runtime.update(200)
        self.assertEqual(person.state, 'work')
        self.assertEqual(runtime.staff['job'], 1)
        runtime.update(1000.05-runtime.time)
        self.assertEqual(person.state, 'returning')
        self.assertEqual(vehicle.phase, 'parked')
        self.assertEqual(vehicle.site, parking)
        self.assertEqual(runtime.parking_trips.plans[person.id]['stage'], 'walk_to_car')
        runtime.update(500)
        self.assertEqual(person.state, 'home')
        self.assertEqual(vehicle.site, person.home)
        self.assertEqual(vehicle.trips, 2)

    def test_single_space_release_admits_only_one_waiting_car(self):
        policy = CommutePolicy(departure_window=0, parking_walk_seconds=0, fallback_trip_seconds=0)
        runtime = city_runtime(policy)
        self.addCleanup(runtime.close)
        people = [worker(runtime, 'a'), worker(runtime, 'b')]
        fill_job(runtime)
        runtime.update(1)
        self.assertEqual(runtime.report()['commute_waiting'], 2)
        self.assertEqual(runtime.report()['blocked_by_destination']['job']['count'], 2)
        lot_id = runtime.sites['job']['parking_lot'].id
        self.assertEqual(runtime.report()['blocked_by_parking_lot'][lot_id]['count'], 2)
        self.assertTrue(runtime.fleet.dispatch('occupant-0', 'a'))
        runtime.update(5)
        cars = [runtime.fleet.vehicles[p.car_id] for p in people]
        self.assertEqual(sum(v.phase=='driving' for v in cars), 1)
        self.assertEqual(sum(v.reserved_space_id is not None for v in cars), 1)
        self.assertEqual(runtime.report()['commute_waiting'], 1)
        self.assertEqual(people[0].state, 'commuting')

    def test_waiting_trip_and_deadline_survive_save_load(self):
        from city_simulation import CitySimulation
        from persistence import world_from_dict
        runtime = city_runtime(CommutePolicy(departure_window=0, parking_walk_seconds=0, fallback_trip_seconds=0))
        self.addCleanup(runtime.close)
        person = worker(runtime)
        fill_job(runtime)
        runtime.update(1)
        restored = CitySimulation(world_from_dict(saved_world(runtime)).city_map)
        self.addCleanup(restored.close)
        self.assertEqual(restored.report()['commute_waiting'], 1)
        restored.update(1000)
        self.assertEqual(restored.report()['commute_unmet'], 1)
        self.assertEqual(restored.residents[person.id].state, 'home')
        self.assertEqual(len([e for e in restored.events if e['event']=='trip_unmet']), 1)
        after_deadline = CitySimulation(world_from_dict(saved_world(restored)).city_map)
        self.addCleanup(after_deadline.close)
        outcome=after_deadline.report()['last_unmet_trips'][person.id]
        self.assertEqual(outcome['destination'],'job')
        self.assertEqual(outcome['reason'],'full')
        self.assertEqual(outcome['time'],1000.)

    def test_overflow_walk_leg_and_car_location_survive_save_load(self):
        from city_simulation import CitySimulation
        from persistence import world_from_dict
        runtime = self.make_runtime()
        person = worker(runtime)
        fill_job(runtime)
        for _ in range(4000):
            runtime.update(.05)
            if runtime.fleet.vehicles[person.car_id].trips:
                break
        restored = CitySimulation(world_from_dict(saved_world(runtime)).city_map)
        self.addCleanup(restored.close)
        self.assertEqual(restored.residents[person.id].state, 'commuting')
        self.assertEqual(restored.fleet.vehicles[person.car_id].site, runtime.fleet.vehicles[person.car_id].site)
        restored.update(1400)
        self.assertEqual(restored.residents[person.id].state, 'home')
        self.assertEqual(restored.fleet.vehicles[person.car_id].site, person.home)
        self.assertEqual(restored.workers_arrived, 1)

    def test_worker_attendance_can_be_saved_after_parking_and_walking(self):
        from city_simulation import CitySimulation
        from persistence import world_from_dict
        runtime = self.make_runtime()
        person = worker(runtime)
        fill_job(runtime)
        runtime.update(300)
        self.assertEqual(person.state, 'work')
        restored = CitySimulation(world_from_dict(saved_world(runtime)).city_map)
        self.addCleanup(restored.close)
        self.assertEqual(restored.residents[person.id].state, 'work')
        self.assertEqual(restored.staff['job'], 1)

    def test_shopper_parks_walks_collects_and_drives_home_without_losing_stock(self):
        from test_city_gameplay import neighborhood
        runtime, home, other, cafe, bakery, market = neighborhood()
        self.addCleanup(runtime.close)
        household = runtime.invite_household(home.id, 1, car=True)
        person = runtime.residents[household.members[0]]
        runtime.import_resources(market.id, 'food', 20)
        for i in range(runtime.sites[market.id]['parking_lot'].capacity):
            runtime.fleet.add(FleetVehicle('shop-occupant-'+str(i), 'van', market.id))
        self.assertTrue(runtime.request_shopping(person.id, market.id, target=3))
        self.assertEqual(person.state, 'visiting')
        runtime.update(800)
        self.assertEqual(person.state, 'home')
        self.assertEqual(runtime.fleet.vehicles[person.car_id].site, home.id)
        self.assertEqual(runtime.fleet.vehicles[person.car_id].trips, 2)
        delivered = [e for e in runtime.events if e['event']=='shopping_delivered']
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]['amount'], 3)
        self.assertAlmostEqual(runtime.report()['resource_balance_error'], 0)

    def test_refueling_wakes_a_no_fuel_trip_without_stale_route_rejection(self):
        runtime = city_runtime(CommutePolicy(departure_window=0, parking_walk_seconds=0, fallback_trip_seconds=0))
        self.addCleanup(runtime.close)
        person = worker(runtime)
        runtime.fleet.vehicles[person.car_id].fuel_liters = 0
        runtime.update(1)
        self.assertEqual(runtime.report()['commute_waiting'], 1)
        runtime.refuel_at('a', 5)
        runtime.update(300)
        self.assertEqual(person.state, 'work')

    def test_primary_lot_arrival_still_needs_the_walk_to_the_building(self):
        runtime = self.make_runtime()
        person = worker(runtime)
        vehicle = runtime.fleet.vehicles[person.car_id]
        for _ in range(4000):
            runtime.update(.05)
            if vehicle.trips:
                break
        self.assertEqual(vehicle.phase, 'parked')
        self.assertEqual(person.state, 'commuting')
        self.assertEqual(runtime.workers_arrived, 0)
        runtime.update(100)
        self.assertEqual(person.state, 'work')

    def test_two_buildings_sharing_a_lot_do_not_teleport_the_driver(self):
        runtime = self.make_runtime()
        person = worker(runtime)
        runtime.sites['job']['parking_lot'] = runtime.sites['a']['parking_lot']
        runtime.fleet.rebuild_indexes()
        runtime.parking_trips._options.clear()
        self.assertTrue(runtime._safe_depart(person))
        runtime.update(.1)
        self.assertEqual(person.state, 'commuting')
        vehicle = runtime.fleet.vehicles[person.car_id]
        self.assertEqual(vehicle.site, 'a')
        self.assertEqual(vehicle.trips, 0)


if __name__ == '__main__':
    unittest.main()
