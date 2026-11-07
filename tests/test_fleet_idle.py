"""Idle fleet work follows departures, arrivals, and released parking capacity."""
from collections import deque
from dataclasses import fields
from types import SimpleNamespace
import unittest

from persistent_fleet import FleetVehicle, PersistentFleet
from tests.test_parking import fleet_with_shared_lot


class ObservedVehicle(FleetVehicle):
    """Count reads of persistent state without changing vehicle behavior."""
    reads = 0

    def __getattribute__(self, name):
        if name in ('phase', 'site', 'parking_space_id', 'reserved_space_id'):
            type(self).reads += 1
        return super().__getattribute__(name)


class FleetIdleTests(unittest.TestCase):
    def test_unchanged_parked_fleet_is_not_read_during_observation(self):
        transit = SimpleNamespace(vehicle_arrivals=deque())
        fleet = PersistentFleet(transit, {'home': {'parking_capacity': 1000}})
        for index in range(512):
            fleet.add(ObservedVehicle(str(index), 'car', 'home'))
        fleet.observe()
        ObservedVehicle.reads = 0
        for _ in range(20):
            fleet.observe()
        self.assertEqual(ObservedVehicle.reads, 0)
        self.assertEqual(fleet.parked_at('home'), 512)
        self.assertEqual(ObservedVehicle.reads, 0)

    def test_available_space_does_not_read_unrelated_parked_vehicles(self):
        fleet = fleet_with_shared_lot()
        fleet.add(ObservedVehicle('one', 'car', 'a'))
        fleet.add(ObservedVehicle('two', 'car', 'a'))
        fleet.observe()
        ObservedVehicle.reads = 0
        self.assertEqual(fleet._available_space(FleetVehicle('new', 'car', 'dest'), 'dest'), 'd1')
        self.assertEqual(ObservedVehicle.reads, 0)

    def test_full_lot_waiter_sleeps_until_a_parking_release(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('one', 'car', 'dest'))
        fleet.add(FleetVehicle('two', 'car', 'dest'))
        waiter = ObservedVehicle('waiting', 'car', 'dest', phase='waiting_for_parking')
        fleet.vehicles[waiter.id] = waiter
        fleet.observe()
        self.assertEqual(waiter.phase, 'waiting_for_parking')
        ObservedVehicle.reads = 0
        for _ in range(20):
            fleet.observe()
        self.assertEqual(ObservedVehicle.reads, 0)
        self.assertTrue(fleet.dispatch('one', 'a'))
        fleet.observe()
        self.assertEqual(waiter.phase, 'parked')
        self.assertEqual(waiter.parking_space_id, 'd1')
        self.assertEqual(fleet.parked_at('dest'), 2)

    def test_successful_departure_emits_one_shared_lot_release(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('one', 'car', 'a'))
        fleet.add(FleetVehicle('two', 'car', 'b'))
        self.assertEqual(fleet.drain_parking_changes(), set())
        self.assertTrue(fleet.dispatch('one', 'dest'))
        self.assertEqual(fleet.drain_parking_changes(), {('lot', 'shared')})
        self.assertFalse(fleet.dispatch('two', 'dest'))
        self.assertEqual(fleet.last_dispatch_status, 'blocked')
        self.assertEqual(fleet.drain_parking_changes(), set())
        fleet.transit.update(100)
        fleet.observe()
        self.assertEqual(fleet.drain_parking_changes(), set())

    def test_count_only_sites_reserve_capacity_for_inbound_vehicles(self):
        fleet = fleet_with_shared_lot()
        fleet.sites['dest'].pop('parking_lot')
        fleet.sites['dest']['parking_capacity'] = 1
        fleet.add(FleetVehicle('one', 'car', 'a'))
        fleet.add(FleetVehicle('two', 'car', 'b'))
        self.assertTrue(fleet.dispatch('one', 'dest'))
        fleet.transit.update(2)
        self.assertFalse(fleet.dispatch('two', 'dest'))
        self.assertEqual(fleet.last_dispatch_status, 'full')
        self.assertEqual(fleet.parked_at('dest'), 0)
        fleet.transit.update(100)
        fleet.observe()
        self.assertEqual(fleet.parked_at('dest'), 1)

    def test_reserved_arrival_does_not_report_a_count_only_capacity_release(self):
        fleet = fleet_with_shared_lot()
        fleet.sites['dest'].pop('parking_lot')
        fleet.sites['dest']['parking_capacity'] = 1
        fleet.add(FleetVehicle('one', 'car', 'a'))
        self.assertTrue(fleet.dispatch('one', 'dest'))
        fleet.drain_parking_changes()
        fleet.transit.update(100)
        fleet.observe()
        self.assertEqual(fleet.parked_at('dest'), 1)
        self.assertEqual(fleet.drain_parking_changes(), set())

    def test_changed_claims_and_rebinding_can_rebuild_indexes(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('one', 'car', 'a'))
        self.assertTrue(fleet.dispatch('one', 'dest'))
        vehicle = fleet.vehicles['one']
        vehicle.reserved_space_id = None
        # Existing callers edit fields directly; the next claim query must see it.
        self.assertEqual(fleet._available_space(FleetVehicle('new', 'car', 'dest'), 'dest'), 'd1')
        vehicle.phase, vehicle._actor = 'parked', None
        fleet.rebuild_indexes()
        fleet.observe()
        self.assertEqual(fleet.parked_at('a'), 0)
        self.assertEqual(fleet.parked_at('dest'), 0)

    def test_capacity_change_wakes_a_waiter_without_polling_other_lots(self):
        fleet = PersistentFleet(SimpleNamespace(vehicle_arrivals=deque()), {
            'home': {'parking_capacity': 1}, 'work': {'parking_capacity': 0}})
        fleet.add(FleetVehicle('one', 'car', 'home'))
        waiter = FleetVehicle('waiting', 'car', 'work', phase='waiting_for_parking')
        fleet.vehicles[waiter.id] = waiter
        fleet.observe()
        fleet.sites['work']['parking_capacity'] = 1
        fleet.notify_parking_changed('work')
        fleet.observe()
        self.assertEqual(waiter.phase, 'parked')
        self.assertEqual(fleet.parked_at('work'), 1)
        self.assertEqual(fleet.drain_parking_changes(), {('site', 'work')})

    def test_failed_access_and_fuel_have_explicit_dispatch_status(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('one', 'car', 'a', fuel_liters=0))
        self.assertFalse(fleet.dispatch('one', 'dest'))
        self.assertEqual(fleet.last_dispatch_status, 'no_fuel')
        fleet.sites['dest']['road_position'] = None
        self.assertFalse(fleet.dispatch('one', 'dest'))
        self.assertEqual(fleet.last_dispatch_status, 'inaccessible')


