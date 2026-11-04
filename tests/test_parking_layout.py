"""Lots use source footprints, and grouping never invents property boundaries."""
import json
import tempfile
import unittest
from pathlib import Path

from city import Building, CityMap, Parcel, Terrain, ZoneType
from models import BuildablePhase
from parking import polygons_overlap


def block_city():
    city = CityMap(width=1000, height=800, terrain=Terrain(trees=[]))
    city.add_road([(20, 100), (950, 100)])
    for ident, x in [('a', 200), ('b', 241), ('c', 600)]:
        parcel = Parcel(x, 170, 40, 40)
        building = Building(ident, parcel, id=ident, residents=4,
                            phase=BuildablePhase.OPERATIONAL)
        city.parcels.append(parcel)
        city.buildings.append(building)
    return city


class ParkingLayoutTests(unittest.TestCase):
    def test_touching_buildings_share_one_inferred_lot_with_distinct_spaces(self):
        from parking_layout import ensure_parking, building_rings, road_obstacles
        city = block_city()
        ensure_parking(city)
        a, b, c = city.buildings
        self.assertEqual(a.parking_lot_id, b.parking_lot_id)
        self.assertNotEqual(a.parking_lot_id, c.parking_lot_id)
        lot = next(l for l in city.parking_lots if l.id == a.parking_lot_id)
        self.assertTrue(lot.inferred)
        self.assertGreaterEqual(lot.capacity, 4)
        self.assertTrue(lot.road_id)
        self.assertFalse(any(polygons_overlap(s.corners, drive) for current in city.parking_lots
                             for s in current.spaces for drive in current.driveway_surfaces))
        obstacles = [ring for building in city.buildings for ring in building_rings(building)]
        obstacles += [polygon for _, polygon in road_obstacles(city)]
        for i, other in enumerate(city.parking_lots):
            self.assertFalse(any(polygons_overlap(other.surface, ring) for ring in obstacles))
            self.assertFalse(any(polygons_overlap(other.surface, neighbor.surface)
                                 for neighbor in city.parking_lots[i+1:]))
        before = [(lot.id, [s.position for s in lot.spaces]) for lot in city.parking_lots]
        ensure_parking(city)
        self.assertEqual(before, [(lot.id, [s.position for s in lot.spaces]) for lot in city.parking_lots])

    def test_matching_address_shares_capacity_but_separate_houses_do_not_merge(self):
        from parking_layout import ensure_parking
        city = block_city()
        city.buildings[1].parcel.x = 310
        city.buildings[0].source_tags = city.buildings[1].source_tags = {
            'addr:street': 'Main Street', 'addr:housenumber': '10'}
        ensure_parking(city)
        self.assertEqual(city.buildings[0].parking_lot_id, city.buildings[1].parking_lot_id)
        self.assertNotEqual(city.buildings[1].parking_lot_id, city.buildings[2].parking_lot_id)

    def test_dispersed_source_group_can_access_a_road_near_either_member(self):
        from parking_layout import ensure_parking
        city=CityMap(width=2500,height=1500,terrain=Terrain(trees=[]))
        city.add_road([(20,20),(20,1450)],road_id='access')
        for ident,x in [('near',100),('far',2100)]:
            city.buildings.append(Building(ident,Parcel(x,500,40,40),id=ident,residents=4,
                                           source_tags={'parking:group':'site'}))
        ensure_parking(city)
        self.assertEqual(len(city.parking_lots),1)
        self.assertEqual(city.parking_lots[0].road_id,'access')
        self.assertTrue(city.parking_lots[0].driveway)

    def test_building_spawner_assigns_category_and_physical_parking(self):
        from types import SimpleNamespace
        from ui_tools.tools.road_tool import BuildingTool
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(20, 30), (4500, 30)])
        tool = BuildingTool(SimpleNamespace(city_map=city, redraw_world=lambda: None))
        for template, x, category in [('small_house', 300, ZoneType.RESIDENTIAL),
                                      ('cafe', 700, ZoneType.COMMERCIAL),
                                      ('farm', 1000, ZoneType.INDUSTRIAL)]:
            tool.selected_spec = next(s for s in tool.specs if s.id == template)
            building = tool.place_building((x, 140))
            self.assertEqual(building.category, category)
            self.assertIsNotNone(building.parking_lot_id)
            lot = next(l for l in city.parking_lots if l.id == building.parking_lot_id)
            self.assertGreaterEqual(lot.capacity, 2)

    def test_new_building_cannot_overwrite_occupied_parking(self):
        from types import SimpleNamespace
        from ui_tools.tools.road_tool import BuildingTool
        city = CityMap(terrain=Terrain(trees=[]))
        tool = BuildingTool(SimpleNamespace(city_map=city,redraw_world=lambda:None))
        first = tool.place_building((300,300))
        from city_simulation import CitySimulation
        from persistent_fleet import FleetVehicle
        runtime = CitySimulation(city)
        runtime.fleet.add(FleetVehicle('parked','car',first.id))
        lot = next(l for l in city.parking_lots if l.id == first.parking_lot_id)
        point = lot.spaces[0].position
        self.assertIsNone(tool.place_building(point))
        self.assertEqual(len(city.buildings),1)

    def test_new_building_can_replan_empty_inferred_parking_without_overlaps(self):
        from types import SimpleNamespace
        from ui_tools.tools.road_tool import BuildingTool
        from parking_layout import building_rings
        city = CityMap(terrain=Terrain(trees=[]))
        tool = BuildingTool(SimpleNamespace(city_map=city,redraw_world=lambda:None))
        first = tool.place_building((300,300))
        point = city.parking_lots[0].spaces[0].position
        second = tool.place_building(point)
        self.assertIsNotNone(second)
        self.assertEqual(len(city.buildings),2)
        self.assertTrue(all(not polygons_overlap(l.surface,p) for l in city.parking_lots if l.surface
                            for b in city.buildings for p in building_rings(b)))

    def test_osm_purpose_and_source_group_are_retained(self):
        from tools.osm_buildings import import_osm_homes
        city = CityMap(width=1500, height=800, terrain=Terrain(trees=[]))
        city.add_road([(20, 100), (1400, 100)])
        elements = []
        for ident, x, purpose in [(1, 200, 'house'), (2, 260, 'commercial'), (3, 700, 'industrial')]:
            ring = [(x, 200), (x+40, 200), (x+40, 240), (x, 240), (x, 200)]
            elements.append(dict(type='way', id=ident, tags={'building': purpose},
                                 geometry=[dict(lon=x, lat=y) for x,y in ring]))
        elements.append(dict(type='relation', id=50, tags={'type': 'site'},
                             members=[dict(type='way', ref=i, role='') for i in (1, 2)]))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'buildings.json'
            source.write_text(json.dumps({'elements': elements}))
            stats = import_osm_homes(city, [source], lambda p: True, lambda p: p)
        self.assertEqual([b.category for b in city.buildings],
                         [ZoneType.RESIDENTIAL, ZoneType.COMMERCIAL, ZoneType.INDUSTRIAL])
        self.assertEqual([b.residents for b in city.buildings], [4, 0, 0])
        self.assertEqual(stats['imported_buildings'], 3)
        self.assertEqual(stats['imported_homes'], 1)
        self.assertEqual(city.buildings[0].parking_lot_id, city.buildings[1].parking_lot_id)
        self.assertEqual(city.buildings[2].source_tags['building'], 'industrial')

    def test_no_room_reports_zero_capacity_instead_of_overlapping_a_building(self):
        from parking_layout import ensure_parking
        city = CityMap(width=60, height=60, terrain=Terrain(trees=[]))
        city.buildings.append(Building('Full', Parcel(0, 0, 60, 60), residents=4))
        ensure_parking(city)
        self.assertEqual(len(city.parking_lots), 1)
        self.assertEqual(city.parking_lots[0].capacity, 0)
        self.assertIsNone(city.parking_lots[0].road_id)

    def test_projected_maps_support_negative_world_coordinates(self):
        from parking_layout import ensure_parking
        city = CityMap(width=1000, height=800, terrain=Terrain(trees=[]))
        city.add_road([(-1000, -500), (-50, -500)])
        city.buildings.append(Building('West', Parcel(-700, -420, 40, 40), residents=4))
        ensure_parking(city)
        self.assertGreaterEqual(city.parking_lots[0].capacity, 2)
        self.assertTrue(city.parking_lots[0].road_id)

    def test_driveway_connects_to_a_ground_level_vehicle_road(self):
        from parking_layout import ensure_parking,parking_access
        city = CityMap(width=1000,height=800,terrain=Terrain(trees=[]))
        city.add_road([(20,30),(950,30)],road_id='motor')
        city.add_pedestrian_path([(20,100),(950,100)],road_id='foot')
        city.buildings.append(Building('Home',Parcel(200,170,40,40),residents=4))
        ensure_parking(city)
        self.assertEqual(city.parking_lots[0].road_id,'motor')
        self.assertIsNotNone(parking_access(city,city.parking_lots[0]))

    def test_ground_parking_does_not_claim_access_to_an_elevated_bridge(self):
        from parking_layout import ensure_parking,parking_access
        city = CityMap(width=1000,height=800,terrain=Terrain(trees=[]))
        city.add_road([(20,100),(950,100)],road_id='bridge',elevations=[40,40])
        city.buildings.append(Building('Home',Parcel(200,170,40,40),residents=4))
        ensure_parking(city)
        self.assertIsNone(city.parking_lots[0].road_id)
        self.assertIsNone(parking_access(city,city.parking_lots[0]))

    def test_road_cannot_be_drawn_through_occupied_parking(self):
        from city_simulation import CitySimulation
        from persistent_fleet import FleetVehicle
        city = block_city()
        runtime = CitySimulation(city)
        runtime.fleet.add(FleetVehicle('parked','car','a'))
        vehicle = next(runtime.fleet.parked_vehicles())
        x,y = vehicle.position
        revision,roads = city.mobility_revision,list(city.roads)
        with self.assertRaisesRegex(ValueError,'parking'):
            city.add_road([(x-100,y),(x+100,y)])
        self.assertEqual(city.roads,roads)
        self.assertEqual(city.mobility_revision,revision)
        self.assertEqual(next(runtime.fleet.parked_vehicles()).position,(x,y))

    def test_all_169_source_buildings_receive_usable_shared_or_private_parking(self):
        from tools.run_arcata_scale_test import build_city
        root = Path(__file__).resolve().parents[1] / 'benchmarks/arcata'
        city,_,_ = build_city([root/'arcata-roads-2026-06-01.json'],
                              root/'arcata-city-boundary.osm',
                              building_paths=[root/'arcata-buildings-neighborhood.osm'])
        self.assertEqual(len(city.buildings), 169)
        lots = {l.id:l for l in city.parking_lots}
        self.assertTrue(all(lots[b.parking_lot_id].capacity >= 2 for b in city.buildings))
        self.assertTrue(all(lots[b.parking_lot_id].road_id for b in city.buildings))
        self.assertLess(len(lots), len(city.buildings))
