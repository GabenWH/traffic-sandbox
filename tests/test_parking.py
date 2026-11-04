"""Physical spaces, shared capacity, and persistent vehicle identity."""
import unittest
from types import SimpleNamespace

from city import Building, CityMap, Parcel, Terrain, ZoneType
from persistent_fleet import FleetVehicle, PersistentFleet


class ParkingModelTests(unittest.TestCase):
    def test_buildings_have_three_way_categories_even_without_authored_zones(self):
        home = Building('Home', Parcel(10, 10, 20, 20), residents=4)
        factory = Building('Factory', Parcel(50, 10, 20, 20), operation={'role': 'factory'})
        clinic = Building('Clinic', Parcel(90, 10, 20, 20, ZoneType.CIVIC))
        self.assertEqual(getattr(home, 'category', None), ZoneType.RESIDENTIAL)
        self.assertEqual(factory.category, ZoneType.INDUSTRIAL)
        self.assertEqual(clinic.category, ZoneType.COMMERCIAL)

    def test_space_geometry_fits_vehicles_and_rejects_overlapping_stalls(self):
        from parking import ParkingLot, ParkingSpace, polygons_overlap
        a = ParkingSpace('a', (100, 100), angle=0, length=20, width=10)
        b = ParkingSpace('b', (100, 112), angle=0, length=20, width=10)
        self.assertTrue(a.fits(15, 6))
        self.assertFalse(a.fits(24, 8))
        self.assertFalse(polygons_overlap(a.corners, b.corners))
        self.assertEqual(ParkingLot('lot', [a, b]).capacity, 2)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            ParkingLot('invalid', [a, ParkingSpace('c', (100, 105))])


def fleet_with_shared_lot():
    from parking import ParkingLot, ParkingSpace
    lot = ParkingLot('shared', [ParkingSpace('s1', (100, 100)),
                               ParkingSpace('s2', (112, 100)),
                               ParkingSpace('truck', (126, 100), length=30, width=12)])
    other = ParkingLot('other', [ParkingSpace('d1', (600, 100)),
                                ParkingSpace('d2', (612, 100))])
    city = CityMap(terrain=Terrain(trees=[]))
    road = city.add_road([(20, 30), (900, 30)])
    from mobility import nearest_lane_position
    def site(lot, point):
        return dict(parking_lot=lot, parking_capacity=lot.capacity,
                    road_position=nearest_lane_position(road.lanes[0], point)[0])
    sites = {'a': site(lot, (100, 30)), 'b': site(lot, (100, 30)),
             'dest': site(other, (600, 30))}
    from transit import TransitSimulation
    transit = TransitSimulation(city)
    return PersistentFleet(transit, sites)


class SharedFleetTests(unittest.TestCase):
    def test_different_buildings_share_capacity_and_car_poses_do_not_overlap(self):
        from parking import polygons_overlap, oriented_rectangle
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('c1', 'car', 'a'))
        fleet.add(FleetVehicle('c2', 'car', 'b'))
        fleet.add(FleetVehicle('t', 'truck', 'a', length=24, width=8))
        self.assertEqual(fleet.parked_at('a'), 3)
        self.assertEqual(fleet.parked_at('b'), 3)
        with self.assertRaisesRegex(ValueError, 'parking space'):
            fleet.add(FleetVehicle('overflow', 'car', 'b'))
        vehicles = list(fleet.parked_vehicles())
        self.assertEqual(len(vehicles), 3)
        polygons = [oriented_rectangle(v.position, v.heading, v.length, v.width) for v in vehicles]
        self.assertFalse(any(polygons_overlap(a, b) for i, a in enumerate(polygons) for b in polygons[i+1:]))
        self.assertEqual(fleet.vehicles['t'].parking_space_id, 'truck')

    def test_full_destination_does_not_release_origin_or_start_traffic(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('c', 'car', 'a'))
        fleet.add(FleetVehicle('d1', 'car', 'dest'))
        fleet.add(FleetVehicle('d2', 'car', 'dest'))
        space = fleet.vehicles['c'].parking_space_id
        self.assertFalse(fleet.dispatch('c', 'dest'))
        self.assertEqual(fleet.vehicles['c'].parking_space_id, space)
        self.assertEqual(fleet.vehicles['c'].phase, 'parked')
        self.assertIsNone(fleet.vehicles['c'].reserved_space_id)

    def test_native_spawn_rejection_keeps_origin_and_does_not_reserve_destination(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('first', 'car', 'a'))
        fleet.add(FleetVehicle('second', 'car', 'b'))
        self.assertTrue(fleet.dispatch('first', 'dest'))
        second = fleet.vehicles['second']
        space = second.parking_space_id
        self.assertFalse(fleet.dispatch('second', 'dest'))
        self.assertEqual(second.parking_space_id, space)
        self.assertIsNone(second.reserved_space_id)

    def test_native_trip_reserves_a_distinct_space_until_arrival(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('c1', 'car', 'a'))
        fleet.add(FleetVehicle('c2', 'car', 'b'))
        self.assertTrue(fleet.dispatch('c1', 'dest'))
        for _ in range(30):
            fleet.transit.update(.05)
            fleet.observe()
        self.assertTrue(fleet.dispatch('c2', 'dest'))
        one, two = fleet.vehicles.values()
        self.assertIsNone(one.parking_space_id)
        self.assertNotEqual(one.reserved_space_id, two.reserved_space_id)
        for _ in range(2000):
            fleet.transit.update(.05)
            fleet.observe()
            if one.phase == two.phase == 'parked': break
        self.assertEqual((one.site, two.site), ('dest', 'dest'))
        self.assertEqual(fleet.parked_at('dest'), 2)
        self.assertEqual(len({one.parking_space_id, two.parking_space_id}), 2)

    def test_waiting_vehicle_cannot_take_a_reservation_during_its_arrival(self):
        fleet = fleet_with_shared_lot()
        fleet.vehicles['waiting'] = FleetVehicle('waiting','car','dest',phase='waiting_for_parking')
        fleet.add(FleetVehicle('occupant','car','dest'))
        fleet.add(FleetVehicle('arriving','car','a'))
        self.assertTrue(fleet.dispatch('arriving','dest'))
        fleet.transit.update(100)
        fleet.observe()
        self.assertEqual(fleet.vehicles['arriving'].phase,'parked')
        self.assertEqual(fleet.vehicles['waiting'].phase,'waiting_for_parking')
        self.assertEqual(fleet.parked_at('dest'),2)

    def test_move_between_buildings_in_same_lot_keeps_space(self):
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('c', 'car', 'a'))
        space = fleet.vehicles['c'].parking_space_id
        self.assertTrue(fleet.dispatch('c', 'b'))
        self.assertEqual(fleet.vehicles['c'].site, 'b')
        self.assertEqual(fleet.vehicles['c'].parking_space_id, space)
        self.assertEqual(fleet.arrivals, ['c'])
        self.assertEqual(len(fleet.transit.traffic.vehicles), 0)