class FleetRoadStopTests(unittest.TestCase):
    def parked_truck(self):
        fleet = fleet_with_shared_lot()
        self.addCleanup(fleet.transit.traffic._discard_native)
        vehicle = FleetVehicle('truck', 'truck', 'a', length=24, width=8, capacity=10)
        fleet.add(vehicle)
        self.assertTrue(fleet.dispatch(vehicle.id, 'dest'),
                        'A truck destination with no fitting bay needs a physical road stop')
        fleet.transit.update(100)
        fleet.observe()
        return fleet, vehicle

    def add_downstream(self, fleet):
        from mobility import nearest_lane_position
        from parking import ParkingLot, ParkingSpace
        lot = ParkingLot('downstream', [ParkingSpace('car-bay', (800, 100)),
                                       ParkingSpace('truck-bay', (814, 100), length=30, width=12)])
        lane = fleet.transit.city.roads[0].lanes[0]
        fleet.sites['downstream'] = dict(parking_lot=lot, parking_capacity=2,
            road_position=nearest_lane_position(lane, (800, 30))[0])

    def test_truck_without_fitting_bay_arrives_at_exact_road_stop(self):
        fleet, vehicle = self.parked_truck()
        self.assertEqual(vehicle.phase, 'parked')
        self.assertEqual(vehicle.site, 'dest')
        self.assertIsNone(vehicle.parking_space_id)
        self.assertIsNone(vehicle.reserved_space_id)
        self.assertIsNone(vehicle.reserved_road_stop_lane_id)
        self.assertIsNone(vehicle.reserved_road_stop_distance)
        self.assertIsNotNone(vehicle.road_stop_lane_id)
        self.assertEqual(fleet.parked_at('dest'), 0)
        self.assertEqual(len(fleet.transit.traffic.cars), 0)
        pose = next(fleet.parked_vehicles())
        self.assertEqual(pose.position[0], 600)
        self.assertEqual(pose.heading, (1.0, 0.0))
        self.assertEqual(pose.position, vehicle.road_stop_position)

    def test_fitting_occupied_bay_keeps_truck_at_origin(self):
        from parking import ParkingLot, ParkingSpace
        fleet = fleet_with_shared_lot()
        self.addCleanup(fleet.transit.traffic._discard_native)
        lot = ParkingLot('delivery', [ParkingSpace('bay', (600, 100), length=30, width=12)])
        fleet.sites['dest'].update(parking_lot=lot, parking_capacity=1)
        fleet.add(FleetVehicle('occupant', 'truck', 'dest', length=24, width=8))
        fleet.add(FleetVehicle('truck', 'truck', 'a', length=24, width=8))
        self.assertFalse(fleet.dispatch('truck', 'dest'))
        self.assertEqual(fleet.last_dispatch_status, 'full')
        self.assertEqual(fleet.vehicles['truck'].parking_space_id, 'truck')

    def test_lane_stop_blocks_followers_and_departure_consumes_it(self):
        fleet, vehicle = self.parked_truck()
        self.add_downstream(fleet)
        fleet.add(FleetVehicle('following', 'car', 'a'))
        self.assertTrue(fleet.dispatch('following', 'downstream'))
        fleet.transit.update(60)
        fleet.observe()
        follower = fleet.vehicles['following']
        self.assertEqual(follower.phase, 'driving')
        self.assertLessEqual(follower._actor.position[0], 576.500001)
        self.assertEqual(follower._actor.speed, 0)
        stopped = vehicle.road_stop_position
        self.assertTrue(fleet.dispatch('truck', 'downstream'))
        self.assertEqual(vehicle._actor.position, stopped)
        self.assertEqual(vehicle._actor.speed, 0)
        self.assertIsNone(vehicle.road_stop_lane_id)
        fleet.transit.update(80)
        fleet.observe()
        self.assertEqual(vehicle.parking_space_id, 'truck-bay')
        self.assertEqual(follower.parking_space_id, 'car-bay')

    def test_restore_reinstates_road_stop_and_cargo(self):
        from transit import TransitSimulation
        fleet, vehicle = self.parked_truck()
        vehicle.cargo['wood'] = 7
        saved = {field.name: getattr(vehicle, field.name)
                 for field in fields(vehicle) if not field.name.startswith('_')}
        restored = PersistentFleet(TransitSimulation(fleet.transit.city), fleet.sites)
        self.addCleanup(restored.transit.traffic._discard_native)
        restored.vehicles['truck'] = FleetVehicle(**saved)
        restored.restore_parking()
        restored.restore_road_stops()
        self.add_downstream(restored)
        restored.add(FleetVehicle('following', 'car', 'a'))
        self.assertTrue(restored.dispatch('following', 'downstream'))
        restored.transit.update(60)
        restored.observe()
        self.assertEqual(restored.vehicles['truck'].cargo, {'wood': 7})
        self.assertEqual(restored.vehicles['following'].phase, 'driving')
        self.assertEqual(restored.vehicles['following']._actor.speed, 0)
        self.assertEqual(next(restored.parked_vehicles()).position, vehicle.road_stop_position)

    def test_removed_lane_preserves_a_suspended_truck_pose(self):
        from transit import TransitSimulation
        fleet, vehicle = self.parked_truck()
        stopped = vehicle.road_stop_position
        saved = {field.name: getattr(vehicle, field.name)
                 for field in fields(vehicle) if not field.name.startswith('_')}
        fleet.transit.city.remove_road(fleet.transit.city.roads[0])
        restored = PersistentFleet(TransitSimulation(fleet.transit.city), fleet.sites)
        self.addCleanup(restored.transit.traffic._discard_native)
        restored.vehicles['truck'] = FleetVehicle(**saved)
        restored.restore_parking()
        restored.restore_road_stops()
        self.assertEqual(next(restored.parked_vehicles()).position, stopped)
        self.assertFalse(restored.dispatch('truck', 'a'))
        self.assertEqual(restored.last_dispatch_status, 'inaccessible')
        self.assertEqual(restored.vehicles['truck'].road_stop_position, stopped)

    def test_stopped_truck_cannot_also_hold_an_offstreet_reservation(self):
        fleet, vehicle = self.parked_truck()
        vehicle.destination, vehicle.reserved_space_id = 'a', 'truck'
        with self.assertRaisesRegex(ValueError, 'Road stop'):
            fleet.restore_parking()

    def corner_delivery(self):
        from city import CityMap, Terrain
        from mobility import lane_position_at_distance
        from parking import ParkingLot, ParkingSpace
        from transit import TransitSimulation
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 100), (500, 100), (500, 600)])
        lane = road.lanes[0]
        from math import dist
        corner = dist(lane.points[0], lane.points[1])
        origin = ParkingLot('origin', [ParkingSpace('origin-bay', (100, 180), length=30, width=12)])
        target = ParkingLot('target', [ParkingSpace('small', (600, 180))])
        onward = ParkingLot('onward', [ParkingSpace('onward-bay', (600, 400), length=30, width=12)])
        sites = {key: dict(parking_lot=lot, parking_capacity=1,
                          road_position=lane_position_at_distance(lane, distance))
                 for key, lot, distance in (('origin', origin, 100),
                                            ('corner', target, corner), ('onward', onward, corner+200))}
        fleet = PersistentFleet(TransitSimulation(city), sites)
        self.addCleanup(fleet.transit.traffic._discard_native)
        truck = FleetVehicle('truck', 'truck', 'origin', length=24, width=8)
        fleet.add(truck)
        self.assertTrue(fleet.dispatch('truck', 'corner'))
        fleet.transit.update(60)
        fleet.observe()
        return fleet, truck, lane, corner

    def test_safe_loading_stop_near_corner_restores_at_the_same_position(self):
        from math import dist
        from transit import TransitSimulation
        fleet, truck, _, corner = self.corner_delivery()
        self.assertGreaterEqual(abs(truck.road_stop_distance-corner), truck.length/2+4-1e-7)
        saved = {field.name: getattr(truck, field.name)
                 for field in fields(truck) if not field.name.startswith('_')}
        restored = PersistentFleet(TransitSimulation(fleet.transit.city), fleet.sites)
        self.addCleanup(restored.transit.traffic._discard_native)
        restored.vehicles['truck'] = FleetVehicle(**saved)
        restored.restore_parking()
        restored.restore_road_stops()
        self.assertEqual(next(restored.parked_vehicles()).heading, truck.road_stop_heading)
        self.assertTrue(restored.dispatch('truck', 'onward'))
        self.assertLess(dist(restored.vehicles['truck']._actor.position, truck.road_stop_position), 1e-7)

    def test_unsafe_saved_corner_pose_stays_suspended_without_a_native_blocker(self):
        from mobility import lane_position_at_distance
        from transit import TransitSimulation
        from truck_stops import LaneObstacle
        fleet, truck, lane, corner = self.corner_delivery()
        unsafe = LaneObstacle(truck.id, lane_position_at_distance(lane, corner), truck.length, truck.width)
        saved = {field.name: getattr(truck, field.name)
                 for field in fields(truck) if not field.name.startswith('_')}
        saved.update(road_stop_distance=corner, road_stop_position=unsafe.position,
                     road_stop_heading=unsafe.heading)
        restored = PersistentFleet(TransitSimulation(fleet.transit.city), fleet.sites)
        self.addCleanup(restored.transit.traffic._discard_native)
        restored.vehicles['truck'] = FleetVehicle(**saved)
        restored.restore_parking()
        restored.restore_road_stops()
        self.assertEqual(next(restored.parked_vehicles()).position, unsafe.position)
        self.assertFalse(restored.dispatch('truck', 'onward'))
        self.assertEqual(restored.last_dispatch_status, 'inaccessible')
        route = restored.transit.city.find_vehicle_route_between(unsafe.lane_position,
            lane_position_at_distance(lane, corner+200))
        self.assertIsNotNone(restored.transit.traffic.admit_route(route, vehicle_id='passing',
            source_id='corner', destination_id='onward', length=14, width=6))


if __name__ == '__main__':
    unittest.main()
