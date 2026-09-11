"""Traffic data objects and geometry helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import atan2, dist, hypot, isfinite, pi, sqrt
from uuid import uuid4


Point = tuple[float, float]


@dataclass(frozen=True)
class CityInspectionProperty:
    """One model-owned property exposed to the city Inspector."""

    label: str
    value: object
    unit: str | None = None
    target: object | None = None


class CityObject:
    """Base contract for persistent objects that can be inspected in a city."""

    id: str
    inspection_title = "City object"

    def inspection_properties(self) -> tuple[CityInspectionProperty, ...]:
        return (CityInspectionProperty("ID", self.id),)


class ConsumptionState(StrEnum):
    """How completely an inventory request was fulfilled."""

    FAILED = "failed"
    PARTIAL = "partial"
    FULL = "full"


class BuildablePhase(StrEnum):
    """The persistent lifecycle phase of constructed city infrastructure."""

    PLANNING = "planning"
    UNDER_CONSTRUCTION = "under_construction"
    OPERATIONAL = "operational"
    DECOMMISSIONED = "decommissioned"
    DEMOLISHING = "demolishing"


class WorkType(StrEnum):
    """A temporary job that can act on a buildable."""

    CONSTRUCTION = "construction"
    MAINTENANCE = "maintenance"
    UPGRADE = "upgrade"
    DEMOLITION = "demolition"


@dataclass
class ResourceInventory:
    """A resource buffer used for construction, operation, and maintenance."""

    amounts: dict[str, float] = field(default_factory=dict)

    def add(self, resource: str, amount: float) -> None:
        resource = resource.strip()
        if not resource:
            raise ValueError("Resource names cannot be empty")
        if not isfinite(amount) or amount <= 0:
            raise ValueError("Resource additions must be positive")
        self.amounts[resource] = self.amounts.get(resource, 0.0) + float(amount)

    def consume(self, resource: str, amount: float) -> tuple[ConsumptionState, float]:
        resource = resource.strip()
        if not resource:
            raise ValueError("Resource names cannot be empty")
        if not isfinite(amount) or amount <= 0:
            raise ValueError("Resource consumption must be positive")
        available = self.amounts.get(resource, 0.0)
        consumed = min(available, float(amount))
        remaining = available - consumed
        if remaining > 0:
            self.amounts[resource] = remaining
        else:
            self.amounts.pop(resource, None)
        if consumed == 0:
            return ConsumptionState.FAILED, 0.0
        if consumed < amount:
            return ConsumptionState.PARTIAL, consumed
        return ConsumptionState.FULL, consumed

    def scaled(self, fraction: float) -> ResourceInventory:
        if not isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError("Inventory scale must be between zero and one")
        return ResourceInventory({resource: amount * fraction for resource, amount in self.amounts.items()})


@dataclass
class WorkOrder:
    """Progress for construction, maintenance, upgrades, or demolition."""

    kind: WorkType
    required_work: float
    completed_work: float = 0.0
    stage_index: int = 0

    def __post_init__(self) -> None:
        if not isfinite(self.required_work) or self.required_work <= 0:
            raise ValueError("Required work must be positive")
        if not isfinite(self.completed_work) or not 0 <= self.completed_work <= self.required_work:
            raise ValueError("Completed work must be between zero and required work")
        if self.stage_index < 0:
            raise ValueError("Work stage cannot be negative")

    @property
    def is_complete(self) -> bool:
        return self.completed_work >= self.required_work

    @property
    def progress(self) -> float:
        if self.required_work <= 0:
            return 1.0
        return min(1.0, self.completed_work / self.required_work)

    def add_work(self, amount: float) -> float:
        if not isfinite(amount) or amount <= 0:
            raise ValueError("Work additions must be positive")
        accepted = min(float(amount), max(0.0, self.required_work - self.completed_work))
        self.completed_work += accepted
        return accepted

    def scaled(self, fraction: float) -> WorkOrder:
        if not isfinite(fraction) or not 0 < fraction <= 1:
            raise ValueError("Work scale must be greater than zero and at most one")
        return WorkOrder(
            kind=self.kind,
            required_work=self.required_work * fraction,
            completed_work=self.completed_work * fraction,
            stage_index=self.stage_index,
        )


@dataclass(kw_only=True)
class Buildable(CityObject):
    """Shared economic and lifecycle state for roads, buildings, and utilities."""

    phase: BuildablePhase = BuildablePhase.PLANNING
    inventory: ResourceInventory = field(default_factory=ResourceInventory)
    condition: float = 1.0
    active_work: WorkOrder | None = None

    def add_resource(self, resource: str, amount: float) -> None:
        """Add a delivered resource to this buildable's local inventory."""
        self.inventory.add(resource, amount)

    def consume_resource(self, resource: str, amount: float) -> tuple[ConsumptionState, float]:
        """Consume as much of a requested resource as is locally available."""
        return self.inventory.consume(resource, amount)

    def begin_work(self, kind: WorkType, required_work: float) -> WorkOrder:
        if self.active_work is not None:
            raise ValueError("This buildable already has active work")
        if not isfinite(required_work) or required_work <= 0:
            raise ValueError("Required work must be positive")
        self.active_work = WorkOrder(kind, float(required_work))
        if kind is WorkType.CONSTRUCTION:
            self.phase = BuildablePhase.UNDER_CONSTRUCTION
        elif kind is WorkType.DEMOLITION:
            self.phase = BuildablePhase.DEMOLISHING
        return self.active_work

    def perform_work(self, amount: float) -> bool:
        if self.active_work is None:
            raise ValueError("This buildable has no active work")
        work = self.active_work
        work.add_work(amount)
        if not work.is_complete:
            return False
        if work.kind in (WorkType.CONSTRUCTION, WorkType.UPGRADE):
            self.phase = BuildablePhase.OPERATIONAL
        elif work.kind is WorkType.DEMOLITION:
            self.phase = BuildablePhase.DECOMMISSIONED
        self.active_work = None
        return True

    def inspection_properties(self) -> tuple[CityInspectionProperty, ...]:
        work = "none"
        if self.active_work is not None:
            work = f"{self.active_work.kind.value} ({self.active_work.progress:.0%})"
        properties = [
            CityInspectionProperty("ID", self.id),
            CityInspectionProperty("Phase", self.phase.value),
            CityInspectionProperty("Condition", f"{self.condition:.0%}"),
            CityInspectionProperty("Active work", work),
            CityInspectionProperty("Stored resources", len(self.inventory.amounts)),
        ]
        properties.extend(
            CityInspectionProperty(f"Inventory: {resource}", amount)
            for resource, amount in sorted(self.inventory.amounts.items())
        )
        return tuple(properties)


