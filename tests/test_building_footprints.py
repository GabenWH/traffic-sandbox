import math
from types import SimpleNamespace
import unittest

from city import Building, CityMap, Parcel, Terrain, ZoneType
from construction import distance_from_parcel
from models import BuildablePhase
from persistence import WorldFormatError, world_from_dict, world_to_dict
from ui.renderer import RendererMixin


DIAMOND = [(0, 10), (10, 0), (20, 10), (10, 20), (0, 10)]


class BuildingFootprintTests(unittest.TestCase):
    def test_hit_testing_and_access_distance_use_shape_not_bounding_box(self):
        parcel = Parcel(0, 0, 20, 20, ZoneType.RESIDENTIAL, footprints=[DIAMOND])
        self.assertTrue(parcel.contains((10, 10)))
        self.assertTrue(parcel.contains((5, 5)))
        self.assertFalse(parcel.contains((1, 1)))
        self.assertEqual(distance_from_parcel(parcel, (10, 10)), 0)
        self.assertAlmostEqual(distance_from_parcel(parcel, (0, 0)), math.sqrt(50))

    def test_saved_city_round_trips_rotated_building_footprint(self):
        city = CityMap(terrain=Terrain(trees=[]))
        parcel = Parcel(0, 0, 20, 20, ZoneType.RESIDENTIAL, footprints=[DIAMOND])
        city.parcels.append(parcel)
        city.buildings.append(Building('Diamond', parcel, residents=4, phase=BuildablePhase.OPERATIONAL))
        encoded = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        restored = world_from_dict(encoded).city_map.buildings[0].parcel
        self.assertEqual(restored.footprints, [DIAMOND])
        self.assertTrue(restored.contains((10, 10)))
        self.assertFalse(restored.contains((1, 1)))

    def test_invalid_saved_footprint_is_rejected(self):
        city = CityMap(terrain=Terrain(trees=[]))
        parcel = Parcel(0, 0, 20, 20, ZoneType.RESIDENTIAL, footprints=[DIAMOND])
        city.parcels.append(parcel)
        saved = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        saved['world']['parcels'][0]['footprints'] = [[[0, 0], [10, 10], [20, 20], [0, 0]]]
        with self.assertRaises(WorldFormatError):
            world_from_dict(saved)

    def test_version_8_rectangular_saves_remain_loadable(self):
        city = CityMap(terrain=Terrain(trees=[]))
        parcel = Parcel(0, 0, 20, 20, ZoneType.RESIDENTIAL)
        city.parcels.append(parcel)
        city.buildings.append(Building('Old home', parcel, residents=4, phase=BuildablePhase.OPERATIONAL))
        saved = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        saved['version'] = 8
        saved['world']['parcels'][0].pop('footprints')
        restored = world_from_dict(saved).city_map.buildings[0].parcel
        self.assertEqual(restored.footprints, [])
        self.assertTrue(restored.contains((1, 1)))

    def test_renderer_draws_rotated_polygon_at_high_and_low_zoom(self):
        class Canvas:
            def __init__(self): self.polygons = []; self.rectangles = []
            def winfo_width(self): return 1000
            def winfo_height(self): return 1000
            def create_polygon(self, *points, **kwargs): self.polygons.append((points, kwargs))
            def create_rectangle(self, *points, **kwargs): self.rectangles.append((points, kwargs))
            def create_text(self, *args, **kwargs): pass
        city = CityMap(terrain=Terrain(trees=[]))
        parcel = Parcel(0, 0, 20, 20, ZoneType.RESIDENTIAL, footprints=[DIAMOND])
        city.buildings.append(Building('Diamond', parcel, phase=BuildablePhase.OPERATIONAL))
        for zoom in (0.2, 1.0):
            canvas = Canvas()
            host = SimpleNamespace(city_map=city, canvas=canvas, camera_zoom=zoom,
                                   world_to_screen=lambda point: point)
            RendererMixin._draw_buildings(host)
            self.assertTrue(canvas.polygons)
            self.assertFalse(canvas.rectangles)
            coords = canvas.polygons[-1][0]
            self.assertIn(10, coords)
            self.assertNotEqual(coords[:4], (0, 0, 20, 0))

    def test_concave_roof_triangles_cover_polygon_without_filling_notch(self):
        from building_footprints import triangulate_ring
        polygon = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
        for ring in (polygon, list(reversed(polygon))):
            triangles = triangulate_ring(ring)
            areas = [abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2
                     for a,b,c in triangles]
            self.assertAlmostEqual(sum(areas), 7.0)
            self.assertEqual(len(triangles), 4)

    def test_3d_prism_follows_the_rotated_outline(self):
        from building_footprints import prism_geometry
        sides, roof = prism_geometry(DIAMOND, 2, 14)
        self.assertEqual(len(sides), 4)
        self.assertEqual(len(roof), 2)
        self.assertEqual({(x,y) for quad in sides for x,y,z in quad}, set(DIAMOND[:-1]))
        self.assertTrue(all(z == 14 for tri in roof for x,y,z in tri))

    def test_concave_building_has_a_walking_origin_inside_its_footprint(self):
        from city_simulation import CitySimulation
        outline = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4), (0, 0)]
        parcel = Parcel(0, 0, 4, 4, ZoneType.RESIDENTIAL, footprints=[outline])
        self.assertFalse(parcel.contains((2, 2)))
        city = CityMap(terrain=Terrain(trees=[]))
        building = Building('L house', parcel, residents=4, phase=BuildablePhase.OPERATIONAL)
        city.parcels.append(parcel); city.buildings.append(building)
        runtime = CitySimulation(city)
        self.assertTrue(parcel.contains(runtime.sites[building.id]['walk_point']))


if __name__ == '__main__':
    unittest.main()
