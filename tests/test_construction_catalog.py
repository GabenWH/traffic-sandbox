"""Validation and starter data for construction materials and trucks."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from resources import (
    CONSTRUCTION_CATALOG_PATH,
    ConstructionCatalogError,
    ResourceSpec,
    TruckSpec,
    load_construction_catalog,
    validate_resource_references,
)
from ui_tools.buildables import BuildableSpec, buildables_of_kind


class ConstructionCatalogTests(unittest.TestCase):
    def test_starter_catalog_has_physical_resources_and_usable_partial_loads(self) -> None:
        resources, trucks = load_construction_catalog()

        self.assertEqual(
            {resource_id: (spec.unit, spec.mass_kg_per_unit, spec.volume_m3_per_unit)
             for resource_id, spec in resources.items()},
            {
                "lumber": ("m³", 500.0, 1.0),
                "stone": ("t", 1000.0, 0.5),
                "steel": ("t", 1000.0, 1.0),
            },
        )
        material = trucks["material_truck"]
        self.assertEqual((material.payload_kg, material.cargo_m3, material.crew_capacity), (7500, 10, 0))
        crew = trucks["crew_truck"]
        self.assertEqual((crew.payload_kg, crew.cargo_m3, crew.crew_capacity), (0, 0, 3))

        buildings = buildables_of_kind("building")
        validate_resource_references(buildings, resources)
        for building in buildings:
            for resource_id, required in building.specs["construction_needs"].items():
                resource = resources[resource_id]
                maximum_load = min(
                    material.payload_kg / resource.mass_kg_per_unit,
                    material.cargo_m3 / resource.volume_m3_per_unit,
                )
                self.assertLess(maximum_load, required, (building.id, resource_id))

    def test_resource_spec_rejects_blank_identity_and_invalid_physics(self) -> None:
        for field, value in (
            ("id", " "),
            ("unit", ""),
            ("mass_kg_per_unit", 0),
            ("mass_kg_per_unit", -1),
            ("mass_kg_per_unit", float("inf")),
            ("mass_kg_per_unit", float("nan")),
            ("volume_m3_per_unit", 0),
            ("volume_m3_per_unit", -1),
            ("volume_m3_per_unit", float("inf")),
            ("volume_m3_per_unit", float("nan")),
        ):
            values = {
                "id": "stone",
                "name": "Stone",
                "unit": "t",
                "mass_kg_per_unit": 1000,
                "volume_m3_per_unit": 0.5,
            }
            values[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(
                ConstructionCatalogError, field
            ):
                ResourceSpec(**values)

    def test_truck_spec_rejects_invalid_capacity_and_dimensions(self) -> None:
        for field, value in (
            ("payload_kg", -1),
            ("payload_kg", float("inf")),
            ("cargo_m3", -1),
            ("cargo_m3", float("nan")),
            ("crew_capacity", -1),
            ("crew_capacity", True),
            ("length", 0),
            ("length", float("inf")),
            ("width", -1),
        ):
            values = {
                "id": "truck",
                "payload_kg": 100,
                "cargo_m3": 5,
                "crew_capacity": 0,
                "length": 18,
                "width": 8,
            }
            values[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(
                ConstructionCatalogError, field
            ):
                TruckSpec(**values)

        TruckSpec("material", 100, 5, 0, 18, 8)
        TruckSpec("crew", 0, 0, 3, 20, 8)
        with self.assertRaisesRegex(ConstructionCatalogError, "payload type"):
            TruckSpec("empty", 0, 0, 0, 18, 8)
        with self.assertRaisesRegex(ConstructionCatalogError, "payload type"):
            TruckSpec("partial", 100, 0, 0, 18, 8)

    def test_catalog_rejects_duplicate_resource_and_truck_ids(self) -> None:
        original = json.loads(CONSTRUCTION_CATALOG_PATH.read_text(encoding="utf-8"))
        for catalog_key in ("resources", "trucks"):
            with self.subTest(catalog_key=catalog_key), TemporaryDirectory() as directory:
                catalog = json.loads(json.dumps(original))
                catalog[catalog_key].append(dict(catalog[catalog_key][0]))
                path = Path(directory) / "construction_resources.json"
                path.write_text(json.dumps(catalog), encoding="utf-8")

                with self.assertRaisesRegex(ConstructionCatalogError, "Duplicate"):
                    load_construction_catalog(path)

    def test_resource_reference_validation_rejects_unknown_building_needs(self) -> None:
        resources, _ = load_construction_catalog()
        missing = BuildableSpec(
            id="building",
            kind="building",
            name="Building",
            description="Building",
            specs={"construction_needs": {"unobtainium": 1}},
        )

        with self.assertRaisesRegex(ConstructionCatalogError, "unobtainium"):
            validate_resource_references((missing,), resources)


if __name__ == "__main__":
    unittest.main()