class ManeuverType(StrEnum):
    """Geometric kind of travel represented by a lane connection."""

    THROUGH = "through"
    LEFT_TURN = "left_turn"
    RIGHT_TURN = "right_turn"
    U_TURN = "u_turn"
    MERGE = "merge"
    DIVERGE = "diverge"


class ControlType(StrEnum):
    """Rule governing entry into a lane connection."""

    UNCONTROLLED = "uncontrolled"
    YIELD = "yield"
    STOP = "stop"
    SIGNAL = "signal"


class IntersectionKind(StrEnum):
    """Geometry and movement policy used by a generic road junction."""

    STANDARD = "standard"
    ROUNDABOUT = "roundabout"
    CUL_DE_SAC = "cul_de_sac"


class RoadEnd(StrEnum):
    """Which authored endpoint owns a road routing port."""

    START = "start"
    END = "end"


class RoadPortFlow(StrEnum):
    """Whether traffic enters or leaves a road through a routing port."""

    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True)
class ManeuverDefinition:
    """Serializable maneuver data that behavior systems can interpret."""

    kind: ManeuverType
    angle: float = 0.0  # signed radians; positive turns right in screen coordinates


@dataclass(frozen=True)
class ControlDefinition:
    """Serializable entry-control data, separate from maneuver geometry."""

    kind: ControlType = ControlType.UNCONTROLLED
    controller_id: str | None = None


