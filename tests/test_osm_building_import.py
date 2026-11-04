"""A small Overpass-style extract exercises the real city import path."""
import json
import gzip
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

from city import CityMap, Terrain, ZoneType
from city_simulation import CitySimulation
from models import BuildablePhase
from persistence import world_from_dict, world_to_dict
from tools.run_arcata_scale_test import build_city
from tools.import_arcata_homes import download_extract


ROOT = Path(__file__).resolve().parents[1]


def geometry(points):
    return [{'lon': lon, 'lat': lat} for lon, lat in points]


class BuildingImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.boundary = root / 'boundary.osm'
        self.boundary.write_text('''<osm>
          <node id="1" lon="-124.08" lat="40.86"/>
          <node id="2" lon="-124.07" lat="40.86"/>
          <node id="3" lon="-124.07" lat="40.87"/>
          <node id="4" lon="-124.08" lat="40.87"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
          <relation id="42"><member type="way" ref="10" role="outer"/>
            <tag k="name" v="Arcata"/><tag k="boundary" v="administrative"/>
          </relation></osm>''')
        self.roads = root / 'roads.json'
        self.roads.write_text(json.dumps({'elements': [
            {'type': 'node', 'id': 1, 'lon': -124.079, 'lat': 40.865},
            {'type': 'node', 'id': 2, 'lon': -124.071, 'lat': 40.8651},
            {'type': 'way', 'id': 20, 'nodes': [1, 2], 'tags': {'highway': 'residential'}},
        ]}))
        self.buildings = root / 'buildings.json'
        square_a = [(-124.078, 40.8652), (-124.0779, 40.8652),
                    (-124.0779, 40.8653), (-124.078, 40.8653), (-124.078, 40.8652)]
        square_b = [(-124.076, 40.8652), (-124.0758, 40.8652),
                    (-124.0758, 40.8653), (-124.076, 40.8653), (-124.076, 40.8652)]
        outer = [(-124.074, 40.8652), (-124.0738, 40.8652),
                 (-124.0738, 40.8653), (-124.074, 40.8653), (-124.074, 40.8652)]
        elements = [
            {'type': 'way', 'id': 101, 'tags': {'building': 'house'}, 'geometry': geometry(square_a)},
            {'type': 'way', 'id': 102, 'tags': {'building': 'commercial'}, 'nodes': [11, 12, 13, 14, 11]},
            {'type': 'way', 'id': 103, 'tags': {'building': 'no'}, 'geometry': geometry(square_a)},
            {'type': 'way', 'id': 104, 'tags': {'building': 'yes'}, 'geometry': geometry(
                [(lon + 1, lat) for lon, lat in square_a])},
            {'type': 'way', 'id': 105, 'tags': {'building': 'yes'}, 'nodes': [999, 998]},
            {'type': 'way', 'id': 201, 'tags': {'building': 'yes'}, 'geometry': geometry(outer[:3])},
            {'type': 'way', 'id': 202, 'geometry': geometry(list(reversed(outer[2:])))},
            {'type': 'relation', 'id': 500, 'tags': {'building': 'apartments', 'type': 'multipolygon'},
             'members': [{'type': 'way', 'ref': 201, 'role': 'outer'},
                         {'type': 'way', 'ref': 202, 'role': 'outer'}]},
        ]
        elements.extend({'type': 'node', 'id': ident, 'lon': lon, 'lat': lat}
                        for ident, (lon, lat) in zip((11, 12, 13, 14), square_b[:4]))
        self.buildings.write_text(json.dumps({'osm3s': {'timestamp_osm_base': '2026-01-01T00:00:00Z'},
                                              'elements': elements}))

    def test_imports_real_footprints_as_operational_empty_homes(self):
        city, _, metadata = build_city([self.roads], self.boundary, building_paths=[self.buildings])
        homes = {b.id: b for b in city.buildings}
        self.assertEqual(set(homes), {'osm-building:way:101', 'osm-building:way:102',
                                      'osm-building:relation:500'})
        self.assertEqual(metadata['imported_homes'], 2)
        self.assertEqual(metadata['imported_buildings'], 3)
        self.assertEqual(homes['osm-building:way:102'].category, ZoneType.COMMERCIAL)
        self.assertEqual(homes['osm-building:way:102'].residents, 0)
        self.assertEqual(homes['osm-building:way:101'].residents, 4)
        self.assertTrue(all(b.phase == BuildablePhase.OPERATIONAL
                            and b.occupants == 0 and b.jobs == 0 for b in homes.values()))
        self.assertGreater(homes['osm-building:way:102'].parcel.width,
                           homes['osm-building:way:101'].parcel.width * 1.9)
        self.assertGreater(homes['osm-building:way:101'].parcel.height, 20)
        self.assertLess(homes['osm-building:way:101'].parcel.height, 50)
        self.assertEqual(len(city.parcels), 3)

        encoded = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        loaded = world_from_dict(json.loads(json.dumps(encoded))).city_map
        runtime = CitySimulation(loaded)
        household = runtime.invite_household('osm-building:way:101', size=2)
        self.assertEqual(runtime.vacancy(household.home), 2)
        self.assertEqual(len(household.members), 2)

    def test_command_creates_loadable_city_with_configurable_capacity(self):
        output = Path(self.temp.name) / 'arcata-homes.json'
        result = subprocess.run([sys.executable, str(ROOT / 'tools' / 'import_arcata_homes.py'),
                                 '--osm', str(self.roads), '--boundary', str(self.boundary),
                                 '--buildings', str(self.buildings), '--residents-per-building', '6',
                                 '--output', str(output)], text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        city = world_from_dict(json.loads(output.read_text())).city_map
        self.assertEqual(len(city.buildings), 3)
        self.assertEqual(sorted(b.residents for b in city.buildings), [0, 6, 6])

    def test_no_usable_footprints_fails_without_writing_a_city(self):
        empty = Path(self.temp.name) / 'empty.json'
        empty.write_text(json.dumps({'elements': []}))
        output = Path(self.temp.name) / 'empty-city.json'
        result = subprocess.run([sys.executable, str(ROOT / 'tools' / 'import_arcata_homes.py'),
                                 '--osm', str(self.roads), '--boundary', str(self.boundary),
                                 '--buildings', str(empty), '--output', str(output)],
                                text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No usable building footprints', result.stderr)
        self.assertFalse(output.exists())

    def test_repeated_extract_does_not_duplicate_buildings(self):
        city, _, metadata = build_city([self.roads], self.boundary,
                                       building_paths=[self.buildings, self.buildings])
        self.assertEqual(len(city.buildings), 3)
        self.assertEqual(metadata['imported_homes'], 2)
        self.assertEqual(metadata['imported_buildings'], 3)

    def test_compressed_citywide_extract_uses_the_same_importer(self):
        compressed=Path(self.temp.name)/'citywide.json.gz'
        compressed.write_bytes(gzip.compress(self.buildings.read_bytes(),mtime=0))
        city,_,stats=build_city([self.roads],self.boundary,building_paths=[compressed])
        self.assertEqual(len(city.buildings),3)
        self.assertEqual(stats['imported_buildings'],3)

    def test_courtyard_stays_empty_while_the_building_is_imported(self):
        from tools.osm_buildings import import_osm_homes
        city=CityMap(terrain=Terrain(trees=[]))
        def member(points,role,ident):
            return dict(type='way',ref=ident,role=role,geometry=geometry(points))
        outer=[(100,100),(200,100),(200,200),(100,200),(100,100)]
        inner=[(130,130),(170,130),(170,170),(130,170),(130,130)]
        path=Path(self.temp.name)/'courtyard.json'
        path.write_text(json.dumps({'elements':[dict(type='relation',id=5,tags={'building':'university'},
            members=[member(outer,'outer',6),member(inner,'inner',7)])]}))
        stats=import_osm_homes(city,[path],lambda p:True,lambda p:p)
        self.assertEqual(stats['imported_buildings'],1)
        self.assertEqual(stats['imported_courtyard_buildings'],1)
        b=city.buildings[0]
        self.assertTrue(b.contains((110,150)))
        self.assertFalse(b.contains((150,150)))
        restored=world_from_dict(world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)).city_map
        self.assertFalse(restored.buildings[0].contains((150,150)))

    def test_invalid_courtyard_cannot_reappear_as_a_filled_outer_way(self):
        from tools.osm_buildings import import_osm_homes
        city=CityMap(terrain=Terrain(trees=[]))
        outer=[(100,100),(200,100),(200,200),(100,200),(100,100)]
        inner=[(190,190),(210,190),(210,210),(190,210),(190,190)]
        elements=[dict(type='way',id=1,tags={'building':'yes'},geometry=geometry(outer)),
                  dict(type='way',id=2,geometry=geometry(inner)),
                  dict(type='relation',id=3,tags={'building':'school'},members=[
                      dict(type='way',ref=1,role='outer'),dict(type='way',ref=2,role='inner')])]
        path=Path(self.temp.name)/'invalid-courtyard.json'
        path.write_text(json.dumps({'elements':elements}))
        stats=import_osm_homes(city,[path],lambda p:True,lambda p:p)
        self.assertEqual(stats['invalid_courtyard_relations'],1)
        self.assertEqual(stats.get('imported_buildings',0),0)
        self.assertFalse(city.buildings)

    def test_import_keeps_rotated_source_outline(self):
        data = json.loads(self.buildings.read_text())
        diamond = [(-124.077, 40.8652), (-124.0769, 40.86525),
                   (-124.077, 40.8653), (-124.0771, 40.86525), (-124.077, 40.8652)]
        data['elements'].append({'type': 'way', 'id': 106, 'tags': {'building': 'house'},
                                 'geometry': geometry(diamond)})
        self.buildings.write_text(json.dumps(data))
        city, _, _ = build_city([self.roads], self.boundary, building_paths=[self.buildings])
        home = next(b for b in city.buildings if b.id == 'osm-building:way:106')
        outline = home.parcel.footprints[0]
        self.assertEqual(len(outline), 5)
        self.assertNotEqual(outline[0][0], outline[1][0])
        self.assertNotEqual(outline[0][1], outline[1][1])
        self.assertFalse(home.parcel.contains((home.parcel.x, home.parcel.y)))
        saved = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        restored = world_from_dict(saved).city_map
        recovered = next(b for b in restored.buildings if b.id == home.id)
        self.assertEqual(recovered.parcel.footprints, home.parcel.footprints)

    def test_incomplete_courtyard_is_reported_instead_of_filled(self):
        data = json.loads(self.buildings.read_text())
        relation = next(e for e in data['elements'] if e['type'] == 'relation')
        relation['members'].append({'type': 'way', 'ref': 203, 'role': 'inner'})
        self.buildings.write_text(json.dumps(data))
        city, _, metadata = build_city([self.roads], self.boundary, building_paths=[self.buildings])
        self.assertEqual(metadata['incomplete_courtyard_relations'], 1)
        self.assertEqual({b.id for b in city.buildings},
                         {'osm-building:way:101', 'osm-building:way:102'})

    def test_download_requests_building_geometry_and_saves_extract(self):
        destination = Path(self.temp.name) / 'downloaded.json'
        response = {'elements': [{'type': 'way', 'id': 101, 'tags': {'building': 'house'}}]}
        with patch('tools.import_arcata_homes.urlopen',
                   return_value=io.BytesIO(json.dumps(response).encode())) as urlopen:
            download_extract(self.boundary, destination)
        self.assertEqual(json.loads(destination.read_text()), response)
        request = urlopen.call_args.args[0]
        query = parse_qs(request.data.decode())['data'][0]
        self.assertIn('way["building"]', query)
        self.assertIn('relation["building"]', query)
        self.assertIn('out body geom', query)

    def test_actual_arcata_osm_xml_footprints_import_on_real_road_map(self):
        roads = ROOT / 'benchmarks/arcata/arcata-roads-2026-06-01.json'
        boundary = ROOT / 'benchmarks/arcata/arcata-city-boundary.osm'
        sample = ROOT / 'tests/fixtures/arcata-osm-building-sample.osm'
        city, _, info = build_city([roads], boundary, building_paths=[sample])
        self.assertEqual(info['road_segments'], 1181)
        self.assertEqual(info['imported_homes'], 2)
        self.assertEqual({b.id for b in city.buildings},
                         {'osm-building:way:845521364', 'osm-building:way:845521365'})
        self.assertTrue(all(b.parcel.width > 0 and b.parcel.height > 0 for b in city.buildings))
        restored = world_from_dict(world_to_dict(city, unit_system='imperial',
                                   camera_x=0, camera_y=0, camera_zoom=1)).city_map
        self.assertEqual(len(restored.buildings), 2)

    def test_loading_rebuilds_network_after_roads_are_loaded_not_after_each_road(self):
        city = CityMap(terrain=Terrain(trees=[]))
        for i in range(5):
            city.add_road([(20, 100 + 100*i), (600, 100 + 100*i)])
        saved = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        original = CityMap.rebuild_mobility_network
        with patch.object(CityMap, 'rebuild_mobility_network', autospec=True, side_effect=original) as rebuild:
            restored = world_from_dict(saved).city_map
        self.assertEqual(len(restored.roads), 5)
        self.assertLessEqual(rebuild.call_count, 2)


if __name__ == '__main__':
    unittest.main()
