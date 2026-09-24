"""Provider contracts and road-side access for construction deliveries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import dist, hypot, inf, isfinite, isnan, ulp
from typing import Protocol
from uuid import uuid4

from city import Building, CityMap, Parcel
from mobility import (
    LanePosition,
    MobilityLink,
    MobilityNode,
    VehicleRouteEndpoint,
    nearest_lane_position,
    vehicle_route_points,
)
from models import (
    BuildablePhase,
    Point,
    WorkType,
    point_at_polyline_distance,
    polyline_length,
)
from pathfinding import Path
from resources import (
    ConstructionCatalogError,
    ResourceSpec,
    TruckSpec,
)


WEST_EDGE_TOLERANCE = 1e-6


class ConstructionProvider(Protocol):
    """A source that can reserve construction materials and crews for trips."""

    id: str

    def access_points(self, city_map: CityMap) -> tuple[VehicleRouteEndpoint, ...]: ...

    def available_material(self, resource_id: str) -> float: ...

    def available_workers(self) -> float: ...

    def reserve_material(self, resource_id: str, amount: float) -> bool: ...

    def reserve_workers(self, count: int) -> bool: ...


class UnlimitedConstructionProvider:
    """Abstract first-slice source with no finite inventory or workforce."""

    id = "virtual-construction-provider"

    def access_points(self, city_map: CityMap) -> tuple[VehicleRouteEndpoint, ...]:
        return provider_access_points(city_map)

    def available_material(self, resource_id: str) -> float:
        return inf

    def available_workers(self) -> float:
        return inf

    def reserve_material(self, resource_id: str, amount: float) -> bool:
        return True

    def reserve_workers(self, count: int) -> bool:
        return True


def provider_access_points(
    city_map: CityMap,
) -> tuple[VehicleRouteEndpoint, ...]:
    """Find connected junctions and inbound lanes meeting the west map edge."""
    endpoints: list[VehicleRouteEndpoint] = [
        intersection
        for intersection in city_map.intersections
        if abs(intersection.position[0]) <= WEST_EDGE_TOLERANCE
        and intersection.connected_roads
    ]
    seen_lanes: set[tuple[int, int]] = set()
    for road in city_map.roads:
        for lane in road.lanes:
            travelled = 0.0
            for start, end in zip(lane.points, lane.points[1:]):
                dx, dy = end[0] - start[0], end[1] - start[1]
                segment_length = hypot(dx, dy)
                if segment_length == 0:
                    continue
                if dx > 0 and start[0] <= 0.0 <= end[0]:
                    fraction = (0.0 - start[0]) / dx
                    y = start[1] + dy * fraction
                    distance = travelled + segment_length * fraction
                    key = (id(lane), round(distance * 1_000_000))
                    if key not in seen_lanes:
                        endpoints.append(
                            LanePosition(lane, distance, (0.0, y))
                        )
                        seen_lanes.add(key)
                travelled += segment_length
    return tuple(endpoints)


def building_access_points(
    city_map: CityMap,
    building: Building,
) -> tuple[LanePosition, ...]:
    """Return nearby directional lane positions beside a building parcel."""
    center = (
        building.parcel.x + building.parcel.width / 2,
        building.parcel.y + building.parcel.height / 2,
    )
    candidates: list[LanePosition] = []
    for road in city_map.roads:
        maximum_distance = 2.0 * road.lane_width
        for lane in road.lanes:
            position, _ = nearest_lane_position(lane, center)
            if distance_from_parcel(building.parcel, position.point) <= maximum_distance:
                candidates.append(position)
    return tuple(candidates)


def distance_from_parcel(parcel: Parcel, point: Point) -> float:
    """Measure from a point to the rectangle, returning zero inside it."""
    distance_x = max(parcel.x - point[0], 0.0, point[0] - (parcel.x + parcel.width))
    distance_y = max(parcel.y - point[1], 0.0, point[1] - (parcel.y + parcel.height))
    return dist((0.0, 0.0), (distance_x, distance_y))


CONSTRUCTION_TRUCK_SPEED = 90.0


@dataclass(frozen=True)
class MaterialPayload:
    resource_id: str
    amount: float


@dataclass(frozen=True)
class CrewPayload:
    workers: int


@dataclass
class ConstructionTrip:
    id: str
    provider_id: str
    building_id: str
    truck_id: str
    payload: MaterialPayload | CrewPayload
    route_points: tuple[Point, ...]
    speed: float
    distance_travelled: float = 0.0

    @property
    def position(self) -> Point:
        return point_at_polyline_distance(
            list(self.route_points), self.distance_travelled,
        )


class ConstructionSimulation:
    """Dispatch routed material loads from current construction demand."""

    def __init__(
        self,
        resources: Mapping[str, ResourceSpec],
        trucks: Mapping[str, TruckSpec],
        provider: ConstructionProvider,
        truck_speed: float = CONSTRUCTION_TRUCK_SPEED,
    ) -> None:
        if not isfinite(truck_speed) or truck_speed <= 0:
            raise ValueError("Construction truck speed must be positive and finite")
        self.resources = dict(resources)
        self.trucks = dict(trucks)
        self.provider = provider
        self.truck_speed = float(truck_speed)
        self.trips: list[ConstructionTrip] = []
        self._city_map: CityMap | None = None
        self._material_delivery_counts: dict[tuple[str, str], int] = {}

    def update(
        self,
        city_map: CityMap,
        elapsed_seconds: float,
    ) -> tuple[ConstructionTrip, ...]:
        """Advance existing work and trips, then dispatch outstanding demand."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Construction elapsed time must be finite and nonnegative")
        self._city_map = city_map
        for building in city_map.buildings:
            if (
                elapsed_seconds > 0
                and building.active_work is not None
                and building.active_work.kind is WorkType.CONSTRUCTION
                and building.assigned_workers > 0
            ):
                if building.perform_work(building.assigned_workers * elapsed_seconds):
                    building.assigned_workers = 0

        completed: list[ConstructionTrip] = []
        for trip in tuple(self.trips):
            route_length = polyline_length(list(trip.route_points))
            trip.distance_travelled = min(
                route_length,
                trip.distance_travelled + elapsed_seconds * trip.speed,
            )
            if trip.distance_travelled >= route_length:
                self._apply_delivery(trip)
                self.trips.remove(trip)
                completed.append(trip)

        for building in city_map.buildings:
            if (
                building.phase is BuildablePhase.UNDER_CONSTRUCTION
                and building.active_work is None
                and building.construction_workers > 0
                and building.construction_work > 0
                and building.assigned_workers >= building.construction_workers
                and self._materials_complete(building)
            ):
                building.begin_work(WorkType.CONSTRUCTION, building.construction_work)

        self._dispatch_materials(city_map)
        self._dispatch_workers(city_map)
        return tuple(completed)

    def _in_transit_material(self, building_id: str, resource_id: str) -> float:
        return sum(
            trip.payload.amount
            for trip in self.trips
            if trip.building_id == building_id
            and isinstance(trip.payload, MaterialPayload)
            and trip.payload.resource_id == resource_id
        )

    def _in_transit_workers(self, building_id: str) -> int:
        return sum(
            trip.payload.workers
            for trip in self.trips
            if trip.building_id == building_id
            and isinstance(trip.payload, CrewPayload)
        )

    def _best_route(
        self,
        city_map: CityMap,
        building: Building,
    ) -> Path[MobilityNode, MobilityLink] | None:
        routes = [
            route
            for start in self.provider.access_points(city_map)
            for destination in building_access_points(city_map, building)
            if (
                route := city_map.find_vehicle_route_between(start, destination)
            ) is not None
        ]
        return min(routes, key=lambda route: route.cost) if routes else None

    def _make_trip(
        self,
        building: Building,
        truck: TruckSpec,
        payload: MaterialPayload | CrewPayload,
        route: Path[MobilityNode, MobilityLink],
    ) -> ConstructionTrip:
        points = vehicle_route_points(route)
        if not points:
            raise ValueError("Construction truck route must contain geometry")
        trip = ConstructionTrip(
            id=str(uuid4()),
            provider_id=self.provider.id,
            building_id=building.id,
            truck_id=truck.id,
            payload=payload,
            route_points=points,
            speed=self.truck_speed,
        )
        self.trips.append(trip)
        return trip

    def _apply_delivery(self, trip: ConstructionTrip) -> None:
        if self._city_map is None:
            return
        building = next(
            (item for item in self._city_map.buildings if item.id == trip.building_id),
            None,
        )
        if building is None:
            return
        if isinstance(trip.payload, MaterialPayload):
            building.record_construction_delivery(
                trip.payload.resource_id,
                trip.payload.amount,
            )
            key = (building.id, trip.payload.resource_id)
            self._material_delivery_counts[key] = (
                self._material_delivery_counts.get(key, 0) + 1
            )
        else:
            building.assigned_workers += trip.payload.workers

    def _materials_complete(self, building: Building) -> bool:
        for resource_id, required in building.construction_needs.items():
            delivered = building.construction_delivered.get(resource_id, 0.0)
            if delivered >= required:
                continue
            remaining = required - delivered
            if (
                remaining > self._material_rounding_tolerance(
                    building.id, resource_id, required,
                )
                or self._in_transit_material(building.id, resource_id) > 0
            ):
                return False
            inventory = building.inventory.amounts.get(resource_id, 0.0)
            if inventory < required:
                building.inventory.add(resource_id, required - inventory)
            building.construction_delivered[resource_id] = required
        return True

    def _material_rounding_tolerance(
        self,
        building_id: str,
        resource_id: str,
        required: float,
    ) -> float:
        transit_count = sum(
            trip.building_id == building_id
            and isinstance(trip.payload, MaterialPayload)
            and trip.payload.resource_id == resource_id
            for trip in self.trips
        )
        delivery_count = self._material_delivery_counts.get(
            (building_id, resource_id), 0,
        )
        return ulp(required) * max(4, transit_count + delivery_count + 2)

    def clear_trips(self) -> None:
        """Discard runtime trips when the current city is replaced."""
        self.trips.clear()
        self._material_delivery_counts.clear()

    def _dispatch_materials(self, city_map: CityMap) -> None:
        material_trucks = [
            truck for truck in self.trucks.values()
            if truck.payload_kg > 0 and truck.cargo_m3 > 0
        ]
        if not material_trucks:
            return
        for building in city_map.buildings:
            if (
                building.phase is not BuildablePhase.UNDER_CONSTRUCTION
                or building.active_work is not None
                or not building.construction_needs
            ):
                continue
            route: Path[MobilityNode, MobilityLink] | None = None
            for resource_id, required in building.construction_needs.items():
                resource = self.resources.get(resource_id)
                if resource is None:
                    raise ConstructionCatalogError(
                        f"Unknown construction resource {resource_id!r}"
                    )
                truck = max(
                    material_trucks,
                    key=lambda candidate: (
                        min(
                            candidate.payload_kg / resource.mass_kg_per_unit,
                            candidate.cargo_m3 / resource.volume_m3_per_unit,
                        ),
                        candidate.id,
                    ),
                )
                max_load = min(
                    truck.payload_kg / resource.mass_kg_per_unit,
                    truck.cargo_m3 / resource.volume_m3_per_unit,
                )
                while True:
                    remaining = (
                        required
                        - building.construction_delivered.get(resource_id, 0.0)
                        - self._in_transit_material(building.id, resource_id)
                    )
                    rounding_tolerance = self._material_rounding_tolerance(
                        building.id, resource_id, required,
                    )
                    if remaining <= rounding_tolerance:
                        break
                    available = self.provider.available_material(resource_id)
                    if isnan(available) or available <= 0:
                        break
                    amount = min(remaining, max_load, available)
                    if amount <= 0:
                        break
                    if route is None:
                        route = self._best_route(city_map, building)
                    if route is None:
                        break
                    if not self.provider.reserve_material(resource_id, amount):
                        break
                    self._make_trip(
                        building,
                        truck,
                        MaterialPayload(resource_id, amount),
                        route,
                    )

    def _dispatch_workers(self, city_map: CityMap) -> None:
        crew_trucks = [
            truck for truck in self.trucks.values()
            if truck.crew_capacity > 0
        ]
        if not crew_trucks:
            return
        truck = max(crew_trucks, key=lambda candidate: (candidate.crew_capacity, candidate.id))
        for building in city_map.buildings:
            if (
                building.phase is not BuildablePhase.UNDER_CONSTRUCTION
                or building.active_work is not None
            ):
                continue
            deficit = (
                building.construction_workers
                - building.assigned_workers
                - self._in_transit_workers(building.id)
            )
            if deficit <= 0:
                continue
            available = self.provider.available_workers()
            if isnan(available) or available <= 0:
                continue
            route = self._best_route(city_map, building)
            if route is None:
                continue
            while deficit > 0:
                count = min(deficit, truck.crew_capacity)
                if isfinite(available):
                    count = min(count, int(available))
                if count <= 0 or not self.provider.reserve_workers(count):
                    break
                self._make_trip(building, truck, CrewPayload(count), route)
                deficit -= count
                available -= count
