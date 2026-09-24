"""Provider contracts and road-side access for construction deliveries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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
from traffic_testbed import RoadVehicleSimulation, RoutedRoadVehicle
from units import pixels_per_second_to_mph
from vehicle import VehicleAppearance


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
CONSTRUCTION_TRUCK_DEPARTURE_INTERVAL = 20.0
DEPARTURE_TIME_TOLERANCE = 1e-9


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
    route: Path[MobilityNode, MobilityLink] | None = field(default=None, repr=False)
    road_vehicle: RoutedRoadVehicle | None = field(default=None, repr=False)

    @property
    def position(self) -> Point:
        if self.road_vehicle is not None:
            return self.road_vehicle.position
        return point_at_polyline_distance(
            list(self.route_points), self.distance_travelled,
        )

    @property
    def heading(self) -> Point:
        """Return the unit direction of the route segment under the truck."""
        if self.road_vehicle is not None:
            return self.road_vehicle.heading
        distance_remaining = max(0.0, self.distance_travelled)
        final_direction: Point | None = None
        for start, end in zip(self.route_points, self.route_points[1:]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            segment_length = hypot(dx, dy)
            if segment_length == 0:
                continue
            direction = (dx / segment_length, dy / segment_length)
            final_direction = direction
            if distance_remaining < segment_length:
                return direction
            distance_remaining -= segment_length
        return final_direction or (0.0, 1.0)


class ConstructionSimulation:
    """Dispatch routed material loads from current construction demand."""

    def __init__(
        self,
        resources: Mapping[str, ResourceSpec],
        trucks: Mapping[str, TruckSpec],
        provider: ConstructionProvider,
        truck_speed: float = CONSTRUCTION_TRUCK_SPEED,
        road_vehicles: RoadVehicleSimulation | None = None,
    ) -> None:
        if not isfinite(truck_speed) or truck_speed <= 0:
            raise ValueError("Construction truck speed must be positive and finite")
        self.resources = dict(resources)
        self.trucks = dict(trucks)
        self.provider = provider
        self.truck_speed = float(truck_speed)
        self.road_vehicles = road_vehicles if road_vehicles is not None else RoadVehicleSimulation(
            spawn_interval=1000.0,
            speed_mph=pixels_per_second_to_mph(truck_speed),
            update_mode="data_first",
        )
        self.trips: list[ConstructionTrip] = []
        self.pending_trips: list[ConstructionTrip] = []
        self.completed_road_vehicles: list[RoutedRoadVehicle] = []
        self._seconds_until_next_departure = 0.0
        self._city_map: CityMap | None = None
        self._network_token: tuple[int, int] | None = None
        self._material_delivery_counts: dict[tuple[str, str], int] = {}

    def update(
        self,
        city_map: CityMap,
        elapsed_seconds: float,
    ) -> tuple[ConstructionTrip, ...]:
        """Advance work, trips, and the shared regional-port departure queue."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Construction elapsed time must be finite and nonnegative")
        self._city_map = city_map
        self.completed_road_vehicles = []
        self.sync_network(city_map)
        completed: list[ConstructionTrip] = []
        self._start_ready_work(city_map)
        self._queue_outstanding_demand(city_map)
        self._depart_next_trip_if_ready()

        remaining = elapsed_seconds
        while remaining > 1e-9:
            self._depart_next_trip_if_ready()
            step = min(remaining, 0.05)
            if self.pending_trips and self._seconds_until_next_departure > 0:
                step = min(step, self._seconds_until_next_departure)
            self._advance_work(city_map, step)
            arrived_vehicles = self.road_vehicles.update(city_map, step)
            self.completed_road_vehicles.extend(arrived_vehicles)
            for trip in tuple(self.trips):
                if trip.road_vehicle is not None:
                    trip.distance_travelled = trip.road_vehicle.distance
                if trip.road_vehicle in arrived_vehicles:
                    self._apply_delivery(trip)
                    self.trips.remove(trip)
                    completed.append(trip)
            remaining = max(0.0, remaining - step)
            self._seconds_until_next_departure = max(
                0.0, self._seconds_until_next_departure - step,
            )
            if self._seconds_until_next_departure <= DEPARTURE_TIME_TOLERANCE:
                self._seconds_until_next_departure = 0.0
            self._start_ready_work(city_map)
            self._queue_outstanding_demand(city_map)
            self._depart_next_trip_if_ready()
        return tuple(completed)

    def sync_network(self, city_map: CityMap) -> list[RoutedRoadVehicle]:
        """Cancel deliveries whose saved routes use a replaced lane graph."""
        token = (id(city_map), city_map.mobility_revision)
        if self._network_token is not None and token != self._network_token:
            self.clear_trips()
        self._network_token = token
        _changed, removed = self.road_vehicles.sync_network(city_map)
        return removed

    def _advance_work(self, city_map: CityMap, elapsed_seconds: float) -> None:
        for building in city_map.buildings:
            if (
                elapsed_seconds > 0
                and building.active_work is not None
                and building.active_work.kind is WorkType.CONSTRUCTION
                and building.assigned_workers > 0
            ):
                if building.perform_work(building.assigned_workers * elapsed_seconds):
                    building.assigned_workers = 0

    def _start_ready_work(self, city_map: CityMap) -> None:
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

    def _queue_outstanding_demand(self, city_map: CityMap) -> None:
        self._dispatch_materials(city_map)
        self._dispatch_workers(city_map)

    def _depart_next_trip_if_ready(self) -> None:
        if (
            not self.pending_trips
            or self._seconds_until_next_departure > DEPARTURE_TIME_TOLERANCE
        ):
            return
        trip = self.pending_trips[0]
        if trip.route is None:
            raise ValueError("Construction trip has no mobility route")
        truck = self.trucks[trip.truck_id]
        vehicle = self.road_vehicles.admit_route(
            trip.route,
            vehicle_id=trip.id,
            source_id=trip.provider_id,
            destination_id=trip.building_id,
            appearance=self._appearance_for_trip(trip, truck),
            length=truck.length,
            width=truck.width,
            speed_cap_mph=pixels_per_second_to_mph(trip.speed),
            color="#d88c32",
        )
        if vehicle is None:
            return
        trip.road_vehicle = vehicle
        self.trips.append(self.pending_trips.pop(0))
        self._seconds_until_next_departure = CONSTRUCTION_TRUCK_DEPARTURE_INTERVAL

    def _appearance_for_trip(
        self, trip: ConstructionTrip, truck: TruckSpec,
    ) -> VehicleAppearance:
        if isinstance(trip.payload, CrewPayload):
            return VehicleAppearance(
                kind="construction_truck",
                shape="crew_truck",
                visual_key=truck.visual_key or truck.id,
                workers=trip.payload.workers,
            )
        resource = self.resources.get(trip.payload.resource_id)
        max_load = (
            min(
                truck.payload_kg / resource.mass_kg_per_unit,
                truck.cargo_m3 / resource.volume_m3_per_unit,
            )
            if resource is not None else 0.0
        )
        return VehicleAppearance(
            kind="construction_truck",
            shape="material_truck",
            visual_key=truck.visual_key or truck.id,
            cargo_key=(resource.visual_key or resource.id) if resource else trip.payload.resource_id,
            load_fraction=min(1.0, trip.payload.amount / max_load) if max_load > 0 else 0.0,
        )

    def _in_transit_material(self, building_id: str, resource_id: str) -> float:
        return sum(
            trip.payload.amount
            for trip in (*self.trips, *self.pending_trips)
            if trip.building_id == building_id
            and isinstance(trip.payload, MaterialPayload)
            and trip.payload.resource_id == resource_id
        )

    def _in_transit_workers(self, building_id: str) -> int:
        return sum(
            trip.payload.workers
            for trip in (*self.trips, *self.pending_trips)
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
            route=route,
        )
        self.pending_trips.append(trip)
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
            for trip in (*self.trips, *self.pending_trips)
        )
        delivery_count = self._material_delivery_counts.get(
            (building_id, resource_id), 0,
        )
        return ulp(required) * max(4, transit_count + delivery_count + 2)

    def clear_trips(self) -> None:
        """Discard runtime trips when the current city is replaced."""
        for trip in self.trips:
            self.road_vehicles.remove_vehicle(trip.id)
        self.trips.clear()
        self.pending_trips.clear()
        self.completed_road_vehicles.clear()
        self._seconds_until_next_departure = 0.0
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