def distance_to_polyline(points: list[Point], position: Point) -> float:
    """Return the shortest distance between a point and a polyline."""
    closest = float("inf")
    for start, end in zip(points, points[1:]):
        segment_x, segment_y = end[0] - start[0], end[1] - start[1]
        segment_length_squared = segment_x ** 2 + segment_y ** 2
        if segment_length_squared == 0:
            closest = min(closest, dist(position, start))
            continue
        progress = (
            (position[0] - start[0]) * segment_x
            + (position[1] - start[1]) * segment_y
        ) / segment_length_squared
        progress = max(0.0, min(1.0, progress))
        nearest = (start[0] + progress * segment_x, start[1] + progress * segment_y)
        closest = min(closest, dist(position, nearest))
    return closest


def polyline_length(points: list[Point]) -> float:
    """Return cumulative length along a polyline."""
    return sum(dist(start, end) for start, end in zip(points, points[1:]))


def point_at_polyline_distance(points: list[Point], distance: float) -> Point:
    """Return the point at a clamped cumulative distance along a polyline."""
    if not points:
        raise ValueError("A polyline needs at least one point")
    remaining = max(0.0, float(distance))
    for start, end in zip(points, points[1:]):
        segment_length = dist(start, end)
        if segment_length == 0:
            continue
        if remaining <= segment_length:
            fraction = remaining / segment_length
            return (
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
        remaining -= segment_length
    return points[-1]


def slice_polyline(points: list[Point], start_distance: float, end_distance: float) -> list[Point]:
    """Return forward polyline geometry between two cumulative distances."""
    total = polyline_length(points)
    start_distance = max(0.0, min(total, float(start_distance)))
    end_distance = max(start_distance, min(total, float(end_distance)))
    start = point_at_polyline_distance(points, start_distance)
    end = point_at_polyline_distance(points, end_distance)
    result = [start]
    travelled = 0.0
    for point, next_point in zip(points, points[1:]):
        travelled += dist(point, next_point)
        if start_distance < travelled < end_distance:
            result.append(next_point)
    if dist(result[-1], end) > 1e-9 or len(result) == 1:
        result.append(end)
    return result


def trim_polyline(points: list[Point], start_distance: float, end_distance: float) -> list[Point]:
    """Trim distances from both ends while retaining a usable polyline."""
    total = polyline_length(points)
    if total <= 0:
        raise ValueError("A polyline must have positive length")
    start_distance = max(0.0, float(start_distance))
    end_distance = max(0.0, float(end_distance))
    requested = start_distance + end_distance
    maximum = total * 0.9
    if requested > maximum and requested > 0:
        scale = maximum / requested
        start_distance *= scale
        end_distance *= scale
    return slice_polyline(points, start_distance, total - end_distance)


@dataclass
class Lane:
    """An ordered centre-line for traffic, ending at an exit point."""

    name: str
    points: list[Point]
    exit: Point
    following_gap: float = 85.0
    next_lane: str | None = None
    road_id: str | None = None
    direction: str = "forward"
    lane_index: int = 0

    @property
    def id(self) -> str:
        """Return the lane's structural address, never an independent UUID."""
        parent = self.road_id if self.road_id is not None else self.name
        return f"{parent}:{self.direction}:{self.lane_index}"

    def nearest_point_index(self, position: Point) -> int:
        return min(range(len(self.points)), key=lambda index: dist(position, self.points[index]))

    def distance_to(self, position: Point) -> float:
        """Return the shortest distance from a point to this lane centre-line."""
        return distance_to_polyline(self.points, position)


@dataclass
class SpeedLimit:
    """A posted speed limit that applies from its position onward in one lane."""

    speed: float  # miles per hour
    lane: Lane
    x: float
    y: float


def offset_polyline(points: list[Point], offset: float) -> list[Point]:
    """Return an averaged-normal offset of ``points`` for a lane centreline."""
    if len(points) < 2:
        raise ValueError("A polyline needs at least two points")
    normals: list[Point] = []
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = hypot(dx, dy)
        if length == 0:
            raise ValueError("Adjacent polyline points must be different")
        normals.append((-dy / length, dx / length))

    result: list[Point] = []
    for index, point in enumerate(points):
        if index == 0:
            normal = normals[0]
        elif index == len(points) - 1:
            normal = normals[-1]
        else:
            summed_x = normals[index - 1][0] + normals[index][0]
            summed_y = normals[index - 1][1] + normals[index][1]
            length = hypot(summed_x, summed_y)
            normal = normals[index] if length < 1e-9 else (summed_x / length, summed_y / length)
        result.append((point[0] + normal[0] * offset, point[1] + normal[1] * offset))
    return result


@dataclass
class Road(Buildable):
    """An authored centreline with generated child lanes."""

    id: str
    name: str
    centerline: list[Point]
    lane_width: float = 12.0
    forward_lane_count: int = 1
    reverse_lane_count: int = 1
    buildable_id: str | None = None
    lanes: list[Lane] = field(default_factory=list)
    inspection_title = "Road"

    @property
    def width(self) -> float:
        return self.lane_width * (self.forward_lane_count + self.reverse_lane_count)

    @property
    def route_inputs(self) -> tuple[RoadPort, ...]:
        """Geometric points through which traffic enters this road segment."""
        return tuple(
            port
            for end in RoadEnd
            if (port := self._route_port(end, RoadPortFlow.INPUT)) is not None
        )

    @property
    def route_outputs(self) -> tuple[RoadPort, ...]:
        """Geometric points through which traffic leaves this road segment."""
        return tuple(
            port
            for end in RoadEnd
            if (port := self._route_port(end, RoadPortFlow.OUTPUT)) is not None
        )

    def _route_port(self, end: RoadEnd, flow: RoadPortFlow) -> RoadPort | None:
        at_start = end is RoadEnd.START
        if flow is RoadPortFlow.INPUT:
            direction = "forward" if at_start else "reverse"
            lane_points = [(lane, lane.points[0]) for lane in self.lanes]
            headings = [
                _unit_vector(lane.points[0], lane.points[1])
                for lane in self.lanes
                if lane.direction == direction
            ]
        else:
            direction = "reverse" if at_start else "forward"
            lane_points = [(lane, lane.points[-1]) for lane in self.lanes]
            headings = [
                _unit_vector(lane.points[-2], lane.points[-1])
                for lane in self.lanes
                if lane.direction == direction
            ]
        selected = tuple(
            (lane, point) for lane, point in lane_points if lane.direction == direction
        )
        if not selected:
            return None
        point = (
            sum(item[1][0] for item in selected) / len(selected),
            sum(item[1][1] for item in selected) / len(selected),
        )
        heading_x = sum(item[0] for item in headings)
        heading_y = sum(item[1] for item in headings)
        heading_length = hypot(heading_x, heading_y)
        heading = (heading_x / heading_length, heading_y / heading_length)
        return RoadPort(
            road=self,
            end=end,
            flow=flow,
            position=point,
            heading=heading,
            width=len(selected) * self.lane_width,
            lanes=tuple(item[0] for item in selected),
        )

    def distance_to(self, position: Point) -> float:
        """Return the distance from a point to the authored centreline."""
        return distance_to_polyline(self.centerline, position)

    def split(self, position: Point, tolerance: float = 1e-6) -> tuple[Road, Road]:
        """Return two valid road segments split at an interior centreline point.

        The segment containing the original start retains this road's ID.
        """
        split_index: int | None = None
        split_point: Point | None = None
        for index, (start, end) in enumerate(zip(self.centerline, self.centerline[1:])):
            segment_x, segment_y = end[0] - start[0], end[1] - start[1]
            length_squared = segment_x ** 2 + segment_y ** 2
            if length_squared == 0:
                continue
            progress = (
                (position[0] - start[0]) * segment_x
                + (position[1] - start[1]) * segment_y
            ) / length_squared
            if not -tolerance <= progress <= 1 + tolerance:
                continue
            progress = max(0.0, min(1.0, progress))
            nearest = (
                start[0] + progress * segment_x,
                start[1] + progress * segment_y,
            )
            if dist(position, nearest) <= tolerance:
                split_index = index
                split_point = nearest
                break
        if split_index is None or split_point is None:
            raise ValueError("Split point must lie on the road centreline")
        if (
            dist(split_point, self.centerline[0]) <= tolerance
            or dist(split_point, self.centerline[-1]) <= tolerance
        ):
            raise ValueError("Split point must be inside the road, not at an endpoint")

        start, end = self.centerline[split_index:split_index + 2]
        if dist(split_point, start) <= tolerance:
            left_points = self.centerline[:split_index + 1]
            right_points = self.centerline[split_index:]
        elif dist(split_point, end) <= tolerance:
            left_points = self.centerline[:split_index + 2]
            right_points = self.centerline[split_index + 1:]
        else:
            left_points = [*self.centerline[:split_index + 1], split_point]
            right_points = [split_point, *self.centerline[split_index + 1:]]

        left_length = sum(dist(a, b) for a, b in zip(left_points, left_points[1:]))
        right_length = sum(dist(a, b) for a, b in zip(right_points, right_points[1:]))
        first_fraction = left_length / (left_length + right_length)
        second_fraction = 1.0 - first_fraction

        first = Road(
            id=self.id,
            name=self.name,
            centerline=left_points,
            lane_width=self.lane_width,
            forward_lane_count=self.forward_lane_count,
            reverse_lane_count=self.reverse_lane_count,
            buildable_id=self.buildable_id,
            phase=self.phase,
            inventory=self.inventory.scaled(first_fraction),
            condition=self.condition,
            active_work=(
                self.active_work.scaled(first_fraction) if self.active_work is not None else None
            ),
        )
        first.rebuild_lanes([
            {
                "name": lane.name,
                "direction": lane.direction,
                "index": lane.lane_index,
                "following_gap": lane.following_gap,
            }
            for lane in self.lanes
        ])
        second = Road(
            id=str(uuid4()),
            name=self.name,
            centerline=right_points,
            lane_width=self.lane_width,
            forward_lane_count=self.forward_lane_count,
            reverse_lane_count=self.reverse_lane_count,
            buildable_id=self.buildable_id,
            phase=self.phase,
            inventory=self.inventory.scaled(second_fraction),
            condition=self.condition,
            active_work=(
                self.active_work.scaled(second_fraction) if self.active_work is not None else None
            ),
        )
        second.rebuild_lanes()
        return first, second

    def inspection_properties(self) -> tuple[CityInspectionProperty, ...]:
        properties = [
            CityInspectionProperty("Name", self.name),
            *super().inspection_properties(),
            CityInspectionProperty("Template", self.buildable_id or "custom"),
            CityInspectionProperty("Lanes", len(self.lanes)),
            CityInspectionProperty("Forward lanes", self.forward_lane_count),
            CityInspectionProperty("Reverse lanes", self.reverse_lane_count),
            CityInspectionProperty("Route inputs", len(self.route_inputs)),
            CityInspectionProperty("Route outputs", len(self.route_outputs)),
            CityInspectionProperty("Lane width", self.lane_width, "distance"),
            CityInspectionProperty("Total width", self.width, "distance"),
            CityInspectionProperty("Centreline points", len(self.centerline)),
        ]
        properties.extend(
            CityInspectionProperty(
                f"{lane.direction.title()} lane {lane.lane_index + 1}",
                lane.name,
                target=lane,
            )
            for lane in self.lanes
        )
        return tuple(properties)

    def rebuild_lanes(
        self,
        lane_metadata: list[dict[str, object]] | None = None,
        *,
        start_setback: float = 0.0,
        end_setback: float = 0.0,
    ) -> None:
        """Regenerate child lane paths, optionally retaining lane metadata."""
        if len(self.centerline) < 2:
            raise ValueError("A road needs at least two centreline points")
        if self.forward_lane_count < 0 or self.reverse_lane_count < 0:
            raise ValueError("Lane counts cannot be negative")
        total = self.forward_lane_count + self.reverse_lane_count
        if total < 1:
            raise ValueError("A road needs at least one lane")
        if self.lane_width <= 0:
            raise ValueError("Lane width must be positive")

        saved = lane_metadata or []
        metadata_by_key = {
            (str(item.get("direction")), int(item.get("index", 0))): item
            for item in saved
        }
        lanes: list[Lane] = []
        for direction, count, start_slot in (
            ("forward", self.forward_lane_count, self.reverse_lane_count),
            ("reverse", self.reverse_lane_count, 0),
        ):
            for lane_index in range(count):
                slot = start_slot + lane_index
                offset = (slot - (total - 1) / 2) * self.lane_width
                points = offset_polyline(self.centerline, offset)
                lane_start_setback = sqrt(max(0.0, start_setback ** 2 - offset ** 2))
                lane_end_setback = sqrt(max(0.0, end_setback ** 2 - offset ** 2))
                if direction == "reverse":
                    points.reverse()
                    points = trim_polyline(
                        points, lane_end_setback, lane_start_setback,
                    )
                else:
                    points = trim_polyline(
                        points, lane_start_setback, lane_end_setback,
                    )
                details = metadata_by_key.get((direction, lane_index), {})
                default_name = f"{self.name} {direction} {lane_index + 1}"
                lanes.append(Lane(
                    name=str(details.get("name", default_name)),
                    points=points,
                    exit=points[-1],
                    following_gap=float(details.get("following_gap", 85.0)),
                    road_id=self.id,
                    direction=direction,
                    lane_index=lane_index,
                ))
        self.lanes = lanes


@dataclass(frozen=True, eq=False)
class RoadPort:
    """A derived directional routing interface across one end of a road."""

    road: Road
    end: RoadEnd
    flow: RoadPortFlow
    position: Point
    heading: Point
    width: float
    lanes: tuple[Lane, ...] = field(compare=False, repr=False)

    @property
    def id(self) -> str:
        return f"{self.road.id}:{self.end.value}:{self.flow.value}"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.road.id, self.end.value, self.flow.value)

    @property
    def geometric_key(self) -> tuple[str, float, float, float, float]:
        """Match an unchanged physical port even if its segment was split."""
        return (
            self.flow.value,
            round(self.position[0], 9),
            round(self.position[1], 9),
            round(self.heading[0], 9),
            round(self.heading[1], 9),
        )

    def __hash__(self) -> int:
        return hash(self.key)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RoadPort) and self.key == other.key


