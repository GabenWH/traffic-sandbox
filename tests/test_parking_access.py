"""Finite public parking endpoints remain separate from economic buildings."""
import unittest
from collections import ChainMap
from math import dist

from city import Building, CityMap, Parcel, Terrain
from models import BuildablePhase
from parking import ParkingLot, ParkingSpace, polygons_overlap
import parking_layout
try:
    from parking_access import ParkingAccessIndex
except ImportError:
    ParkingAccessIndex = None


def parking_city(*, road_name='Main [residential]', elevation=0, pedestrian_sides=None):
    city = CityMap(width=1800, height=1000, terrain=Terrain(trees=[]))
    city.add_road([(40, 300), (1700, 300)], road_id='main', name=road_name,
                  elevations=[elevation, elevation], pedestrian_sides=pedestrian_sides)
    sites = {}
    for ident, x, residents in [('home', 180, 4), ('work', 650, 0), ('shop', 1000, 0)]:
        building = Building(ident, Parcel(x, 460, 40, 40), id=ident, residents=residents,
                            jobs=0 if residents else 4, phase=BuildablePhase.OPERATIONAL)
        lot = ParkingLot('lot:'+ident,
            [ParkingSpace('space:'+ident, (x+20, 390), angle=0)],
            surface=[(x, 380), (x+40, 380), (x+40, 400), (x, 400)],
            driveway=[(x+45, 390), (x+45, 300)], road_id='main')
        building.parking_lot_id = lot.id
        city.buildings.append(building)
        city.parcels.append(building.parcel)
        city.parking_lots.append(lot)
        sites[ident] = dict(building=building, parking_lot=lot, parking_capacity=1,
                            road_position=parking_layout.parking_access(city, lot),
                            walk_point=building.parcel.representative_point())
    return city, sites


