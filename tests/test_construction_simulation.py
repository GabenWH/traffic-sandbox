"""Demand scheduling and routed construction delivery simulation."""

import unittest
from math import dist

from city import Building, CityMap, Parcel, Terrain
from construction import (
    building_access_points,
    ConstructionSimulation,
    ConstructionTrip,
    CrewPayload,
    MaterialPayload,
    UnlimitedConstructionProvider,
)
from models import BuildablePhase, WorkType
from mobility import vehicle_route_points
from resources import ResourceSpec, TruckSpec


class ConstructionSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.city = CityMap(width=600, height=300, terrain=Terrain(trees=[]))
        self.city.add_road([(0, 100), (400, 100)])

    def test_material_trips_split_by_weight_and_volume_and_reserve_demand(self) -> None:
        resources = {
            "heavy": ResourceSpec("heavy", "Heavy", "t", 10, 1),
            "bulky": ResourceSpec("bulky", "Bulky", "m³", 1, 10),
        }
        trucks = {
            "material": TruckSpec("material", 100, 25, 0, 18, 8),
        }
        building = Building(
            "Warehouse",
            Parcel(120, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"heavy": 25, "bulky": 6},
        )
        self.city.buildings.append(building)
        simulation = ConstructionSimulation(
            resources,
            trucks,
            UnlimitedConstructionProvider(),
        )

        simulation.update(self.city, 0)

        material_trips = [
            trip for trip in (*simulation.trips, *simulation.pending_trips)
            if isinstance(trip.payload, MaterialPayload)
        ]
        self.assertEqual(len(material_trips), 6)
        self.assertEqual(len(simulation.trips), 1)
        self.assertEqual(len(simulation.pending_trips), 5)
        active = simulation.trips[0]
        self.assertIs(active.road_vehicle, simulation.road_vehicles.vehicles[0])
        self.assertEqual(active.road_vehicle.appearance.kind, "construction_truck")
        self.assertEqual(active.road_vehicle.appearance.shape, "material_truck")
        self.assertEqual(active.position, active.road_vehicle.position)
        self.assertCountEqual(
            [trip.payload.amount for trip in material_trips
             if trip.payload.resource_id == "heavy"],
            [10, 10, 5],
        )
        self.assertCountEqual(
            [trip.payload.amount for trip in material_trips
             if trip.payload.resource_id == "bulky"],
            [2.5, 2.5, 1],
        )
        self.assertEqual(
            simulation._in_transit_material(building.id, "heavy"), 25
        )
        self.assertEqual(
            simulation._in_transit_material(building.id, "bulky"), 6
        )
        self.assertTrue(all(trip.distance_travelled == 0 for trip in material_trips))
        for trip in material_trips:
            resource = resources[trip.payload.resource_id]
            truck = trucks[trip.truck_id]
            self.assertLessEqual(
                trip.payload.amount * resource.mass_kg_per_unit,
                truck.payload_kg,
            )
            self.assertLessEqual(
                trip.payload.amount * resource.volume_m3_per_unit,
                truck.cargo_m3,
            )

        simulation.update(self.city, 0)
        self.assertEqual(len(simulation.trips), 1)
        self.assertEqual(len(simulation.pending_trips), 5)

    def test_port_dispatches_one_shared_material_or_crew_truck_every_twenty_seconds(self) -> None:
        city = CityMap(width=2000, height=300, terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (1500, 100)])
        building = Building(
            "Warehouse",
            Parcel(1200, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 12},
            construction_workers=1,
        )
        city.buildings.append(building)
        simulation = ConstructionSimulation(
            {"stone": ResourceSpec("stone", "Stone", "t", 500, 1)},
            {
                "material": TruckSpec("material", 2500, 10, 0, 18, 8),
                "crew": TruckSpec("crew", 0, 0, 1, 20, 8),
            },
            UnlimitedConstructionProvider(),
            truck_speed=5,
        )

        simulation.update(city, 0)
        self.assertEqual(len(simulation.trips), 1)
        self.assertIsInstance(simulation.trips[0].payload, MaterialPayload)
        self.assertEqual(len(simulation.pending_trips), 3)

        simulation.update(city, 19.999)
        self.assertEqual(len(simulation.trips), 1)
        simulation.update(city, 0.001)
        self.assertEqual(len(simulation.trips), 2)
        simulation.update(city, 20)
        self.assertEqual(len(simulation.trips), 3)
        simulation.update(city, 20)
        self.assertEqual(len(simulation.trips), 4)
        self.assertIsInstance(simulation.trips[-1].payload, CrewPayload)

    def test_port_keeps_minimum_spacing_when_new_demand_appears_after_idle_queue(self) -> None:
        first = Building(
            "First", Parcel(120, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 1},
        )
        self.city.buildings.append(first)
        simulation = ConstructionSimulation(
            {"stone": ResourceSpec("stone", "Stone", "t", 500, 1)},
            {"material": TruckSpec("material", 2500, 10, 0, 18, 8)},
            UnlimitedConstructionProvider(),
            truck_speed=5,
        )

        simulation.update(self.city, 0)
        self.assertEqual(len(simulation.trips), 1)
        second = Building(
            "Second", Parcel(220, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 1},
        )
        self.city.buildings.append(second)

        simulation.update(self.city, 19.999)
        self.assertEqual(len(simulation.trips), 1)
        self.assertEqual(len(simulation.pending_trips), 1)
        simulation.update(self.city, 0.001)
        self.assertEqual(len(simulation.trips), 2)

    def test_trip_heading_tracks_route_tangent_and_turns(self) -> None:
        trip = ConstructionTrip(
            "trip", "port", "building", "material",
            MaterialPayload("stone", 1),
            ((0, 0), (10, 0), (10, 10)), 1,
        )

        self.assertEqual(trip.heading, (1.0, 0.0))
        trip.distance_travelled = 10
        self.assertEqual(trip.heading, (0.0, 1.0))
        trip.distance_travelled = 20
        self.assertEqual(trip.heading, (0.0, 1.0))

    def test_trip_moves_along_its_saved_road_route(self) -> None:
        resources = {"stone": ResourceSpec("stone", "Stone", "t", 500, 1)}
        trucks = {"material": TruckSpec("material", 2500, 10, 0, 18, 8)}
        building = Building(
            "Project",
            Parcel(120, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 5},
        )
        self.city.buildings.append(building)
        simulation = ConstructionSimulation(
            resources, trucks, UnlimitedConstructionProvider(), truck_speed=10,
        )

        simulation.update(self.city, 0)
        trip = simulation.trips[0]
        start = trip.position
        simulation.update(self.city, 1)

        self.assertAlmostEqual(trip.distance_travelled, 10)
        self.assertNotEqual(trip.position, start)
        self.assertAlmostEqual(dist(start, trip.position), 10)

    def test_small_fractional_remainder_is_delivered_before_work_starts(self) -> None:
        required = 0.3000000002
        building = Building(
            "Project",
            Parcel(120, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": required},
            construction_workers=1,
            construction_work=1,
        )
        self.city.buildings.append(building)
        simulation = ConstructionSimulation(
            {"stone": ResourceSpec("stone", "Stone", "t", 1, 1)},
            {
                "material": TruckSpec("material", 0.1, 0.1, 0, 18, 8),
                "crew": TruckSpec("crew", 0, 0, 1, 20, 8),
            },
            UnlimitedConstructionProvider(),
            truck_speed=1000,
        )

        simulation.update(self.city, 0)
        self.assertAlmostEqual(
            simulation._in_transit_material(building.id, "stone"),
            required,
        )
        simulation.update(self.city, 81)

        self.assertEqual(building.construction_delivered["stone"], required)
        self.assertEqual(building.active_work.kind, WorkType.CONSTRUCTION)

    def test_ulp_scale_delivery_remainder_is_reconciled_before_work_starts(self) -> None:
        required = 976.2551293378144
        max_load = 45.4766762331217
        building = Building(
            "Project",
            Parcel(120, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": required},
            construction_workers=1,
            construction_work=1,
        )
        self.city.buildings.append(building)
        simulation = ConstructionSimulation(
            {"stone": ResourceSpec("stone", "Stone", "t", 1, 1)},
            {
                "material": TruckSpec("material", max_load, max_load, 0, 18, 8),
                "crew": TruckSpec("crew", 0, 0, 1, 20, 8),
            },
            UnlimitedConstructionProvider(),
            truck_speed=1000,
        )

        simulation.update(self.city, 0)
        simulation.update(self.city, 441)

        self.assertEqual(building.construction_delivered, {"stone": required})
        self.assertEqual(building.phase, BuildablePhase.UNDER_CONSTRUCTION)
        self.assertEqual(building.active_work.kind, WorkType.CONSTRUCTION)

    def test_demand_retries_after_west_gate_connects_to_building_road(self) -> None:
        city = CityMap(width=600, height=300, terrain=Terrain(trees=[]))
        disconnected = city.add_road([(250, 100), (400, 100)])
        building = Building(
            "Project",
            Parcel(300, 112, 40, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 5},
            construction_workers=1,
            construction_work=20,
        )
        city.buildings.append(building)
        simulation = ConstructionSimulation(
            {"stone": ResourceSpec("stone", "Stone", "t", 500, 1)},
            {
                "material": TruckSpec("material", 2500, 10, 0, 18, 8),
                "crew": TruckSpec("crew", 0, 0, 3, 20, 8),
            },
            UnlimitedConstructionProvider(),
            truck_speed=1000,
        )

        simulation.update(city, 0)
        self.assertEqual(simulation.trips, [])
        self.assertEqual(building.construction_delivered, {})

        connected = city.add_road([(0, 100), (250, 100)])
        self.assertIsNot(disconnected, connected)
        simulation.update(city, 0)

        self.assertEqual(len(simulation.trips), 1)
        self.assertEqual(len(simulation.pending_trips), 1)
        self.assertIsNotNone(simulation._best_route(city, building))
        completed = simulation.update(city, 21)
        self.assertEqual(len(completed), 2)
        self.assertEqual(building.construction_delivered, {"stone": 5.0})
        self.assertEqual(building.assigned_workers, 1)

    def test_route_search_skips_unreachable_near_lane_direction(self) -> None:
        city = CityMap(width=600, height=300, terrain=Terrain(trees=[]))
        disconnected = city.add_road(
            [(250, 130), (400, 130)],
            forward_lane_count=1,
            reverse_lane_count=0,
        )
        connected = city.add_road(
            [(0, 100), (400, 100)],
            forward_lane_count=1,
            reverse_lane_count=0,
        )
        building = Building(
            "Project",
            Parcel(300, 112, 40, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 5},
            construction_workers=1,
            construction_work=20,
        )
        city.buildings.append(building)
        resources = {"stone": ResourceSpec("stone", "Stone", "t", 500, 1)}
        trucks = {
            "material": TruckSpec("material", 2500, 10, 0, 18, 8),
            "crew": TruckSpec("crew", 0, 0, 3, 20, 8),
        }
        simulation = ConstructionSimulation(
            resources, trucks, UnlimitedConstructionProvider(),
        )
        unreachable = building_access_points(city, building)[0]
        self.assertEqual(unreachable.lane.road_id, disconnected.id)

        route = simulation._best_route(city, building)
        self.assertIsNotNone(route)
        self.assertIn(vehicle_route_points(route)[-1], {
            position.point
            for position in building_access_points(city, building)
            if position.lane.road_id == connected.id
        })

    def test_crews_wait_for_all_materials_then_work_and_release_on_completion(self) -> None:
        class StagedProvider(UnlimitedConstructionProvider):
            allow_steel = False
            allow_workers = False

            def available_material(self, resource_id: str) -> float:
                if resource_id == "steel" and not self.allow_steel:
                    return 0
                return super().available_material(resource_id)

            def available_workers(self) -> float:
                return float("inf") if self.allow_workers else 0

        resources = {
            "stone": ResourceSpec("stone", "Stone", "t", 500, 1),
            "steel": ResourceSpec("steel", "Steel", "t", 500, 1),
        }
        trucks = {
            "material": TruckSpec("material", 2500, 10, 0, 18, 8),
            "crew": TruckSpec("crew", 0, 0, 3, 20, 8),
        }
        building = Building(
            "Apartment",
            Parcel(120, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 10, "steel": 10},
            construction_workers=4,
            construction_work=100,
        )
        self.city.buildings.append(building)
        provider = StagedProvider()
        simulation = ConstructionSimulation(resources, trucks, provider, truck_speed=1000)

        simulation.update(self.city, 0)
        self.assertEqual(
            [trip.payload.amount for trip in (*simulation.trips, *simulation.pending_trips)
             if isinstance(trip.payload, MaterialPayload)],
            [5, 5],
        )
        self.assertFalse(any(
            isinstance(trip.payload, CrewPayload)
            for trip in (*simulation.trips, *simulation.pending_trips)
        ))

        completed = simulation.update(self.city, 21)
        self.assertEqual(len(completed), 2)
        self.assertEqual(building.construction_delivered, {"stone": 10.0})
        self.assertEqual(building.assigned_workers, 0)
        self.assertIsNone(building.active_work)

        provider.allow_workers = True
        simulation.update(self.city, 0)
        self.assertEqual(
            [trip.payload.workers for trip in (*simulation.trips, *simulation.pending_trips)
             if isinstance(trip.payload, CrewPayload)],
            [3, 1],
        )
        completed = simulation.update(self.city, 21)
        self.assertEqual(len(completed), 1)
        self.assertEqual(building.assigned_workers, 3)
        self.assertIsNone(building.active_work)
        self.assertNotIn("steel", building.construction_delivered)
        completed = simulation.update(self.city, 19)
        self.assertEqual(len(completed), 1)
        self.assertEqual(building.assigned_workers, 4)

        provider.allow_steel = True
        simulation.update(self.city, 0)
        completed = simulation.update(self.city, 41)
        self.assertEqual(len(completed), 2)
        self.assertEqual(building.phase, BuildablePhase.UNDER_CONSTRUCTION)
        self.assertEqual(building.construction_delivered, {"stone": 10.0, "steel": 10.0})
        self.assertEqual(building.inventory.amounts, {})
        self.assertEqual(building.assigned_workers, 4)
        work_at_check = building.active_work.completed_work
        simulation.update(self.city, 5)
        self.assertAlmostEqual(building.active_work.completed_work, work_at_check + 20)
        self.assertEqual(building.assigned_workers, 4)
        simulation.update(self.city, 20)
        self.assertEqual(building.phase, BuildablePhase.OPERATIONAL)
        self.assertIsNone(building.active_work)
        self.assertEqual(building.assigned_workers, 0)
        self.assertEqual(building.construction_delivered, {"stone": 10.0, "steel": 10.0})
        simulation.update(self.city, 0)
        self.assertEqual(simulation.trips, [])

    def test_clear_trips_preserves_deliveries_and_assigned_workers(self) -> None:
        resources = {"stone": ResourceSpec("stone", "Stone", "t", 500, 1)}
        trucks = {
            "material": TruckSpec("material", 2500, 10, 0, 18, 8),
            "crew": TruckSpec("crew", 0, 0, 3, 20, 8),
        }
        building = Building(
            "Project",
            Parcel(120, 112, 50, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"stone": 10},
            construction_workers=2,
        )
        building.record_construction_delivery("stone", 3)
        building.assigned_workers = 1
        self.city.buildings.append(building)
        simulation = ConstructionSimulation(
            resources, trucks, UnlimitedConstructionProvider(),
        )

        simulation.update(self.city, 0)
        self.assertEqual(simulation._in_transit_workers(building.id), 1)
        simulation.clear_trips()

        self.assertEqual(simulation.trips, [])
        self.assertEqual(building.construction_delivered, {"stone": 3.0})
        self.assertEqual(building.inventory.amounts, {"stone": 3.0})
        self.assertEqual(building.assigned_workers, 1)


if __name__ == "__main__":
    unittest.main()
