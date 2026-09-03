"""Composable mobility layers built on the generic pathfinding graph."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass, field
from math import dist, isfinite

from models import (
    Intersection,
    Lane,
    LaneConnection,
    Point,
    Road,
    RoadPort,
    point_at_polyline_distance,
    polyline_length,
    slice_polyline,
)
from pathfinding import DirectedGraph, Path


VEHICLE_LAYER = "vehicles"
MobilityNode = Hashable


@dataclass(frozen=True)
class MobilityLink:
    """An opaque domain value carried by a mobility-graph edge."""

    kind: str
    value: object


@dataclass(frozen=True, eq=False)
class LanePosition:
    """A precise travel-direction distance and point along one lane."""

    lane: Lane
    distance: float
    point: Point

    def __post_init__(self) -> None:
        length = polyline_length(self.lane.points)
        tolerance = max(1e-9, length * 1e-12)
        if (
            not isfinite(self.distance)
            or self.distance < -tolerance
            or self.distance > length + tolerance
        ):
            raise ValueError("Lane-position distance must lie along its lane")
        object.__setattr__(self, "distance", max(0.0, min(length, self.distance)))


@dataclass(frozen=True)
class LaneTraversal:
    """A possibly partial piece of lane geometry carried by a route edge."""

    lane: Lane
    points: tuple[Point, ...]


@dataclass(frozen=True)
class PortTraversal:
    """The short fan-in or fan-out between a lane and its road port."""

    port: RoadPort
    lane: Lane
    points: tuple[Point, ...]


VehicleRouteEndpoint = LanePosition | Intersection


@dataclass
class MobilityLayer:
    """One independently replaceable set of nodes and mobility links."""

    graph: DirectedGraph[MobilityNode, MobilityLink] = field(default_factory=DirectedGraph)
    positions: dict[MobilityNode, Point] = field(default_factory=dict)


@dataclass
class MobilityNetwork:
    """Combine arbitrary routing layers without assigning meaning to A*."""

    layers: dict[str, MobilityLayer] = field(default_factory=dict)

    def set_layer(self, name: str, layer: MobilityLayer) -> None:
        if not name:
            raise ValueError("Mobility layer names cannot be empty")
        self.layers[name] = layer

    def combined_graph(
        self,
        layer_names: Iterable[str] | None = None,
    ) -> DirectedGraph[MobilityNode, MobilityLink]:
        names = tuple(self.layers) if layer_names is None else tuple(layer_names)
        graph: DirectedGraph[MobilityNode, MobilityLink] = DirectedGraph()
        for name in names:
            try:
                graph.extend(self.layers[name].graph)
            except KeyError as error:
                raise KeyError(f"Unknown mobility layer: {name!r}") from error
        return graph

    def combined_positions(
        self,
        layer_names: Iterable[str] | None = None,
    ) -> dict[MobilityNode, Point]:
        names = tuple(self.layers) if layer_names is None else tuple(layer_names)
        positions: dict[MobilityNode, Point] = {}
        for name in names:
            try:
                positions.update(self.layers[name].positions)
            except KeyError as error:
                raise KeyError(f"Unknown mobility layer: {name!r}") from error
        return positions

    def find_path(
        self,
        start: MobilityNode,
        goal: MobilityNode,
        *,
        layer_names: Iterable[str] | None = None,
        use_distance_heuristic: bool = False,
    ) -> Path[MobilityNode, MobilityLink] | None:
        """Search selected layers; zero heuristic supports arbitrary cost units."""
        names = tuple(self.layers) if layer_names is None else tuple(layer_names)
        graph = self.combined_graph(names)
        if not use_distance_heuristic:
            return graph.find_path(start, goal)
        positions = self.combined_positions(names)
        try:
            goal_position = positions[goal]
        except KeyError as error:
            raise ValueError("A distance heuristic requires a position for the goal") from error

        def estimate(node: MobilityNode) -> float:
            try:
                return dist(positions[node], goal_position)
            except KeyError as error:
                raise ValueError(
                    f"A distance heuristic requires a position for node {node!r}"
                ) from error

        return graph.find_path(start, goal, estimate)


def lane_start_node(lane: Lane) -> tuple[str, str]:
    return ("vehicle_lane_start", lane.id)


def lane_end_node(lane: Lane) -> tuple[str, str]:
    return ("vehicle_lane_end", lane.id)


def road_input_node(port: RoadPort) -> tuple[str, str]:
    return ("vehicle_road_input", port.id)


def road_output_node(port: RoadPort) -> tuple[str, str]:
    return ("vehicle_road_output", port.id)


def build_vehicle_layer(
    roads: Sequence[Road],
    intersections: Sequence[Intersection],
) -> MobilityLayer:
    """Compile lane travel and junction movements into one directed layer."""
    layer = MobilityLayer()
    for road in roads:
        for lane in road.lanes:
            start = lane_start_node(lane)
            end = lane_end_node(lane)
            layer.positions[start] = lane.points[0]
            layer.positions[end] = lane.points[-1]
            layer.graph.add_edge(start, end, polyline_length(lane.points), MobilityLink("lane", lane))

        for port in road.route_inputs:
            port_node = road_input_node(port)
            layer.positions[port_node] = port.position
            for lane in port.lanes:
                points = (port.position, lane.points[0])
                layer.graph.add_edge(
                    port_node,
                    lane_start_node(lane),
                    dist(*points),
                    MobilityLink("road_port", PortTraversal(port, lane, points)),
                )
        for port in road.route_outputs:
            port_node = road_output_node(port)
            layer.positions[port_node] = port.position
            for lane in port.lanes:
                points = (lane.points[-1], port.position)
                layer.graph.add_edge(
                    lane_end_node(lane),
                    port_node,
                    dist(*points),
                    MobilityLink("road_port", PortTraversal(port, lane, points)),
                )

    for junction in intersections:
        for connection in junction.lane_connections:
            layer.graph.add_edge(
                road_output_node(connection.source_output),
                road_input_node(connection.destination_input),
                connection.length,
                MobilityLink("lane_connection", connection),
            )
    return layer


def nearest_lane_position(lane: Lane, position: Point) -> tuple[LanePosition, float]:
    """Project a world point onto a lane and return location plus lateral distance."""
    best_distance = float("inf")
    best_progress = 0.0
    best_point = lane.points[0]
    travelled = 0.0
    for start, end in zip(lane.points, lane.points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_squared = dx ** 2 + dy ** 2
        segment_length = length_squared ** 0.5
        if length_squared == 0:
            continue
        fraction = (
            (position[0] - start[0]) * dx + (position[1] - start[1]) * dy
        ) / length_squared
        fraction = max(0.0, min(1.0, fraction))
        projected = (start[0] + dx * fraction, start[1] + dy * fraction)
        lateral_distance = dist(position, projected)
        if lateral_distance < best_distance:
            best_distance = lateral_distance
            best_progress = travelled + segment_length * fraction
            best_point = projected
        travelled += segment_length
    best_progress = max(0.0, min(travelled, best_progress))
    if best_progress == 0.0:
        best_point = lane.points[0]
    elif best_progress == travelled:
        best_point = lane.points[-1]
    return LanePosition(lane, best_progress, best_point), best_distance


def lane_position_at_distance(lane: Lane, distance_along: float) -> LanePosition:
    """Construct a clamped position along a lane's direction of travel."""
    total = polyline_length(lane.points)
    distance_along = max(0.0, min(total, float(distance_along)))
    return LanePosition(
        lane,
        distance_along,
        point_at_polyline_distance(lane.points, distance_along),
    )


