"""Provider contracts and road-side access for construction deliveries."""

from __future__ import annotations

from math import dist, hypot, inf
from typing import Protocol

from city import Building, CityMap, Parcel
from mobility import LanePosition, VehicleRouteEndpoint, nearest_lane_position
from models import Point


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
