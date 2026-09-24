"""Tests for JSON buildable templates and building placement."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from city import CityMap, Terrain, ZoneType
from persistence import world_from_dict, world_to_dict
from ui.interactions import InteractionMixin
from ui_tools.buildables import (
    BUILDABLES_PATH,
    BuildableCatalogError,
    buildables_of_kind,
    load_buildables,
)
from ui_tools.tools.road_tool import BuildingTool
from ui_tools.tools.inspect_tool import deliver_building_resource
from models import BuildablePhase, WorkType


class BuildablesTests(unittest.TestCase):
    def test_default_catalog_contains_valid_road_and_building_specs(self) -> None:
        specs = load_buildables()

        self.assertIn("two_lane_street", {spec.id for spec in specs})
        self.assertIn("small_house", {spec.id for spec in specs})
        self.assertTrue(all(spec.description for spec in specs))
        for spec in buildables_of_kind("building"):
            self.assertGreater(spec.specs["construction_workers"], 0)
            self.assertGreater(spec.specs["construction_work"], 0)

    def test_building_requirements_must_have_positive_workers_and_finite_work(self) -> None:
        for field, value in (
            ("construction_workers", 0),
            ("construction_workers", 1.5),
            ("construction_work", 0),
            ("construction_work", float("inf")),
            ("construction_work", float("nan")),
        ):
            with self.subTest(field=field, value=value), TemporaryDirectory() as directory:
                catalog = json.loads(BUILDABLES_PATH.read_text(encoding="utf-8"))
                building = next(
                    entry for entry in catalog["buildables"]
                    if entry["kind"] == "building"
                )
                building["specs"][field] = value
                path = Path(directory) / "buildables.json"
                path.write_text(json.dumps(catalog), encoding="utf-8")

                with self.assertRaisesRegex(BuildableCatalogError, field):
                    load_buildables(path)

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
        self.assertEqual(building.phase, BuildablePhase.UNDER_CONSTRUCTION)
        self.assertIsNone(building.active_work)
        self.assertEqual(building.construction_workers, 3)
        self.assertEqual(building.construction_work, 450)
        self.assertEqual(building.assigned_workers, 0)
        self.assertEqual(building.construction_delivered, {})
        self.assertEqual(building.parcel.zone, ZoneType.COMMERCIAL)
        self.assertEqual((building.jobs, building.residents), (8, 0))
        self.assertEqual((building.parcel.width, building.parcel.height), (54.0, 42.0))
        self.assertTrue(building.construction_needs)
        with self.assertRaisesRegex(ValueError, "needs"):
            building.begin_work(WorkType.CONSTRUCTION, 10)
        for resource, amount in building.construction_needs.items():
            deliver_building_resource(building, f"{resource} {amount}")
        building.begin_work(WorkType.CONSTRUCTION, 10)
        self.assertEqual(building.inventory.amounts, {})
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
        self.assertEqual(loaded.construction_needs, building.construction_needs)

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
