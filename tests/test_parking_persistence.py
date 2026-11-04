"""Parking geometry and claims survive normal gameplay/world saves."""
import copy
import json
import unittest

from city_simulation import CitySimulation
from persistent_fleet import FleetVehicle
from persistence import WorldFormatError, world_to_dict, world_from_dict
from tests.test_parking_layout import block_city


def encode(city):
    return json.loads(json.dumps(world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)))


class ParkingPersistenceTests(unittest.TestCase):
    def test_runtime_uses_one_shared_lot_capacity_and_keeps_it_on_restore(self):
        city = block_city()
        runtime = CitySimulation(city)
        a, b, c = city.buildings
        self.assertIsNotNone(a.parking_lot_id)
        self.assertIs(runtime.sites[a.id]['parking_lot'], runtime.sites[b.id]['parking_lot'])
        runtime.fleet.add(FleetVehicle('one', 'car', a.id))
        runtime.fleet.add(FleetVehicle('two', 'car', b.id))
        saved = encode(city)
        self.assertTrue(saved['world']['parking_lots'])
        restored_city = world_from_dict(saved).city_map
        restored = CitySimulation(restored_city)
        self.assertEqual(restored.fleet.parked_at(a.id), 2)
        self.assertEqual(restored.fleet.vehicles['one'].parking_space_id,
                         runtime.fleet.vehicles['one'].parking_space_id)
        self.assertEqual(restored_city.buildings[0].category, a.category)
        self.assertEqual(restored_city.parking_lots, city.parking_lots)

    def test_save_rejects_duplicate_space_claims_and_missing_lot_references(self):
        city = block_city()
        runtime = CitySimulation(city)
        runtime.fleet.add(FleetVehicle('one', 'car', 'a'))
        runtime.fleet.add(FleetVehicle('two', 'car', 'b'))
        saved = encode(city)
        corrupt = copy.deepcopy(saved)
        corrupt['gameplay']['fleet'][1]['parking_space_id'] = corrupt['gameplay']['fleet'][0]['parking_space_id']
        with self.assertRaisesRegex(ValueError, '[Pp]arking'):
            CitySimulation(world_from_dict(corrupt).city_map)
        corrupt = copy.deepcopy(saved)
        corrupt['world']['buildings'][0]['parking_lot_id'] = 'missing'
        with self.assertRaisesRegex(WorldFormatError, 'parking lot'):
            world_from_dict(corrupt)
        corrupt = copy.deepcopy(saved)
        corrupt['gameplay']['fleet'][0]['parking_space_id'] = None
        with self.assertRaisesRegex(ValueError, '[Pp]arking'):
            CitySimulation(world_from_dict(corrupt).city_map)

    def test_older_worlds_gain_parking_without_losing_building_shapes(self):
        city = block_city()
        saved = encode(city)
        saved['version'] = 9
        saved['world'].pop('parking_lots', None)
        for b in saved['world']['buildings']:
            b.pop('parking_lot_id', None)
            b.pop('category', None)
            b.pop('source_tags', None)
        loaded = world_from_dict(saved).city_map
        CitySimulation(loaded)
        self.assertEqual(len(loaded.buildings), 3)
        self.assertTrue(all(b.parking_lot_id for b in loaded.buildings))
        self.assertTrue(all(l.capacity >= 2 for l in loaded.parking_lots))

    def test_active_reservations_survive_saves_and_repeated_road_rebinding(self):
        city = block_city()
        runtime = CitySimulation(city)
        runtime.fleet.add(FleetVehicle('van', 'van', 'a'))
        self.assertTrue(runtime.fleet.dispatch('van', 'c'))
        reservation = runtime.fleet.vehicles['van'].reserved_space_id
        restored = CitySimulation(world_from_dict(encode(city)).city_map)
        self.assertEqual(restored.fleet.vehicles['van'].reserved_space_id, reservation)
        for _ in range(2):
            restored.city.rebuild_mobility_network()
            restored.sync_network()
        restored.update(120)
        self.assertEqual(restored.fleet.vehicles['van'].site, 'c')
        self.assertEqual(restored.fleet.vehicles['van'].phase, 'parked')
        self.assertEqual(restored.fleet.vehicles['van'].parking_space_id, reservation)
        self.assertIsNone(restored.fleet.vehicles['van'].reserved_space_id)

    def test_full_parking_rejection_does_not_partly_create_a_household(self):
        from city import Building,CityMap,Parcel,Terrain
        from models import BuildablePhase
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(20,30),(900,30)])
        home = Building('Home',Parcel(200,90,40,40),residents=4,id='home',phase=BuildablePhase.OPERATIONAL)
        city.buildings.append(home);city.parcels.append(home.parcel)
        runtime = CitySimulation(city)
        for _ in range(3):runtime.invite_household('home',1,car=True)
        with self.assertRaisesRegex(ValueError,'parking space'):
            runtime.invite_household('home',1,car=True)
        self.assertEqual(len(runtime.residents),3)
        self.assertEqual(len(runtime.households),3)

    def test_legacy_inflight_vehicle_waits_without_displacing_parked_cars(self):
        city = block_city()
        runtime = CitySimulation(city)
        runtime.fleet.add(FleetVehicle('incoming','van','a'))
        self.assertTrue(runtime.fleet.dispatch('incoming','c'))
        # Version 9 had no reservation, and could dispatch toward a full site.
        runtime.fleet.vehicles['incoming'].reserved_space_id = None
        for i in range(3):runtime.fleet.add(FleetVehicle(f'present-{i}','van','c'))
        old = encode(city)
        old['version'] = 9
        old['world'].pop('parking_lots')
        for b in old['world']['buildings']:b.pop('parking_lot_id')
        for vehicle in old['gameplay']['fleet']:
            vehicle.pop('parking_space_id');vehicle.pop('reserved_space_id')
        restored = CitySimulation(world_from_dict(old).city_map)
        self.assertEqual(restored.fleet.parked_at('c'),3)
        # A migrated in-flight vehicle without a reservation remains saveable.
        restored = CitySimulation(world_from_dict(encode(restored.city)).city_map)
        restored.update(100)
        self.assertEqual(restored.fleet.vehicles['incoming'].phase,'waiting_for_parking')
        self.assertEqual(restored.fleet.parked_at('c'),3)
        self.assertTrue(restored.fleet.dispatch('present-0','a'))
        restored.update(.05)
        self.assertEqual(restored.fleet.vehicles['incoming'].phase,'parked')
        self.assertEqual(restored.fleet.parked_at('c'),3)
