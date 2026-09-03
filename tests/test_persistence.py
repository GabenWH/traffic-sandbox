"""Tests for versioned generic world persistence."""

import json
import unittest

from city import Building, CityMap, Parcel, Terrain, ZoneType
from models import ControlDefinition, ControlType, IntersectionKind
from persistence import WORLD_FORMAT, WorldFormatError, world_from_dict, world_to_dict


class WorldPersistenceTests(unittest.TestCase):
    def test_world_round_trip_preserves_hierarchy_and_view(self) -> None:
        city = CityMap(width=900, height=700, terrain=Terrain("#123456", [(400, 400)]))
        road = city.add_road([(10, 20), (80, 20), (120, 60)], name="Broadway")
        parcel = Parcel(30, 40, 50, 60, ZoneType.COMMERCIAL)
        city.parcels.append(parcel)
        city.buildings.append(Building("Corner Shop", parcel, jobs=7))
        encoded = world_to_dict(
            city, unit_system="metric", camera_x=12, camera_y=34, camera_zoom=1.5,
        )

        self.assertTrue(all(
            "id" not in lane
            for saved_road in encoded["world"]["roads"]
            for lane in saved_road["lanes"]
        ))

        loaded = world_from_dict(json.loads(json.dumps(encoded)))

        self.assertEqual(encoded["format"], WORLD_FORMAT)
        self.assertEqual((loaded.city_map.width, loaded.city_map.height), (900.0, 700.0))
        self.assertEqual(loaded.city_map.terrain.trees, [(400.0, 400.0)])
        self.assertEqual(loaded.city_map.roads[0].id, road.id)
        self.assertEqual(
            [lane.id for lane in loaded.city_map.roads[0].lanes],
            [lane.id for lane in road.lanes],
        )
        self.assertIs(loaded.city_map.buildings[0].parcel, loaded.city_map.parcels[0])
        self.assertEqual(len(loaded.city_map.cul_de_sacs), 2)
        self.assertEqual((loaded.unit_system, loaded.camera_zoom), ("metric", 1.5))

    def test_merge_demo_save_is_not_treated_as_a_generic_world(self) -> None:
        with self.assertRaisesRegex(WorldFormatError, "city-builder world"):
            world_from_dict({"scenario": "merge_demo", "cars": []})

    def test_unknown_road_port_reference_data_is_rejected(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        encoded["world"]["intersections"][0]["lane_connections"][0][
            "source_output"
        ]["road_id"] = "missing-road"

        with self.assertRaisesRegex(WorldFormatError, "unknown road"):
            world_from_dict(encoded)

    def test_intersection_round_trip_preserves_segment_links(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)], name="East West")
        city.add_road([(50, 0), (50, 100)], name="North South")
        city.standard_intersections[0].lane_connections[0].control = ControlDefinition(ControlType.STOP)
        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )

        loaded = world_from_dict(json.loads(json.dumps(encoded)))

        self.assertEqual(len(loaded.city_map.roads), 4)
        self.assertEqual(len(loaded.city_map.standard_intersections), 1)
        self.assertEqual(len(loaded.city_map.cul_de_sacs), 4)
        intersection = loaded.city_map.standard_intersections[0]
        self.assertEqual(intersection.position, (50.0, 50.0))
        self.assertEqual(
            [road.id for road in intersection.connected_roads],
            encoded["world"]["intersections"][0]["road_ids"],
        )
        self.assertEqual(
            world_to_dict(
                loaded.city_map,
                unit_system="imperial",
                camera_x=0,
                camera_y=0,
                camera_zoom=1,
            )["world"]["intersections"][0]["lane_connections"],
            encoded["world"]["intersections"][0]["lane_connections"],
        )
        self.assertEqual(intersection.lane_connections[0].control.kind, ControlType.STOP)

    def test_multi_road_cul_de_sac_round_trip_uses_generic_intersection(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (200, 0)], name="Main road")
        city.add_road(
            [(0, 100), (0, 0)],
            name="Driveway",
            forward_lane_count=1,
            reverse_lane_count=0,
        )
        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )

        loaded = world_from_dict(json.loads(json.dumps(encoded))).city_map

        cul_de_sac = next(
            intersection for intersection in loaded.intersections
            if intersection.position == (0.0, 0.0)
        )
        self.assertEqual(cul_de_sac.kind, IntersectionKind.CUL_DE_SAC)
        self.assertEqual(
            [road.name for road in cul_de_sac.connected_roads],
            ["Main road", "Driveway"],
        )
        self.assertTrue(any(
            connection.source_output.road is not connection.destination_input.road
            for connection in cul_de_sac.lane_connections
        ))


if __name__ == "__main__":
    unittest.main()