@dataclass
class LaneConnection(CityObject):
    """A directed, behavior-bearing path from a road output to a road input."""

    intersection_id: str
    source_output: RoadPort
    destination_input: RoadPort
    path: list[Point]
    maneuver: ManeuverDefinition
    control: ControlDefinition = field(default_factory=ControlDefinition)
    # Generated entrance/exit connectors use ordinary movement data, with an
    # extra role for signals and a shared target lane for generic merge checks.
    roundabout_role: str = ""
    merge_target: tuple[str, str] | None = None
    control_offset: float = 0.0  # Distance into the connector to its yield line.
    inspection_title = "Lane connection"

    @property
    def id(self) -> str:
        return (
            f"{self.intersection_id}:"
            f"{self.source_output.id}->{self.destination_input.id}"
            f"{':' + self.roundabout_role if self.roundabout_role else ''}"
        )

    @property
    def length(self) -> float:
        return sum(dist(start, end) for start, end in zip(self.path, self.path[1:]))

    def inspection_properties(self) -> tuple[CityInspectionProperty, ...]:
        return (
            CityInspectionProperty("ID", self.id),
            CityInspectionProperty(
                "From", self.source_output.road.name, target=self.source_output.road,
            ),
            CityInspectionProperty(
                "To", self.destination_input.road.name, target=self.destination_input.road,
            ),
            CityInspectionProperty("Maneuver", self.maneuver.kind.value),
            CityInspectionProperty("Control", self.control.kind.value),
            CityInspectionProperty("Length", self.length, "distance"),
        )


