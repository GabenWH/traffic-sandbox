"""Elevation behavior for roads and grade-separated junctions."""

import unittest

from city import CityMap, Terrain
from models import Road
from persistence import WORLD_VERSION, WorldFormatError, world_from_dict, world_to_dict


class RoadElevationTests(unittest.TestCase):
    def test_height_interpolates_along_centerline(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)], elevations=[0, 20])

        self.assertEqual(road.elevation_at((50, 0)), 10)

    def test_split_preserves_slope_on_both_pieces(self) -> None:
        road = Road("r", "Ramp", [(0, 0), (100, 0)], elevations=[0, 20])
        road.rebuild_lanes()

        first, second = road.split((50, 0))

        self.assertEqual(first.elevations, [0, 10])
        self.assertEqual(second.elevations, [10, 20])

    def test_overpass_crossing_does_not_create_junction(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)])
        city.add_road([(50, 0), (50, 100)], elevations=[20, 20])

        self.assertEqual(len(city.standard_intersections), 0)
        self.assertEqual(len(city.roads), 2)
        ground_end = next(
            junction for junction in city.cul_de_sacs
            if junction.position == (0, 50)
        )
        upper_end = next(
            junction for junction in city.cul_de_sacs
            if junction.position == (50, 100)
        )
        self.assertIsNone(city.find_vehicle_route_between(ground_end, upper_end))

    def test_matching_elevated_crossing_creates_one_junction(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)], elevations=[20, 20])
        city.add_road([(50, 0), (50, 100)], elevations=[20, 20])

        self.assertEqual(len(city.standard_intersections), 1)
        self.assertEqual(city.standard_intersections[0].elevation, 20)
        self.assertEqual(len(city.standard_intersections[0].connected_roads), 4)

    def test_stacked_road_ends_have_distinct_cul_de_sacs(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        city.add_road([(0, 0), (0, 100)], elevations=[20, 20])

        at_origin = [
            junction for junction in city.cul_de_sacs
            if junction.position == (0, 0)
        ]
        self.assertEqual(sorted(j.elevation for j in at_origin), [0, 20])

    def test_save_round_trip_preserves_road_and_junction_height(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)], elevations=[20, 20])
        city.add_road([(50, 0), (50, 100)], elevations=[20, 20])

        saved = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        loaded = world_from_dict(saved).city_map

        self.assertEqual(saved["version"], WORLD_VERSION)
        self.assertTrue(all(road.elevations == [20, 20] for road in loaded.roads))
        self.assertEqual(loaded.standard_intersections[0].elevation, 20)

    def test_version_four_save_loads_at_ground_level(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        saved = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        saved["version"] = 4
        for road in saved["world"]["roads"]:
            road.pop("elevations", None)
        for junction in saved["world"]["intersections"]:
            junction.pop("elevation", None)

        loaded = world_from_dict(saved).city_map

        self.assertEqual(loaded.roads[0].elevations, [0, 0])
        self.assertTrue(all(junction.elevation == 0 for junction in loaded.intersections))

    def test_save_rejects_wrong_number_of_elevations(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        saved = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        saved["world"]["roads"][0]["elevations"] = [10]

        with self.assertRaises(WorldFormatError):
            world_from_dict(saved)

    def test_explicit_empty_heights_are_not_treated_as_ground_default(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        with self.assertRaises(ValueError):
            city.add_road([(0, 0), (100, 0)], elevations=[])

    def test_save_round_trip_preserves_3d_camera(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        camera = {"target": [250, 350, 0], "yaw": 120, "pitch": 90, "distance": 900}

        saved = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
            camera_3d=camera,
        )

        self.assertEqual(world_from_dict(saved).camera_3d, camera)

    def test_save_rejects_invalid_3d_camera_pitch(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        saved = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        saved["view"]["camera_3d"] = {
            "target": [250, 350, 0], "yaw": 0, "pitch": 100, "distance": 900,
        }

        with self.assertRaises(WorldFormatError):
            world_from_dict(saved)


if __name__ == "__main__":
    unittest.main()