def vehicle_link_points(link: MobilityLink) -> tuple[Point, ...]:
    """Return travel geometry carried by one vehicle-layer link."""
    if link.kind == "lane" and isinstance(link.value, Lane):
        return tuple(link.value.points)
    if link.kind == "lane" and isinstance(link.value, LaneTraversal):
        return link.value.points
    if link.kind == "road_port" and isinstance(link.value, PortTraversal):
        return link.value.points
    if link.kind == "lane_connection" and isinstance(link.value, LaneConnection):
        return tuple(link.value.path)
    return ()


def vehicle_route_points(route: Path[MobilityNode, MobilityLink]) -> tuple[Point, ...]:
    """Flatten a routed vehicle path into one continuous drawable polyline."""
    result: list[Point] = []
    for link in route.edges:
        points = vehicle_link_points(link)
        if not points:
            continue
        if result and result[-1] == points[0]:
            result.extend(points[1:])
        else:
            result.extend(points)
    return tuple(result)


def find_vehicle_route_between(
    network: MobilityNetwork,
    start: VehicleRouteEndpoint,
    destination: VehicleRouteEndpoint,
) -> Path[MobilityNode, MobilityLink] | None:
    """Route between lane positions or complete multi-lane junctions."""
    graph = network.combined_graph((VEHICLE_LAYER,))
    positions = network.combined_positions((VEHICLE_LAYER,))
    start_point = _route_endpoint_point(start)
    destination_point = _route_endpoint_point(destination)
    start_node = ("vehicle_query_start", id(start))
    destination_node = ("vehicle_query_destination", id(destination))

    if isinstance(start, LanePosition):
        start_length = polyline_length(start.lane.points)
        start_points = slice_polyline(start.lane.points, start.distance, start_length)
        graph.add_edge(
            start_node,
            lane_end_node(start.lane),
            start_length - start.distance,
            MobilityLink("lane", LaneTraversal(start.lane, tuple(start_points))),
        )
    else:
        for port in start.outgoing_ports():
            graph.add_edge(
                start_node,
                road_input_node(port),
                0.0,
                MobilityLink("route_endpoint", start),
            )

    if isinstance(destination, LanePosition):
        destination_points = slice_polyline(
            destination.lane.points, 0.0, destination.distance,
        )
        graph.add_edge(
            lane_start_node(destination.lane),
            destination_node,
            destination.distance,
            MobilityLink(
                "lane",
                LaneTraversal(destination.lane, tuple(destination_points)),
            ),
        )
    else:
        for port in destination.incoming_ports():
            graph.add_edge(
                road_output_node(port),
                destination_node,
                0.0,
                MobilityLink("route_endpoint", destination),
            )

    if (
        isinstance(start, LanePosition)
        and isinstance(destination, LanePosition)
        and start.lane is destination.lane
        and destination.distance >= start.distance
    ):
        direct_points = slice_polyline(
            start.lane.points, start.distance, destination.distance,
        )
        graph.add_edge(
            start_node,
            destination_node,
            destination.distance - start.distance,
            MobilityLink(
                "lane",
                LaneTraversal(start.lane, tuple(direct_points)),
            ),
        )
    elif start is destination:
        graph.add_edge(
            start_node,
            destination_node,
            0.0,
            MobilityLink("route_endpoint", start),
        )
    positions[start_node] = start_point
    positions[destination_node] = destination_point

    def estimate(node: MobilityNode) -> float:
        return dist(positions[node], destination_point)

    return graph.find_path(start_node, destination_node, estimate)


def _route_endpoint_point(endpoint: VehicleRouteEndpoint) -> Point:
    return endpoint.point if isinstance(endpoint, LanePosition) else endpoint.position