@dataclass
class Intersection(CityObject):
    """An explicit junction joining road segments at one world position."""

    id: str
    position: Point
    connected_roads: list[Road] = field(default_factory=list)
    lane_connections: list[LaneConnection] = field(default_factory=list)
    radius: float = 24.0
    kind: IntersectionKind = IntersectionKind.STANDARD

    @property
    def inspection_title(self) -> str:
        if self.kind is IntersectionKind.ROUNDABOUT:
            return "Roundabout"
        return "Cul-de-sac" if self.kind is IntersectionKind.CUL_DE_SAC else "Intersection"

    def incoming_ports(self) -> list[RoadPort]:
        """Return road outputs through which traffic enters this junction."""
        return [
            port
            for road in self.connected_roads
            for port in road.route_outputs
            if port.end is self._road_end_at_junction(road)
        ]

    def outgoing_ports(self) -> list[RoadPort]:
        """Return road inputs through which traffic leaves this junction."""
        return [
            port
            for road in self.connected_roads
            for port in road.route_inputs
            if port.end is self._road_end_at_junction(road)
        ]

    @property
    def is_all_way_stop(self) -> bool:
        """Whether every generated movement requires a stop."""
        return bool(self.lane_connections) and all(
            connection.control.kind is ControlType.STOP
            for connection in self.lane_connections
        )

    def set_all_way_stop(self, enabled: bool) -> None:
        """Apply one all-way-stop policy across this standard junction."""
        if self.kind is not IntersectionKind.STANDARD:
            raise ValueError("All-way stops require a standard intersection.")
        control = ControlDefinition(
            ControlType.STOP if enabled else ControlType.UNCONTROLLED,
        )
        for connection in self.lane_connections:
            connection.control = control

    def _road_end_at_junction(self, road: Road) -> RoadEnd:
        return (
            RoadEnd.START
            if dist(road.centerline[0], self.position)
            <= dist(road.centerline[-1], self.position)
            else RoadEnd.END
        )

    def rebuild_lane_connections(self, tolerance: float = 12.0) -> None:
        """Generate every non-U-turn movement through this junction."""
        existing = {
            (
                connection.source_output.geometric_key,
                connection.destination_input.geometric_key,
            ): connection
            for connection in self.lane_connections
        }
        connections: list[LaneConnection] = []
        for source in self.incoming_ports():
            for destination in self.outgoing_ports():
                if (
                    self.kind is IntersectionKind.STANDARD
                    and source.road is destination.road
                ):
                    continue
                angle = _connection_angle(source, destination)
                kind = _maneuver_type(angle)
                if (
                    self.kind is IntersectionKind.STANDARD
                    and kind is ManeuverType.U_TURN
                ):
                    continue
                previous = existing.get((source.geometric_key, destination.geometric_key))
                connection = LaneConnection(
                    intersection_id=self.id,
                    source_output=source,
                    destination_input=destination,
                    path=(
                        _cul_de_sac_connection_path(source, destination, self.radius)
                        if self.kind is IntersectionKind.CUL_DE_SAC
                        else _connection_path(source, destination)
                    ),
                    maneuver=ManeuverDefinition(
                        previous.maneuver.kind if previous is not None else kind,
                        angle,
                    ),
                    control=previous.control if previous is not None else ControlDefinition(),
                )
                connections.append(connection)
        self.lane_connections = connections

    def inspection_properties(self) -> tuple[CityInspectionProperty, ...]:
        properties = [
            CityInspectionProperty("ID", self.id),
            CityInspectionProperty("Kind", self.kind.value),
            CityInspectionProperty("X", self.position[0], "distance"),
            CityInspectionProperty("Y", self.position[1], "distance"),
            CityInspectionProperty("Connected segments", len(self.connected_roads)),
            CityInspectionProperty("Incoming road outputs", len(self.incoming_ports())),
            CityInspectionProperty("Outgoing road inputs", len(self.outgoing_ports())),
            CityInspectionProperty("Lane connections", len(self.lane_connections)),
            CityInspectionProperty("Radius", self.radius, "distance"),
        ]
        properties.extend(
            CityInspectionProperty(
                f"Road segment {index}", road.name, target=road,
            )
            for index, road in enumerate(self.connected_roads, start=1)
        )
        return tuple(properties)


