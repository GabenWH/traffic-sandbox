"""Tests for shared building and road construction state."""

import json
import unittest

from city import Building, CityMap, Parcel, Terrain
from models import (
    Buildable,
    BuildablePhase,
    ConsumptionState,
    ResourceInventory,
    WorkOrder,
    WorkType,
)
from persistence import world_from_dict, world_to_dict
from persistence import WorldFormatError


class BuildableLifecycleTests(unittest.TestCase):
    def test_buildings_and_roads_have_independent_inventories(self) -> None:
        building = Building("Test building", Parcel(0, 0, 20, 20))
        other = Building("Other building", Parcel(30, 0, 20, 20))
        road = CityMap(terrain=Terrain(trees=[])).add_road([(0, 0), (100, 0)])

        self.assertIsInstance(building, Buildable)
        self.assertIsInstance(road, Buildable)
        building.add_resource("lumber", 12)

        self.assertEqual(building.inventory.amounts, {"lumber": 12.0})
        self.assertEqual(other.inventory.amounts, {})
        self.assertEqual(road.inventory.amounts, {})

    def test_inventory_reports_full_partial_and_failed_consumption(self) -> None:
        inventory = ResourceInventory()
        inventory.add("concrete", 10)

        self.assertEqual(inventory.consume("concrete", 4), (ConsumptionState.FULL, 4.0))
        self.assertEqual(inventory.consume("concrete", 10), (ConsumptionState.PARTIAL, 6.0))
        self.assertEqual(inventory.consume("concrete", 1), (ConsumptionState.FAILED, 0.0))
        self.assertNotIn("concrete", inventory.amounts)

    def test_work_orders_drive_lifecycle_without_conflating_maintenance(self) -> None:
        building = Building("Test building", Parcel(0, 0, 20, 20))
        building.begin_work(WorkType.CONSTRUCTION, 10)

        self.assertEqual(building.phase, BuildablePhase.UNDER_CONSTRUCTION)
        self.assertFalse(building.perform_work(4))
        self.assertAlmostEqual(building.active_work.progress, 0.4)
        self.assertTrue(building.perform_work(6))
        self.assertEqual(building.phase, BuildablePhase.OPERATIONAL)
        self.assertIsNone(building.active_work)

        building.begin_work(WorkType.MAINTENANCE, 2)
        self.assertEqual(building.phase, BuildablePhase.OPERATIONAL)
        self.assertTrue(building.perform_work(2))
        self.assertEqual(building.phase, BuildablePhase.OPERATIONAL)

        building.begin_work(WorkType.DEMOLITION, 1)
        self.assertEqual(building.phase, BuildablePhase.DEMOLISHING)
        self.assertTrue(building.perform_work(1))
        self.assertEqual(building.phase, BuildablePhase.DECOMMISSIONED)

    def test_road_split_distributes_inventory_and_work_by_length(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)])
        road.add_resource("asphalt", 100)
        road.begin_work(WorkType.CONSTRUCTION, 20)
        road.perform_work(5)

        first, second = road.split((25, 0))

        self.assertEqual(first.inventory.amounts, {"asphalt": 25.0})
        self.assertEqual(second.inventory.amounts, {"asphalt": 75.0})
        self.assertIsNot(first.inventory, second.inventory)
        self.assertEqual(first.active_work, WorkOrder(WorkType.CONSTRUCTION, 5, 1.25))
        self.assertEqual(second.active_work, WorkOrder(WorkType.CONSTRUCTION, 15, 3.75))

    def test_world_round_trip_preserves_buildable_state(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)])
        road.condition = 0.75
        road.add_resource("asphalt", 8)
        road.begin_work(WorkType.MAINTENANCE, 10)
        road.perform_work(3)
        parcel = Parcel(20, 20, 30, 40)
        building = Building("Test building", parcel, phase=BuildablePhase.OPERATIONAL)
        building.add_resource("goods", 5)
        city.parcels.append(parcel)
        city.buildings.append(building)

        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        loaded = world_from_dict(json.loads(json.dumps(encoded))).city_map

        loaded_road = loaded.roads[0]
        self.assertEqual(loaded_road.phase, BuildablePhase.PLANNING)
        self.assertEqual(loaded_road.condition, 0.75)
        self.assertEqual(loaded_road.inventory.amounts, {"asphalt": 8.0})
        self.assertEqual(loaded_road.active_work, WorkOrder(WorkType.MAINTENANCE, 10, 3))
        self.assertEqual(loaded.buildings[0].phase, BuildablePhase.OPERATIONAL)
        self.assertEqual(loaded.buildings[0].inventory.amounts, {"goods": 5.0})

    def test_invalid_quantities_are_rejected(self) -> None:
        inventory = ResourceInventory()
        for amount in (0, -1, float("inf"), float("nan")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                inventory.add("steel", amount)

    def test_invalid_saved_condition_is_rejected(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])
        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        encoded["world"]["roads"][0]["buildable_state"]["condition"] = float("nan")

        with self.assertRaisesRegex(WorldFormatError, "condition must be finite"):
            world_from_dict(encoded)


if __name__ == "__main__":
    unittest.main()
