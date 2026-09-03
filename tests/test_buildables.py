"""Tests for JSON buildable templates and building placement."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from city import CityMap, Terrain, ZoneType
from persistence import world_from_dict, world_to_dict
from ui.interactions import InteractionMixin
from ui_tools.buildables import BuildableCatalogError, buildables_of_kind, load_buildables
from ui_tools.tools.road_tool import BuildingTool


class BuildablesTests(unittest.TestCase):
    def test_default_catalog_contains_valid_road_and_building_specs(self) -> None:
        specs = load_buildables()

        self.assertIn("two_lane_street", {spec.id for spec in specs})
        self.assertIn("small_house", {spec.id for spec in specs})
        self.assertTrue(all(spec.description for spec in specs))

    def test_catalog_rejects_duplicate_ids(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "buildables.json"
            entry = {
                "id": "same",
                "kind": "road",
                "name": "Road",
                "description": "Road",
                "specs": {
                    "lane_width": 12,
                    "forward_lane_count": 1,
                    "reverse_lane_count": 1,
                },
            }
            path.write_text(json.dumps({"version": 1, "buildables": [entry, entry]}))

            with self.assertRaisesRegex(BuildableCatalogError, "Duplicate"):
                load_buildables(path)

    def test_building_tool_places_selected_template_and_makes_it_selectable(self) -> None:
        redraws: list[bool] = []

        class Host(InteractionMixin):
            city_map = CityMap(width=500, height=400, terrain=Terrain(trees=[]))
            inspector_tool = None

            @staticmethod
            def redraw_world() -> None:
                redraws.append(True)

        host = Host()
        tool = BuildingTool(host, buildables_of_kind("building"))
        tool.selected_spec = next(spec for spec in tool.specs if spec.id == "corner_shop")

        building = tool.place_building((100, 120))

        assert building is not None
        self.assertEqual(building.buildable_id, "corner_shop")
        self.assertEqual(building.parcel.zone, ZoneType.COMMERCIAL)
        self.assertEqual((building.jobs, building.residents), (8, 0))
        self.assertEqual((building.parcel.width, building.parcel.height), (54.0, 42.0))
        self.assertIs(host.building_at((100, 120)), building)
        self.assertEqual(redraws, [True])

        encoded = world_to_dict(
            host.city_map,
            unit_system="imperial",
            camera_x=0,
            camera_y=0,
            camera_zoom=1,
        )
        loaded = world_from_dict(encoded).city_map.buildings[0]
        self.assertEqual((loaded.buildable_id, loaded.color), ("corner_shop", "#70a8c9"))

    def test_building_tool_rejects_placement_outside_the_map(self) -> None:
        class Host:
            city_map = CityMap(width=100, height=100, terrain=Terrain(trees=[]))
            inspector_tool = None

            @staticmethod
            def redraw_world() -> None:
                raise AssertionError("Invalid placement should not redraw")

        tool = BuildingTool(Host(), buildables_of_kind("building"))

        self.assertIsNone(tool.place_building((2, 2)))
        self.assertEqual(tool.host.city_map.buildings, [])


if __name__ == "__main__":
    unittest.main()