def _connection_angle(source: RoadPort, destination: RoadPort) -> float:
    incoming = source.heading
    outgoing = destination.heading
    cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    return atan2(cross, dot)


def _maneuver_type(angle: float) -> ManeuverType:
    if abs(angle) <= pi / 6:
        return ManeuverType.THROUGH
    if abs(angle) >= 5 * pi / 6:
        return ManeuverType.U_TURN
    return ManeuverType.RIGHT_TURN if angle > 0 else ManeuverType.LEFT_TURN


def _connection_path(source: RoadPort, destination: RoadPort) -> list[Point]:
    start = source.position
    end = destination.position
    incoming = source.heading
    outgoing = destination.heading
    handle = dist(start, end) / 2
    control_one = (start[0] + incoming[0] * handle, start[1] + incoming[1] * handle)
    control_two = (end[0] - outgoing[0] * handle, end[1] - outgoing[1] * handle)
    return [
        start,
        *cubic_bezier_points(start, control_one, control_two, end, steps=8),
    ]


def _cul_de_sac_connection_path(
    source: RoadPort,
    destination: RoadPort,
    radius: float,
) -> list[Point]:
    start = source.position
    end = destination.position
    incoming_vector = source.heading
    outgoing_vector = destination.heading
    handle = max(radius * 0.7, dist(start, end) / 2)
    control_one = (
        start[0] + incoming_vector[0] * handle,
        start[1] + incoming_vector[1] * handle,
    )
    control_two = (
        end[0] - outgoing_vector[0] * handle,
        end[1] - outgoing_vector[1] * handle,
    )
    return [
        start,
        *cubic_bezier_points(start, control_one, control_two, end, steps=12),
    ]