class ParkingAccessTests(unittest.TestCase):
    def make_index(self, city, sites):
        factory = ParkingAccessIndex
        self.assertIsNotNone(factory, 'Public parking access index is missing')
        return factory(city, sites)

    def test_reuses_public_lots_and_excludes_private_home_capacity(self):
        city, sites = parking_city()
        buildings = list(city.buildings)
        index = self.make_index(city, sites)
        candidates = index.candidates('work')
        candidate_sites = ChainMap(index.sites, sites)
        lots = [candidate_sites[sid]['parking_lot'] for sid in candidates]
        self.assertIn(sites['shop']['parking_lot'], lots)
        self.assertNotIn(sites['home']['parking_lot'], lots)
        self.assertNotIn(sites['work']['parking_lot'], lots)
        self.assertEqual(len({lot.id for lot in lots}), len(lots))
        self.assertIs(next(lot for lot in lots if lot.id == 'lot:shop'), sites['shop']['parking_lot'])
        self.assertEqual(city.buildings, buildings)
        self.assertEqual(set(sites), {'home', 'work', 'shop'})
        self.assertTrue(all('building' not in site for site in index.sites.values()))

    def test_private_access_tag_excludes_nonresidential_overflow(self):
        city, sites = parking_city()
        sites['shop']['building'].source_tags['access'] = 'private'
        index = self.make_index(city, sites)
        candidates = ChainMap(index.sites, sites)
        self.assertFalse(any(candidates[sid]['parking_lot'].id == 'lot:shop'
                             for sid in index.candidates('work')))

    def test_candidates_are_bounded_and_keep_physical_walk_points(self):
        city, sites = parking_city()
        index = self.make_index(city, sites)
        candidates = ChainMap(index.sites, sites)
        target = sites['work']['walk_point']
        selected = index.candidates('work', max_distance=180)
        self.assertTrue(selected)
        self.assertTrue(all(dist(index.walk_point(sid), target) <= 180 for sid in selected))
        self.assertEqual(selected, index.candidates('work', max_distance=180))
        self.assertEqual(index.candidates('missing'), ())
        for sid in selected:
            self.assertEqual(index.walk_point(sid), candidates[sid]['walk_point'])
            self.assertIsNotNone(candidates[sid]['road_position'])

    def test_curb_bays_have_finite_nonoverlapping_spaces_and_access(self):
        city, sites = parking_city()
        index = self.make_index(city, sites)
        curb = [lot for lot in city.parking_lots if lot.id.startswith('curb:')]
        self.assertTrue(curb)
        self.assertTrue(all(0 < lot.capacity <= 6 for lot in curb))
        self.assertTrue(all(space.fits(15, 6) and not space.fits(24, 8)
                            for lot in curb for space in lot.spaces))
        obstacles = [ring for building in city.buildings
                     for ring in parking_layout.building_rings(building)]
        obstacles += [polygon for _, polygon in parking_layout.road_obstacles(city)]
        for lot in curb:
            self.assertTrue(lot.inferred)
            self.assertIsNotNone(parking_layout.parking_access(city, lot))
            self.assertFalse(any(polygons_overlap(lot.surface, polygon) for polygon in obstacles))
            self.assertFalse(any(polygons_overlap(lot.surface, other.surface)
                                 for other in city.parking_lots if other is not lot))
            self.assertFalse(any(polygons_overlap(space.corners, driveway)
                                 for space in lot.spaces for driveway in lot.driveway_surfaces))
        endpoint = next(site for site in index.sites.values()
                        if site['parking_lot'] is curb[0])
        route = city.find_pedestrian_route(endpoint['walk_point'], sites['work']['walk_point'])
        self.assertGreater(route.length, 0)

    def test_curb_bays_are_not_inferred_on_bridges_freeways_or_without_sidewalks(self):
        for kwargs in ({'elevation':40}, {'road_name':'Freeway [motorway]'},
                       {'pedestrian_sides':()}):
            with self.subTest(kwargs=kwargs):
                city, sites = parking_city(**kwargs)
                self.make_index(city, sites)
                self.assertFalse(any(lot.id.startswith('curb:') for lot in city.parking_lots))

    def test_curb_geometry_stays_inside_the_world_at_a_boundary_road(self):
        city, sites = parking_city()
        city.roads[0].centerline = [(40, 20), (1700, 20)]
        city.rebuild_mobility_network()
        self.make_index(city, sites)
        curb = [lot for lot in city.parking_lots if lot.id.startswith('curb:')]
        self.assertTrue(curb)
        self.assertTrue(all(0 <= x <= 1800 and 0 <= y <= 1000
                            for lot in curb for x, y in lot.surface))

    def test_curb_bounds_preserve_negative_projected_coordinates(self):
        city = CityMap(width=1000, height=800, terrain=Terrain(trees=[]))
        city.add_road([(-1000, -500), (-50, -500)], road_id='west')
        building = Building('work', Parcel(-700, -420, 40, 40), id='work', jobs=4)
        city.buildings.append(building)
        city.parcels.append(building.parcel)
        parking_layout.ensure_parking(city)
        lot = city.parking_lots[0]
        sites = {'work': dict(building=building, parking_lot=lot, parking_capacity=lot.capacity,
                             road_position=parking_layout.parking_access(city, lot),
                             walk_point=building.parcel.representative_point())}
        self.make_index(city, sites)
        curb = [lot for lot in city.parking_lots if lot.id.startswith('curb:')]
        self.assertTrue(curb)
        self.assertTrue(any(x < 0 and y < 0 for lot in curb for x, y in lot.surface))
        self.assertTrue(all(-1000 <= x <= 1000 and -500 <= y <= 800
                            for lot in curb for x, y in lot.surface))

    def test_rebuilding_index_preserves_lots_and_claimable_space_ids(self):
        city, sites = parking_city()
        index = self.make_index(city, sites)
        before = [(lot, tuple(space.id for space in lot.spaces)) for lot in city.parking_lots]
        again = self.make_index(city, sites)
        self.assertEqual(len(city.parking_lots), len(before))
        for actual, (original, space_ids) in zip(city.parking_lots, before):
            self.assertIs(actual, original)
            self.assertEqual(tuple(space.id for space in actual.spaces), space_ids)
        self.assertEqual(index.candidates('work'), again.candidates('work'))

    def test_former_public_lot_stays_addressable_after_access_becomes_private(self):
        city, sites = parking_city()
        index = self.make_index(city, sites)
        endpoint = next(sid for sid, site in index.sites.items()
                        if site['parking_lot'].id == 'lot:shop')
        sites['shop']['building'].source_tags['access'] = 'private'
        again = self.make_index(city, sites)
        self.assertIn(endpoint, again.sites)
        self.assertNotIn(endpoint, again.candidates('work'))

    def test_curb_lots_survive_world_serialization_without_a_new_format(self):
        from persistence import world_to_dict, world_from_dict
        city, sites = parking_city()
        self.make_index(city, sites)
        saved = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        loaded = world_from_dict(saved).city_map
        self.assertEqual(loaded.parking_lots, city.parking_lots)

    def test_disconnected_saved_curb_sites_remain_addressable_but_are_not_candidates(self):
        city, sites = parking_city()
        index = self.make_index(city, sites)
        curb_ids = {sid for sid, site in index.sites.items()
                    if site['parking_lot'].id.startswith('curb:')}
        city.roads.clear()
        city.rebuild_mobility_network()
        for site in sites.values():
            site['road_position'] = None
        again = self.make_index(city, sites)
        self.assertTrue(curb_ids <= set(again.sites))
        self.assertFalse(set(again.candidates('work')) & curb_ids)
        self.assertTrue(all(again.sites[sid]['road_position'] is None for sid in curb_ids))


