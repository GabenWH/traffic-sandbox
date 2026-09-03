"""City-builder world data, kept separate from vehicle simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import dist
from random import Random
from uuid import uuid4

from mobility import (
    VEHICLE_LAYER,
    LanePosition,
    MobilityLink,
    MobilityNetwork,
    MobilityNode,
    VehicleRouteEndpoint,
    build_vehicle_layer,
    find_vehicle_route_between,
    lane_end_node,
    lane_start_node,
)
from models import (
    Buildable,
    CityInspectionProperty,
    CityObject,
    Intersection,
    IntersectionKind,
    Lane,
    Point,
    Road,
)
from pathfinding import Path


GEOMETRY_TOLERANCE = 1e-6
INTERSECTION_SNAP_DISTANCE = 12.0
MINIMUM_INTERSECTION_RADIUS = 24.0
INTERSECTION_CLEARANCE = 12.0
MINIMUM_CUL_DE_SAC_RADIUS = 20.0
CUL_DE_SAC_CLEARANCE = 8.0
TREE_CANOPY_RADIUS = 11.0


class ZoneType(StrEnum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    CIVIC = "civic"


@dataclass
class Terrain:
    """Terrain appearance for the buildable map."""

    grass_color: str = "#78b85a"
    trees: list[tuple[float, float]] = field(default_factory=list)

    @classmethod
    def starter_terrain(cls) -> "Terrain":
        """Create a repeatable, lightly wooded buildable landscape."""
        random = Random(41)
        return cls(trees=[(random.randrange(80, 4920), random.randrange(80, 3420)) for _ in range(180)])


@dataclass
class Parcel(CityObject):
    x: float
    y: float
    width: float
    height: float
    zone: ZoneType | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    inspection_title = "Parcel"

    def contains(self, position: Point) -> bool:
        return (
            self.x <= position[0] <= self.x + self.width
            and self.y <= position[1] <= self.y + self.height
        )

    def inspection_properties(self):
        return (
            *super().inspection_properties(),
            CityInspectionProperty("Zone", self.zone.value if self.zone is not None else "unassigned"),
            CityInspectionProperty("Width", self.width, "distance"),
            CityInspectionProperty("Height", self.height, "distance"),
        )

@dataclass
class Building(Buildable):
    name: str
    parcel: Parcel
    residents: int = 0
    jobs: int = 0
    buildable_id: str | None = None
    color: str = "#8b8580"
    id: str = field(default_factory=lambda: str(uuid4()))
    inspection_title = "Building"

    def contains(self, position: Point) -> bool:
        return self.parcel.contains(position)

    def inspection_properties(self):
        return (
            CityInspectionProperty("Name", self.name),
            *super().inspection_properties(),
            CityInspectionProperty("Template", self.buildable_id or "custom"),
            CityInspectionProperty("Zone", self.parcel.zone.value if self.parcel.zone else "unassigned"),
            CityInspectionProperty("Residents", self.residents),
            CityInspectionProperty("Jobs", self.jobs),
            CityInspectionProperty("Width", self.parcel.width, "distance"),
            CityInspectionProperty("Height", self.parcel.height, "distance"),
        )


@dataclass
class CityMap:
    """Own terrain and city objects; traffic uses its roads later."""

    width: float = 5000
    height: float = 3500
    terrain: Terrain = field(default_factory=Terrain.starter_terrain)
    roads: list[Road] = field(default_factory=list)
    intersections: list[Intersection] = field(default_factory=list)
    parcels: list[Parcel] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)
    mobility: MobilityNetwork = field(default_factory=MobilityNetwork, init=False, repr=False)

    def __post_init__(self) -> None:
        self.rebuild_mobility_network()

    def zone_parcel(self, parcel: Parcel, zone: ZoneType) -> None:
        parcel.zone = zone

    @property
    def cul_de_sacs(self) -> list[Intersection]:
        """Return cul-de-sac-shaped members of the generic intersection set."""
        return [
            intersection for intersection in self.intersections
            if intersection.kind is IntersectionKind.CUL_DE_SAC
        ]

    @property
    def standard_intersections(self) -> list[Intersection]:
        return [
            intersection for intersection in self.intersections
            if intersection.kind is IntersectionKind.STANDARD
        ]

    def add_road(
        self,
        centerline: list[tuple[float, float]],
        *,
        name: str | None = None,
        road_id: str | None = None,
        lane_width: float = 12.0,
        forward_lane_count: int = 1,
        reverse_lane_count: int = 1,
        buildable_id: str | None = None,
        lane_metadata: list[dict[str, object]] | None = None,
        create_intersections: bool = True,
    ) -> Road:
        """Create a road, splitting it and existing roads at crossings."""
        road = Road(
            id=road_id or str(uuid4()),
            name=name or f"Road {len(self.roads) + 1}",
            centerline=[(float(x), float(y)) for x, y in centerline],
            lane_width=float(lane_width),
            forward_lane_count=int(forward_lane_count),
            reverse_lane_count=int(reverse_lane_count),
            buildable_id=buildable_id,
        )
        road.rebuild_lanes(lane_metadata)
        if not create_intersections:
            self.roads.append(road)
            self.rebuild_mobility_network()
            return road

        crossings_by_road: dict[str, list[Point]] = {}
        crossing_points: list[Point] = []
        prospective_junction_radius = max(
            MINIMUM_INTERSECTION_RADIUS,
            road.width / 2 + INTERSECTION_CLEARANCE,
        )
        for intersection in self.intersections:
            collision_radius = intersection.radius + (
                road.width / 2
                if intersection.kind is IntersectionKind.CUL_DE_SAC
                else prospective_junction_radius
            )
            if road.distance_to(intersection.position) > collision_radius:
                continue
            _snap_road_centerline_to_point(
                road,
                intersection.position,
                collision_radius,
            )
            _append_unique(crossing_points, intersection.position)
        if crossing_points:
            road.rebuild_lanes(lane_metadata)

        snapped_groups: dict[str, list[Point]] = {}
        for existing in list(self.roads):
            for point in _road_crossings(road, existing):
                nearby = next(
                    (
                        intersection for intersection in self.intersections
                        if existing in intersection.connected_roads
                        and dist(intersection.position, point)
                        <= intersection.radius + (
                            road.width / 2
                            if intersection.kind is IntersectionKind.CUL_DE_SAC
                            else prospective_junction_radius
                        )
                    ),
                    None,
                )
                if nearby is None:
                    _append_unique(crossing_points, point)
                    existing_split_point = point
                else:
                    snapped_groups.setdefault(nearby.id, []).append(point)
                    existing_split_point = nearby.position
                _append_unique(
                    crossings_by_road.setdefault(existing.id, []),
                    existing_split_point,
                )

        for points in snapped_groups.values():
            average_progress = sum(_road_progress(road, point) for point in points) / len(points)
            _append_unique(crossing_points, _point_at_progress(road, average_progress))

        for existing in list(self.roads):
            points = crossings_by_road.get(existing.id, [])
            if not points:
                continue
            pieces = _split_at_points(existing, points)
            index = self.roads.index(existing)
            self.roads[index:index + 1] = pieces

        new_pieces = _split_at_points(road, crossing_points)
        self.roads.extend(new_pieces)
        for point in crossing_points:
            if not any(
                dist(candidate.position, point)
                <= max(
                    INTERSECTION_SNAP_DISTANCE,
                    candidate.radius + (
                        road.width / 2
                        if candidate.kind is IntersectionKind.CUL_DE_SAC
                        else prospective_junction_radius
                    ),
                )
                for candidate in self.intersections
            ):
                self.intersections.append(Intersection(str(uuid4()), point))

        self.rebuild_mobility_network()
        self._remove_trees_overlapping(road)
        return new_pieces[0]

    def _remove_trees_overlapping(self, road: Road) -> None:
        """Remove trees touched by the paved footprint of an authored road."""
        clearing_distance = road.width / 2 + TREE_CANOPY_RADIUS
        self.terrain.trees = [
            position for position in self.terrain.trees
            if road.distance_to(position) > clearing_distance
            and all(
                dist(position, junction.position) > junction.radius + TREE_CANOPY_RADIUS
                for junction in self.intersections
            )
        ]

    def rebuild_mobility_network(self) -> None:
        """Derive junction footprints, lane endpoints, and the vehicle layer."""
        lane_metadata = {
            road.id: [
                {
                    "name": lane.name,
                    "direction": lane.direction,
                    "index": lane.lane_index,
                    "following_gap": lane.following_gap,
                }
                for lane in road.lanes
            ]
            for road in self.roads
        }
        standard_intersections = [
            intersection for intersection in self.intersections
            if intersection.kind is IntersectionKind.STANDARD
        ]
        cul_de_sacs = [
            intersection for intersection in self.intersections
            if intersection.kind is IntersectionKind.CUL_DE_SAC
        ]
        for intersection in standard_intersections:
            intersection.connected_roads = [
                road for road in self.roads
                if any(
                    dist(intersection.position, endpoint) <= INTERSECTION_SNAP_DISTANCE
                    for endpoint in (road.centerline[0], road.centerline[-1])
                )
            ]
            intersection.radius = max(
                MINIMUM_INTERSECTION_RADIUS,
                *(
                    road.width / 2
                    + INTERSECTION_CLEARANCE
                    + min(dist(intersection.position, endpoint) for endpoint in (
                        road.centerline[0], road.centerline[-1],
                    ))
                    for road in intersection.connected_roads
                ),
            )

        endpoint_junctions: dict[tuple[str, bool], Intersection] = {}
        free_endpoints: list[tuple[Road, bool, Point]] = []
        for road in self.roads:
            for at_start, endpoint in (
                (True, road.centerline[0]),
                (False, road.centerline[-1]),
            ):
                junction = min(
                    (
                        intersection
                        for intersection in standard_intersections
                        if road in intersection.connected_roads
                        and dist(intersection.position, endpoint) <= INTERSECTION_SNAP_DISTANCE
                    ),
                    key=lambda intersection: dist(intersection.position, endpoint),
                    default=None,
                )
                if junction is not None:
                    endpoint_junctions[(road.id, at_start)] = junction
                else:
                    free_endpoints.append((road, at_start, endpoint))

        for road, at_start, endpoint in free_endpoints:
            supports_turnaround = (
                road.forward_lane_count > 0 and road.reverse_lane_count > 0
            )
            if not supports_turnaround:
                continue
            if any(
                dist(cul_de_sac.position, endpoint) <= INTERSECTION_SNAP_DISTANCE
                for cul_de_sac in cul_de_sacs
            ):
                continue
            cul_de_sacs.append(Intersection(
                id=f"cul_de_sac:{road.id}:{'start' if at_start else 'end'}",
                position=endpoint,
                kind=IntersectionKind.CUL_DE_SAC,
            ))

        for cul_de_sac in cul_de_sacs:
            cul_de_sac.connected_roads = []
        for road, at_start, endpoint in free_endpoints:
            cul_de_sac = min(
                (
                    candidate for candidate in cul_de_sacs
                    if dist(candidate.position, endpoint) <= INTERSECTION_SNAP_DISTANCE
                ),
                key=lambda candidate: dist(candidate.position, endpoint),
                default=None,
            )
            if cul_de_sac is None:
                continue
            endpoint_junctions[(road.id, at_start)] = cul_de_sac
            if not any(road is connected for connected in cul_de_sac.connected_roads):
                cul_de_sac.connected_roads.append(road)

        cul_de_sacs = [
            cul_de_sac for cul_de_sac in cul_de_sacs
            if cul_de_sac.connected_roads
            and any(
                road.forward_lane_count > 0 and road.reverse_lane_count > 0
                for road in cul_de_sac.connected_roads
            )
        ]
        for cul_de_sac in cul_de_sacs:
            cul_de_sac.radius = max(
                MINIMUM_CUL_DE_SAC_RADIUS,
                *(
                    road.width / 2
                    + CUL_DE_SAC_CLEARANCE
                    + min(
                        dist(cul_de_sac.position, road.centerline[0]),
                        dist(cul_de_sac.position, road.centerline[-1]),
                    )
                    for road in cul_de_sac.connected_roads
                ),
            )
        self.intersections = [*standard_intersections, *cul_de_sacs]

        endpoint_radii: dict[tuple[str, bool], float] = {}
        for road in self.roads:
            for at_start in (True, False):
                junction = endpoint_junctions.get((road.id, at_start))
                endpoint_radii[(road.id, at_start)] = (
                    junction.radius if junction is not None else 0.0
                )
            road.rebuild_lanes(
                lane_metadata.get(road.id),
                start_setback=endpoint_radii[(road.id, True)],
                end_setback=endpoint_radii[(road.id, False)],
            )

        for intersection in self.intersections:
            intersection.rebuild_lane_connections(INTERSECTION_SNAP_DISTANCE)
        self._rebuild_vehicle_layer()

    def _rebuild_vehicle_layer(self) -> None:
        self.mobility.set_layer(
            VEHICLE_LAYER,
            build_vehicle_layer(self.roads, self.intersections),
        )

    def find_vehicle_route(
        self,
        start_lane: Lane,
        destination_lane: Lane,
    ) -> Path[MobilityNode, MobilityLink] | None:
        """Find the shortest directed lane/connection path between two lanes."""
        if not isinstance(start_lane, Lane) or not isinstance(destination_lane, Lane):
            raise TypeError("Vehicle routes require Lane objects")
        return self.mobility.find_path(
            lane_start_node(start_lane),
            lane_end_node(destination_lane),
            layer_names=(VEHICLE_LAYER,),
            use_distance_heuristic=True,
        )

    def find_vehicle_route_between(
        self,
        start: VehicleRouteEndpoint,
        destination: VehicleRouteEndpoint,
    ) -> Path[MobilityNode, MobilityLink] | None:
        """Route between precise lane positions or selected junctions."""
        current_lanes = {id(lane) for road in self.roads for lane in road.lanes}
        for endpoint in (start, destination):
            if isinstance(endpoint, LanePosition):
                if id(endpoint.lane) not in current_lanes:
                    raise ValueError("Vehicle route positions must use lanes in this city")
            elif (
                not any(endpoint is candidate for candidate in self.intersections)
            ):
                raise ValueError("Vehicle route junctions must belong to this city")
        return find_vehicle_route_between(self.mobility, start, destination)


def _append_unique(points: list[Point], point: Point) -> None:
    if not any(dist(existing, point) <= GEOMETRY_TOLERANCE for existing in points):
        points.append(point)


def _snap_road_centerline_to_point(
    road: Road,
    target: Point,
    collision_radius: float,
) -> None:
    """Route a colliding authored centerline through an existing junction."""
    points = list(road.centerline)
    endpoint_indexes = [
        index for index in (0, len(points) - 1)
        if dist(points[index], target) <= collision_radius
    ]
    if endpoint_indexes:
        index = min(endpoint_indexes, key=lambda candidate: dist(points[candidate], target))
        points[index] = target
    else:
        closest: tuple[float, int, float] | None = None
        for index, (start, end) in enumerate(zip(points, points[1:])):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_squared = dx ** 2 + dy ** 2
            if length_squared == 0:
                continue
            fraction = (
                (target[0] - start[0]) * dx + (target[1] - start[1]) * dy
            ) / length_squared
            fraction = max(0.0, min(1.0, fraction))
            projected = (start[0] + dx * fraction, start[1] + dy * fraction)
            candidate = (dist(projected, target), index, fraction)
            if closest is None or candidate[0] < closest[0]:
                closest = candidate
        if closest is None:
            raise ValueError("A road centerline needs a non-degenerate segment")
        _distance, index, fraction = closest
        if fraction <= GEOMETRY_TOLERANCE:
            points[index] = target
        elif fraction >= 1 - GEOMETRY_TOLERANCE:
            points[index + 1] = target
        else:
            points.insert(index + 1, target)

    road.centerline = [
        point
        for index, point in enumerate(points)
        if index == 0 or dist(point, points[index - 1]) > GEOMETRY_TOLERANCE
    ]
    if len(road.centerline) < 2:
        raise ValueError("A road cannot lie entirely inside an intersection")


def _segment_intersection(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> Point | None:
    """Return the bounded crossing of two non-collinear line segments."""
    first_x, first_y = first_end[0] - first_start[0], first_end[1] - first_start[1]
    second_x, second_y = second_end[0] - second_start[0], second_end[1] - second_start[1]
    denominator = first_x * second_y - first_y * second_x
    if abs(denominator) <= GEOMETRY_TOLERANCE:
        return None
    offset_x = second_start[0] - first_start[0]
    offset_y = second_start[1] - first_start[1]
    first_progress = (offset_x * second_y - offset_y * second_x) / denominator
    second_progress = (offset_x * first_y - offset_y * first_x) / denominator
    if not (
        -GEOMETRY_TOLERANCE <= first_progress <= 1 + GEOMETRY_TOLERANCE
        and -GEOMETRY_TOLERANCE <= second_progress <= 1 + GEOMETRY_TOLERANCE
    ):
        return None
    return (
        first_start[0] + max(0.0, min(1.0, first_progress)) * first_x,
        first_start[1] + max(0.0, min(1.0, first_progress)) * first_y,
    )


def _road_crossings(first: Road, second: Road) -> list[Point]:
    points: list[Point] = []
    for first_segment in zip(first.centerline, first.centerline[1:]):
        for second_segment in zip(second.centerline, second.centerline[1:]):
            point = _segment_intersection(*first_segment, *second_segment)
            if point is not None:
                _append_unique(points, point)
    return points


def _split_at_points(road: Road, points: list[Point]) -> list[Road]:
    """Split a road at every distinct interior point, in centreline order."""
    ordered = sorted(points, key=lambda point: _road_progress(road, point))
    pieces = [road]
    for point in ordered:
        for index, piece in enumerate(pieces):
            if any(
                dist(point, endpoint) <= GEOMETRY_TOLERANCE
                for endpoint in (piece.centerline[0], piece.centerline[-1])
            ):
                break
            if piece.distance_to(point) <= GEOMETRY_TOLERANCE:
                pieces[index:index + 1] = piece.split(point, GEOMETRY_TOLERANCE)
                break
    return pieces


def _road_progress(road: Road, point: Point) -> float:
    """Return cumulative centreline distance to a point on a road."""
    travelled = 0.0
    for start, end in zip(road.centerline, road.centerline[1:]):
        segment_length = dist(start, end)
        if segment_length == 0:
            continue
        if _point_on_segment(point, start, end):
            return travelled + dist(start, point)
        travelled += segment_length
    return travelled


def _point_at_progress(road: Road, progress: float) -> Point:
    """Return a point at cumulative distance along a road centreline."""
    remaining = progress
    for start, end in zip(road.centerline, road.centerline[1:]):
        segment_length = dist(start, end)
        if segment_length == 0:
            continue
        if remaining <= segment_length:
            ratio = max(0.0, remaining / segment_length)
            return (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
        remaining -= segment_length
    return road.centerline[-1]


def _point_on_segment(point: Point, start: Point, end: Point) -> bool:
    return abs(dist(start, point) + dist(point, end) - dist(start, end)) <= GEOMETRY_TOLERANCE