def _unit_vector(start: Point, end: Point) -> Point:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    return (dx / length, dy / length)


@dataclass
class Car:
    lane: Lane
    x: float
    y: float
    speed: float
    cruise_speed: float
    color: str
    acceleration: float = 0.0
    next_point: int = 1
    length: int = 14
    width: int = 6
    item: int | None = None
    detail_items: list[int] = field(default_factory=list)
    merge_realness: float = 0.0
    speed_preference_mph: float = 0.0


@dataclass(frozen=True)
class FollowingTarget:
    """A real leader or a gradually-solidifying leader from another lane."""

    car: Car
    strength: float
    is_phantom: bool = False


def cubic_bezier_points(
    start: Point, control_one: Point, control_two: Point, end: Point, steps: int = 18
) -> list[Point]:
    """Return points on a cubic Bézier curve, excluding the starting point."""
    points = []
    for index in range(1, steps + 1):
        t = index / steps
        inverse_t = 1 - t
        x = (
            inverse_t ** 3 * start[0]
            + 3 * inverse_t ** 2 * t * control_one[0]
            + 3 * inverse_t * t ** 2 * control_two[0]
            + t ** 3 * end[0]
        )
        y = (
            inverse_t ** 3 * start[1]
            + 3 * inverse_t ** 2 * t * control_one[1]
            + 3 * inverse_t * t ** 2 * control_two[1]
            + t ** 3 * end[1]
        )
        points.append((x, y))
    return points