class OverflowParkingPlacementTests(unittest.TestCase):
    def assert_claim_protected(self, incoming):
        from types import SimpleNamespace
        from city_simulation import CitySimulation
        from persistent_fleet import FleetVehicle
        from ui_tools.tools.road_tool import BuildingTool

        city, _ = parking_city()
        runtime = CitySimulation(city)
        self.addCleanup(runtime.close)
        endpoint = next(sid for sid, site in runtime.parking_trips.extra_sites.items()
                        if site['parking_lot'].id.startswith('curb:') and ':left:' in sid)
        lot = runtime.fleet.sites[endpoint]['parking_lot']
        vehicle = FleetVehicle('visitor', 'car', 'home' if incoming else endpoint)
        runtime.fleet.add(vehicle)
        if incoming:
            self.assertTrue(runtime.fleet.dispatch(vehicle.id, endpoint))
        claim = vehicle.reserved_space_id if incoming else vehicle.parking_space_id
        position = lot.space(claim).position
        before_buildings = list(city.buildings)
        before_lots = list(city.parking_lots)
        tool = BuildingTool(SimpleNamespace(city_map=city, redraw_world=lambda: None))
        tool.selected_spec = next(spec for spec in tool.specs if spec.id == 'small_house')

        self.assertIsNone(tool.place_building(position))
        self.assertEqual(city.buildings, before_buildings)
        self.assertEqual(city.parking_lots, before_lots)
        self.assertEqual(vehicle.reserved_space_id if incoming else vehicle.parking_space_id, claim)

    def test_building_placement_protects_occupied_overflow_lot(self):
        self.assert_claim_protected(incoming=False)

    def test_building_placement_protects_reserved_overflow_lot(self):
        self.assert_claim_protected(incoming=True)


class IncrementalCurbTests(unittest.TestCase):
    def initial_street(self):
        from parking_access import ensure_curbside_parking
        city = CityMap(width=7000, height=1000, terrain=Terrain(trees=[]))
        city.add_road([(40, 300), (6900, 300)], road_id='main')
        ensure_curbside_parking(city, [(500, 460)])
        return city

    def test_new_destination_gains_curb_parking_farther_along_existing_road(self):
        from parking_access import ensure_curbside_parking
        city = self.initial_street()
        self.assertFalse(any(dist(space.position, (6000, 460)) <= 1320
                             for lot in city.parking_lots for space in lot.spaces))
        ensure_curbside_parking(city, [(500, 460), (6000, 460)])
        self.assertTrue(any(dist(space.position, (6000, 460)) <= 1320
                            for lot in city.parking_lots for space in lot.spaces))

    def test_incremental_curbs_preserve_claims_and_remain_unique_on_repeated_sync(self):
        from parking_access import ensure_curbside_parking
        from persistent_fleet import FleetVehicle, PersistentFleet
        from transit import TransitSimulation
        city = self.initial_street()
        before = {lot.id: lot for lot in city.parking_lots}
        index = ParkingAccessIndex(city, {})
        fleet = PersistentFleet(TransitSimulation(city), index.sites)
        self.addCleanup(fleet.transit.traffic._discard_native)
        endpoint = next(iter(index.sites))
        vehicle = FleetVehicle('already-parked', 'car', endpoint)
        fleet.add(vehicle)
        claim = vehicle.parking_space_id
        pose = next(fleet.parked_vehicles()).position

        ensure_curbside_parking(city, [(500, 460), (6000, 460)])
        self.assertGreater(len(city.parking_lots), len(before))
        after = {lot.id: lot for lot in city.parking_lots}
        self.assertEqual(len(after), len(city.parking_lots))
        for ident, lot in before.items():
            self.assertIs(after[ident], lot)
        fleet.sites = ParkingAccessIndex(city, {}).sites
        fleet.restore_parking()
        self.assertEqual(vehicle.parking_space_id, claim)
        self.assertEqual(next(fleet.parked_vehicles()).position, pose)
        self.assertFalse(any(polygons_overlap(lot.surface, other.surface)
                             for i, lot in enumerate(city.parking_lots)
                             for other in city.parking_lots[i+1:]))

        ensure_curbside_parking(city, [(500, 460), (6000, 460)])
        self.assertEqual({lot.id for lot in city.parking_lots}, set(after))
        self.assertEqual(len(city.parking_lots), len(after))
