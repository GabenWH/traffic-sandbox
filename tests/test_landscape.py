"""Landscape data, persistence, import, and the shared viewer geometry."""
import json
import tempfile
import unittest
from pathlib import Path

from building_footprints import contains_point
from city import CityMap, Terrain
from persistence import world_from_dict, world_to_dict, WorldFormatError


class LandscapeTests(unittest.TestCase):
    def test_starter_landscape_has_distinct_cover_water_and_off_map_hills(self):
        terrain = Terrain.starter_terrain()
        self.assertTrue({'forest', 'meadow', 'farmland'} <= {a.kind for a in terrain.areas})
        self.assertTrue({'stream', 'river'} <= {w.kind for w in terrain.waterways})
        self.assertTrue(terrain.hills)
        for hill in terrain.hills:
            self.assertTrue(hill.x + hill.radius_x <= 0 or hill.x - hill.radius_x >= 5000
                            or hill.y + hill.radius_y <= 0 or hill.y - hill.radius_y >= 3500)

    def test_starter_hills_stay_outside_any_buildable_city_size(self):
        for width,height in [(800,600),(5000,3500),(10000,10000)]:
            city=CityMap(width=width,height=height)
            self.assertTrue(city.terrain.hills)
            for hill in city.terrain.hills:
                self.assertTrue(hill.x+hill.radius_x<=0 or hill.x-hill.radius_x>=width
                                or hill.y+hill.radius_y<=0 or hill.y-hill.radius_y>=height)

    def test_landscape_round_trips_and_legacy_saves_still_load(self):
        city = CityMap()
        snapshot = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        restored = world_from_dict(json.loads(json.dumps(snapshot))).city_map
        self.assertEqual(restored.terrain.areas, city.terrain.areas)
        self.assertEqual(restored.terrain.waterways, city.terrain.waterways)
        self.assertEqual(restored.terrain.hills, city.terrain.hills)
        for key in ('areas', 'waterways', 'hills', 'bounds'):
            snapshot['world']['terrain'].pop(key, None)
        legacy = world_from_dict(snapshot).city_map.terrain
        self.assertEqual((legacy.areas, legacy.waterways, legacy.hills), ([], [], []))

    def test_invalid_saved_landscape_polygon_is_rejected_at_load(self):
        city=CityMap(terrain=Terrain(trees=[]))
        snapshot=world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)
        snapshot['world']['terrain']['areas']=[{'kind':'forest','points':[[0,0],[1,0],[2,0]],'source':''}]
        with self.assertRaises(WorldFormatError): world_from_dict(snapshot)

    def test_import_mapped_areas_waterways_holes_and_deduplicate(self):
        from tools.osm_landscape import import_osm_landscape
        def geometry(points): return [{'lon': x, 'lat': y} for x, y in points]
        outer = [(0,0),(100,0),(100,100),(0,100),(0,0)]
        hole = [(30,30),(70,30),(70,70),(30,70),(30,30)]
        data = {'elements': [
            {'type':'way','id':1,'geometry':geometry(outer),'tags':{'landuse':'forest'}},
            {'type':'way','id':2,'geometry':geometry(hole)},
            {'type':'relation','id':3,'tags':{'type':'multipolygon','landuse':'forest'},
             'members':[{'type':'way','ref':1,'role':'outer'}, {'type':'way','ref':2,'role':'inner'}]},
            {'type':'way','id':4,'geometry':geometry([(110,0),(140,0),(140,30),(110,30),(110,0)]),
             'tags':{'landuse':'farmland'}},
            {'type':'way','id':5,'geometry':geometry([(0,120),(50,120)]),
             'tags':{'waterway':'stream','width':'2 m'}},
            {'type':'way','id':6,'geometry':geometry([(0,130),(50,130)]),
             'tags':{'waterway':'river'}},
            {'type':'way','id':7,'geometry':geometry([(0,0),(10,10)]),'tags':{'natural':'wood'}},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'land.json'; path.write_text(json.dumps(data))
            city=CityMap(terrain=Terrain(trees=[]))
            stats=import_osm_landscape(city,[path,path],lambda point:True,lambda point:point)
            areas=city.terrain.areas
            self.assertEqual(stats['forest'],1)
            self.assertEqual(stats['farmland'],1)
            forest=[a for a in areas if a.kind=='forest']
            self.assertTrue(any(contains_point(a.points,(10,10)) for a in forest))
            self.assertFalse(any(contains_point(a.points,(50,50)) for a in forest))
            stream=next(w for w in city.terrain.waterways if w.kind=='stream')
            self.assertAlmostEqual(stream.width, 2 * 3.28084)
            self.assertEqual(len(city.terrain.waterways),2)
            count = len(areas)
            import_osm_landscape(city,[path],lambda point:True,lambda point:point)
            self.assertEqual(len(city.terrain.waterways),2)
            self.assertEqual(len(city.terrain.areas),count)

    def test_waterway_relation_members_import_once_with_member_geometry(self):
        from tools.osm_landscape import import_osm_landscape
        points=[{'lon':1,'lat':1},{'lon':100,'lat':1}]
        data={'elements':[
            {'type':'way','id':30,'tags':{'waterway':'river'},'geometry':points},
            {'type':'relation','id':40,'tags':{'type':'waterway','waterway':'river'},
             'members':[{'type':'way','ref':30,'role':'main_stream','geometry':points},
                        {'type':'way','ref':31,'role':'main_stream',
                         'geometry':[{'lon':100,'lat':1},{'lon':200,'lat':5}]}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'river.json';path.write_text(json.dumps(data))
            city=CityMap(terrain=Terrain(trees=[]))
            import_osm_landscape(city,[path],lambda p:True,lambda p:p)
            self.assertEqual(len(city.terrain.waterways),2)
            self.assertTrue(all(w.kind=='river' for w in city.terrain.waterways))
            self.assertEqual(len({w.source for w in city.terrain.waterways}),2)

    def test_imported_forest_trees_avoid_mapped_waterways(self):
        from building_footprints import distance_to_segment
        from tools.osm_landscape import import_osm_landscape
        def geometry(points): return [{'lon': x, 'lat': y} for x,y in points]
        data={'elements':[
            {'type':'way','id':11,'tags':{'landuse':'forest'},
             'geometry':geometry([(0,0),(600,0),(600,600),(0,600),(0,0)])},
            {'type':'way','id':12,'tags':{'waterway':'river','width':'100 ft'},
             'geometry':geometry([(0,300),(600,300)])}]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'map.json';path.write_text(json.dumps(data))
            city=CityMap(terrain=Terrain(trees=[]))
            import_osm_landscape(city,[path],lambda p:True,lambda p:p)
            self.assertTrue(city.terrain.trees)
            self.assertTrue(all(distance_to_segment(p,(0,300),(600,300))>=50
                                for p in city.terrain.trees))

    def test_forest_tree_exclusion_covers_intersection_pavement(self):
        from models import Intersection
        from tools.osm_landscape import _tree_exclusions
        city=CityMap(terrain=Terrain(trees=[]))
        city.intersections.append(Intersection('wide',(300,300),radius=100))
        allowed=_tree_exclusions(city)
        self.assertFalse(allowed((335,335)))
        self.assertTrue(allowed((500,500)))

    def test_imported_forest_trees_avoid_parking_and_driveways(self):
        from building_footprints import distance_to_ring
        from parking import ParkingLot
        from tools.osm_landscape import import_osm_landscape
        def geometry(points): return [{'lon': x, 'lat': y} for x,y in points]
        data={'elements':[{'type':'way','id':82,'tags':{'landuse':'forest'},
              'geometry':geometry([(0,0),(600,0),(600,600),(0,600),(0,0)])}]}
        lot=ParkingLot('lot',surface=[(0,0),(300,0),(300,600),(0,600)],
                       driveway=[(300,300),(600,300)])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'forest.json';path.write_text(json.dumps(data))
            city=CityMap(width=600,height=600,terrain=Terrain(trees=[]),parking_lots=[lot])
            import_osm_landscape(city,[path],lambda p:True,lambda p:p)
            self.assertTrue(city.terrain.trees)
            for tree in city.terrain.trees:
                for polygon in [lot.surface,*lot.driveway_surfaces]:
                    self.assertGreaterEqual(distance_to_ring(polygon,tree),11)

    def test_forest_trees_stay_in_city_even_when_source_polygon_is_much_larger(self):
        from tools.osm_landscape import import_osm_landscape
        def geometry(points): return [{'lon': x, 'lat': y} for x,y in points]
        data={'elements':[{'type':'way','id':80,'tags':{'landuse':'forest'},
              'geometry':geometry([(-10000,-10000),(10000,-10000),(10000,10000),(-10000,10000),(-10000,-10000)])}]}
        def inside(p): return 0<=p[0]<=100 and 0<=p[1]<=100 and not (40<p[0]<60 and 40<p[1]<60)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'forest.json';path.write_text(json.dumps(data))
            city=CityMap(width=100,height=100,terrain=Terrain(trees=[],bounds=(0,0,100,100)))
            import_osm_landscape(city,[path],inside,lambda p:p,
                                 touches_boundary=lambda points,closed:True, contains_world=inside)
            self.assertTrue(city.terrain.trees)
            self.assertTrue(all(inside(p) for p in city.terrain.trees))

    def test_arcata_city_imports_landscape_with_shared_projection(self):
        from tools.run_arcata_scale_test import build_city
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            boundary=root/'boundary.osm'
            boundary.write_text("""<osm><node id='1' lon='0' lat='0'/><node id='2' lon='.01' lat='0'/>
              <node id='3' lon='.01' lat='.01'/><node id='4' lon='0' lat='.01'/>
              <way id='10'><nd ref='1'/><nd ref='2'/><nd ref='3'/><nd ref='4'/><nd ref='1'/></way>
              <relation id='42'><member type='way' ref='10' role='outer'/><tag k='name' v='Arcata'/>
              <tag k='boundary' v='administrative'/></relation></osm>""")
            roads=root/'roads.json'; roads.write_text(json.dumps({'elements':[
                {'type':'node','id':11,'lon':.002,'lat':.005},
                {'type':'node','id':12,'lon':.008,'lat':.005},
                {'type':'way','id':20,'nodes':[11,12],'tags':{'highway':'residential'}}]}))
            land=root/'land.json'; land.write_text(json.dumps({'elements':[
                {'type':'way','id':30,'tags':{'natural':'wood'},'geometry':[
                    {'lon':.002,'lat':.006},{'lon':.003,'lat':.006},
                    {'lon':.003,'lat':.007},{'lon':.002,'lat':.006}]},
                {'type':'way','id':31,'tags':{'waterway':'river'},'geometry':[
                    {'lon':-.005,'lat':.005},{'lon':.015,'lat':.005}]},
                {'type':'way','id':32,'tags':{'landuse':'meadow'},'geometry':[
                    {'lon':-.005,'lat':-.005},{'lon':.015,'lat':-.005},
                    {'lon':.015,'lat':.015},{'lon':-.005,'lat':.015},{'lon':-.005,'lat':-.005}]}]}))
            city,_,metadata=build_city([roads],boundary,landscape_paths=[land])
            self.assertEqual(metadata['landscape']['forest'],1)
            self.assertEqual(metadata['landscape']['river'],1)
            self.assertEqual(metadata['landscape']['meadow'],1)
            self.assertEqual(len(city.terrain.areas),2)
            self.assertLess(city.terrain.bounds[0],0)
            self.assertGreater(city.terrain.bounds[2],0)
            self.assertLess(city.terrain.areas[0].points[0][0],0)

    def test_existing_arcata_save_can_receive_landscape_without_losing_gameplay(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            boundary=root/'boundary.osm'
            boundary.write_text("""<osm><node id='1' lon='0' lat='0'/><node id='2' lon='.01' lat='0'/>
              <node id='3' lon='.01' lat='.01'/><node id='4' lon='0' lat='.01'/>
              <way id='10'><nd ref='1'/><nd ref='2'/><nd ref='3'/><nd ref='4'/><nd ref='1'/></way>
              <relation id='42'><member type='way' ref='10' role='outer'/><tag k='name' v='Arcata'/>
              <tag k='boundary' v='administrative'/></relation></osm>""")
            city=CityMap(terrain=Terrain(trees=[]))
            snapshot=world_to_dict(city,unit_system='imperial',camera_x=2,camera_y=3,camera_zoom=1)
            snapshot['gameplay']={'schema':'city.gameplay.v1','custom':{'money':123}}
            snapshot['custom_future_field']={'keep':True}
            source=root/'world.json';source.write_text(json.dumps(snapshot))
            land=root/'land.json';land.write_text(json.dumps({'elements':[
                {'type':'way','id':30,'tags':{'landuse':'meadow'},'geometry':[
                    {'lon':.002,'lat':.006},{'lon':.003,'lat':.006},
                    {'lon':.003,'lat':.007},{'lon':.002,'lat':.006}]}]}))
            output=root/'updated.json'
            script=Path(__file__).resolve().parents[1]/'tools/import_arcata_landscape.py'
            result=subprocess.run([sys.executable,str(script),'--world',str(source),'--landscape',str(land),
                                   '--boundary',str(boundary),'--output',str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            updated=json.loads(output.read_text())
            self.assertEqual(updated['gameplay'],snapshot['gameplay'])
            self.assertEqual(updated['custom_future_field'],snapshot['custom_future_field'])
            self.assertEqual(updated['view'],snapshot['view'])
            self.assertEqual(world_from_dict(updated).city_map.terrain.areas[0].kind,'meadow')
            self.assertFalse(source.read_text()==output.read_text())

    def test_grass_is_a_separate_shader_surface_with_map_orientation(self):
        from panda3d.core import NodePath
        from ui.landscape_view import LandscapeView
        root = NodePath('root')
        view = LandscapeView(root)
        view.replace(CityMap())
        self.assertEqual(view.root.getScale().y, -1)
        grass = view.root.find('**/grass')
        self.assertFalse(grass.isEmpty())
        self.assertIsNotNone(grass.getShader())
        self.assertGreater(grass.node().getGeom(0).getVertexData().getNumRows(), 100)
        view.close()
        self.assertTrue(view.root.isEmpty())

    def test_legacy_map_draws_cover_in_same_depth_order_as_3d(self):
        from types import SimpleNamespace
        from landscape import LandscapeArea
        from ui.renderer import RendererMixin
        fills=[]
        canvas=SimpleNamespace(create_polygon=lambda *args, **kwargs:fills.append(kwargs['fill']),
                               create_line=lambda *args, **kwargs:None)
        terrain=Terrain(trees=[],areas=[LandscapeArea('forest',[(0,0),(5,0),(0,5)]),
                                        LandscapeArea('meadow',[(0,0),(10,0),(0,10)]),
                                        LandscapeArea('water',[(0,0),(2,0),(0,2)])])
        host=SimpleNamespace(city_map=SimpleNamespace(terrain=terrain),canvas=canvas,
                             world_to_screen=lambda p:p,camera_zoom=1)
        RendererMixin._draw_landscape(host)
        self.assertEqual(fills,['#91bb65','#4c864e','#4f8fad'])

    def test_unchanged_landscape_reuses_geometry_and_triangulations(self):
        from unittest.mock import patch
        from panda3d.core import NodePath
        from landscape import LandscapeArea
        import landscape
        from ui.landscape_view import LandscapeView
        from ui.scene_buffers import compile_city
        city=CityMap(terrain=Terrain(trees=[],areas=[
            LandscapeArea('meadow',[(12001,0),(12111,0),(12111,121),(12001,121)]),
            LandscapeArea('forest',[(13001,0),(13111,0),(13111,121),(13001,121)])]))
        view=LandscapeView(NodePath('root'))
        self.addCleanup(view.close)
        original=landscape.triangulate_ring
        with patch('landscape.triangulate_ring', wraps=original) as triangulate:
            view.replace(city); compile_city(city,include_ground=False)
            first=view.root.find('**/grass')
            view.replace(city); compile_city(city,include_ground=False)
            self.assertEqual(view.root.find('**/grass'),first)
            self.assertEqual(triangulate.call_count,2)
            city.terrain.areas.append(LandscapeArea('meadow',[(14000,0),(14020,0),(14000,20)]))
            view.replace(city)
            self.assertNotEqual(view.root.find('**/grass'),first)

    def test_bending_waterway_uses_one_continuous_ribbon(self):
        from ui.landscape_geometry import waterway_quads
        quads=waterway_quads([(0,0),(100,0),(100,100)],20,-.3)
        self.assertEqual(len(quads),2)
        self.assertEqual(quads[0][1],quads[1][0])
        self.assertEqual(quads[0][2],quads[1][3])
        self.assertAlmostEqual(quads[0][1][0],90)
        self.assertAlmostEqual(quads[0][1][1],10)

    def test_landscape_mesh_contains_raised_grass_and_separate_water(self):
        from ui.landscape_geometry import grass_triangles
        from ui.scene_buffers import compile_city
        city=CityMap()
        grass=grass_triangles(city)
        self.assertGreater(grass[:,2].max(),10)
        triangles,_=compile_city(city,include_ground=False)
        water=[row for row in triangles if tuple(round(float(x),2) for x in row[3:6]) == (0.31,0.56,0.68)]
        self.assertTrue(water)
        self.assertTrue(all(-0.5 < row[2] < 0 for row in water))


if __name__ == '__main__': unittest.main()
