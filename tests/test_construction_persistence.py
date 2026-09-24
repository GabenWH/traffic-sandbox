"""Save/load recovery for runtime construction deliveries."""

from __future__ import annotations

import json
import unittest

from city import Building, CityMap, Parcel, Terrain
from construction import (
    ConstructionSimulation,
    CrewPayload,
    MaterialPayload,
    UnlimitedConstructionProvider,
)
from models import BuildablePhase, WorkType
from persistence import WORLD_VERSION, WorldFormatError, world_from_dict, world_to_dict
from resources import load_construction_catalog


class ConstructionPersistenceTests(unittest.TestCase):
    def _partial_and_active_city(self) -> tuple[CityMap, Building, Building]:
        city = CityMap(width=900, height=500, terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (800, 100)])
        partial = Building(
            "Partial project",
            Parcel(150, 112, 50, 40),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"lumber": 10},
            construction_workers=3,
            construction_work=100,
        )
        partial.record_construction_delivery("lumber", 5)
        partial.assigned_workers = 1
        active = Building(
            "Active project",
            Parcel(300, 112, 50, 40),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"lumber": 10},
            construction_workers=2,
            construction_work=100,
        )
        active.record_construction_delivery("lumber", 10)
        active.assigned_workers = 2
        active.begin_work(WorkType.CONSTRUCTION, 100)
        active.perform_work(30)
        city.parcels.extend([partial.parcel, active.parcel])
        city.buildings.extend([partial, active])
        return city, partial, active

    def test_round_trip_restores_partial_deliveries_and_active_work(self) -> None:
        city, partial, active = self._partial_and_active_city()
        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        loaded = world_from_dict(json.loads(json.dumps(encoded))).city_map
        loaded_partial, loaded_active = loaded.buildings

        self.assertEqual(WORLD_VERSION, 7)
        self.assertEqual(loaded_partial.construction_workers, 3)
        self.assertEqual(loaded_partial.construction_work, 100)
        self.assertEqual(loaded_partial.construction_delivered, {"lumber": 5.0})
        self.assertEqual(loaded_partial.inventory.amounts, {"lumber": 5.0})
        self.assertEqual(loaded_partial.assigned_workers, 1)
        self.assertIsNone(loaded_partial.active_work)
        self.assertEqual(loaded_active.construction_delivered, {"lumber": 10.0})
        self.assertEqual(loaded_active.inventory.amounts, {})
        self.assertEqual(loaded_active.assigned_workers, 2)
        self.assertEqual(loaded_active.active_work.completed_work, 30.0)
        self.assertEqual(loaded_active.phase, BuildablePhase.UNDER_CONSTRUCTION)
        self.assertNotIn("trips", encoded)
        self.assertNotIn("trips", encoded["world"])
        self.assertEqual((partial.id, active.id), (loaded_partial.id, loaded_active.id))

    def test_loading_regenerates_only_missing_deliveries_and_resumes_work(self) -> None:
        city, _partial, _active = self._partial_and_active_city()
        encoded = world_to_dict(
            city, unit_system="metric", camera_x=0, camera_y=0, camera_zoom=1,
        )
        loaded = world_from_dict(json.loads(json.dumps(encoded))).city_map
        resources, trucks = load_construction_catalog()
        simulation = ConstructionSimulation(
            resources, trucks, UnlimitedConstructionProvider(), truck_speed=1000,
        )

        simulation.update(loaded, 0.5)

        partial, active = loaded.buildings
        partial_trips = [
            trip for trip in (*simulation.trips, *simulation.pending_trips)
            if trip.building_id == partial.id
        ]
        active_trips = [
            trip for trip in (*simulation.trips, *simulation.pending_trips)
            if trip.building_id == active.id
        ]
        self.assertEqual(
            partial.construction_delivered["lumber"] - 5.0 + sum(
                trip.payload.amount for trip in partial_trips
                if isinstance(trip.payload, MaterialPayload)
            ),
            5.0,
        )
        self.assertEqual(partial.assigned_workers, 1)
        self.assertEqual(
            sum(
                trip.payload.workers for trip in partial_trips
                if isinstance(trip.payload, CrewPayload)
            ),
            2,
        )
        self.assertEqual(active_trips, [])
        self.assertAlmostEqual(active.active_work.completed_work, 31.0)

    def test_versions_four_through_six_default_missing_construction_fields(self) -> None:
        city, _partial, _active = self._partial_and_active_city()
        for version in (4, 5, 6):
            with self.subTest(version=version):
                encoded = world_to_dict(
                    city,
                    unit_system="imperial",
                    camera_x=0,
                    camera_y=0,
                    camera_zoom=1,
                )
                encoded["version"] = version
                for building in encoded["world"]["buildings"]:
                    state = building["buildable_state"]
                    for key in (
                        "construction_workers",
                        "construction_work",
                        "assigned_workers",
                        "construction_delivered",
                    ):
                        state.pop(key, None)

                loaded = world_from_dict(encoded).city_map

                self.assertEqual(loaded.buildings[0].construction_workers, 0)
                self.assertEqual(loaded.buildings[0].construction_work, 0)
                self.assertEqual(loaded.buildings[0].assigned_workers, 0)
                self.assertEqual(loaded.buildings[0].construction_delivered, {})

    def test_legacy_small_house_save_recovers_template_needs_and_delivery_state(self) -> None:
        city = CityMap(width=900, height=500, terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (800, 100)])
        partial = Building(
            "Small house",
            Parcel(150, 112, 40, 30),
            buildable_id="small_house",
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"lumber": 20, "stone": 10},
        )
        partial.add_resource("lumber", 7)
        active = Building(
            "Small house",
            Parcel(300, 112, 40, 30),
            buildable_id="small_house",
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"lumber": 20, "stone": 10},
        )
        active.record_construction_delivery("lumber", 20)
        active.record_construction_delivery("stone", 10)
        active.assigned_workers = 2
        active.begin_work(WorkType.CONSTRUCTION, 180)
        active.perform_work(30)
        city.parcels.extend([partial.parcel, active.parcel])
        city.buildings.extend([partial, active])
        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        encoded["version"] = 6
        for building_data in encoded["world"]["buildings"]:
            state = building_data["buildable_state"]
            for key in (
                "construction_workers",
                "construction_work",
                "assigned_workers",
                "construction_delivered",
            ):
                state.pop(key, None)

        loaded = world_from_dict(encoded).city_map
        loaded_partial, loaded_active = loaded.buildings

        self.assertEqual(loaded_partial.construction_workers, 2)
        self.assertEqual(loaded_partial.construction_work, 180)
        self.assertEqual(loaded_partial.construction_delivered, {"lumber": 7.0})
        self.assertEqual(loaded_partial.assigned_workers, 0)
        self.assertEqual(loaded_active.construction_delivered, {"lumber": 20.0, "stone": 10.0})
        self.assertEqual(loaded_active.assigned_workers, 2)
        self.assertEqual(loaded_active.construction_work, 180)

        resources, trucks = load_construction_catalog()
        simulation = ConstructionSimulation(
            resources, trucks, UnlimitedConstructionProvider(), truck_speed=1000,
        )
        initial_delivered = dict(loaded_partial.construction_delivered)
        simulation.update(loaded, 0.5)

        partial_trips = [
            trip for trip in (*simulation.trips, *simulation.pending_trips)
            if trip.building_id == loaded_partial.id
        ]
        active_trips = [
            trip for trip in (*simulation.trips, *simulation.pending_trips)
            if trip.building_id == loaded_active.id
        ]
        self.assertEqual(
            loaded_partial.construction_delivered.get("lumber", 0)
            - initial_delivered.get("lumber", 0) + sum(
                trip.payload.amount for trip in partial_trips
                if isinstance(trip.payload, MaterialPayload)
                and trip.payload.resource_id == "lumber"
            ),
            13,
        )
        self.assertEqual(
            loaded_partial.construction_delivered.get("stone", 0)
            - initial_delivered.get("stone", 0) + sum(
                trip.payload.amount for trip in partial_trips
                if isinstance(trip.payload, MaterialPayload)
                and trip.payload.resource_id == "stone"
            ),
            10,
        )
        self.assertEqual(
            loaded_partial.assigned_workers - 0 + sum(
                trip.payload.workers for trip in partial_trips
                if isinstance(trip.payload, CrewPayload)
            ),
            2,
        )
        self.assertEqual(active_trips, [])
        self.assertAlmostEqual(loaded_active.active_work.completed_work, 31)

    def test_invalid_saved_construction_worker_and_delivery_values_are_rejected(self) -> None:
        city, _partial, _active = self._partial_and_active_city()
        encoded = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )
        state = encoded["world"]["buildings"][0]["buildable_state"]
        cases = (
            ("construction_workers", -1, "construction_workers"),
            ("construction_work", float("inf"), "construction_work"),
            ("assigned_workers", 4, "assigned_workers"),
            ("construction_delivered", {"lumber": 11}, "construction_delivered"),
            ("construction_delivered", {"stone": 1}, "construction_delivered"),
        )
        for key, value, message in cases:
            with self.subTest(key=key, value=value):
                state[key] = value
                with self.assertRaisesRegex(WorldFormatError, message):
                    world_from_dict(encoded)
                encoded = world_to_dict(
                    city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
                )
                state = encoded["world"]["buildings"][0]["buildable_state"]


if __name__ == "__main__":
    unittest.main()
