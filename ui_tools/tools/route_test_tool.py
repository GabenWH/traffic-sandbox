"""Interactive shortest-route visualization for constructed city roads."""

from __future__ import annotations

from typing import Any

from city import CityMap
from mobility import (
    LanePosition,
    LaneTraversal,
    MobilityLink,
    PortTraversal,
    VehicleRouteEndpoint,
    lane_position_at_distance,
    nearest_lane_position,
)
from models import Intersection, IntersectionKind, Lane, LaneConnection, Point
from pathfinding import Path
from units import distance_unit, pixels_to_display_distance

from ..base import CanvasTool


TOOL_ID = "route_test"
ROUTE_TEST_TAG = "route_test_overlay"


def constructed_lane_at(
    city_map: CityMap,
    position: Point,
    camera_zoom: float = 1.0,
) -> Lane | None:
    """Return the closest generated lane within its visible road surface."""
    selected = constructed_lane_position_at(city_map, position, camera_zoom)
    return None if selected is None else selected.lane


def constructed_lane_position_at(
    city_map: CityMap,
    position: Point,
    camera_zoom: float = 1.0,
) -> LanePosition | None:
    """Return the closest precise directed-lane position under a click."""
    candidates = [
        (*nearest_lane_position(lane, position), road.lane_width)
        for road in city_map.roads
        for lane in road.lanes
    ]
    if not candidates:
        return None
    lane_position, distance, lane_width = min(candidates, key=lambda item: item[1])
    tolerance = lane_width / 2 + 4 / max(camera_zoom, 0.01)
    return lane_position if distance <= tolerance else None


def constructed_junction_at(
    city_map: CityMap,
    position: Point,
) -> Intersection | None:
    """Return a selected intersection or cul-de-sac footprint."""
    for intersection in reversed(city_map.intersections):
        if (
            (position[0] - intersection.position[0]) ** 2
            + (position[1] - intersection.position[1]) ** 2
            <= intersection.radius ** 2
        ):
            return intersection
    return None


def route_polylines(
    route: Path[object, MobilityLink],
) -> tuple[tuple[str, list[Point]], ...]:
    """Extract drawable geometry while keeping A* edges domain-opaque."""
    polylines: list[tuple[str, list[Point]]] = []
    for link in route.edges:
        if link.kind == "lane" and isinstance(link.value, Lane):
            polylines.append((link.kind, link.value.points))
        elif link.kind == "lane" and isinstance(link.value, LaneTraversal):
            polylines.append((link.kind, list(link.value.points)))
        elif link.kind == "road_port" and isinstance(link.value, PortTraversal):
            if link.value.points[0] != link.value.points[-1]:
                polylines.append((link.kind, list(link.value.points)))
        elif link.kind == "lane_connection" and isinstance(link.value, LaneConnection):
            polylines.append((link.kind, link.value.path))
    return tuple(polylines)


class RouteTestTool(CanvasTool):
    """Choose two constructed lanes and display the shortest directed route."""

    name = "Test route"
    cursor = "crosshair"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.start_lane: Lane | None = None
        self.destination_lane: Lane | None = None
        self.start_position: LanePosition | None = None
        self.destination_position: LanePosition | None = None
        self.start_endpoint: VehicleRouteEndpoint | None = None
        self.destination_endpoint: VehicleRouteEndpoint | None = None
        self.route: Path[object, MobilityLink] | None = None
        self.message = "Click a starting lane."
        self._escape_binding: str | None = None
        self._dirty = True
        self._camera_state: tuple[float, float, float] | None = None

    def activate(self) -> None:
        self.host.canvas.configure(cursor=self.cursor)
        self._escape_binding = self.host.root.bind("<Escape>", self._escape_event, add="+")
        self._dirty = True
        self.refresh()

    def deactivate(self) -> None:
        if self._escape_binding is not None:
            self.host.root.unbind("<Escape>", self._escape_binding)
            self._escape_binding = None
        self.host.canvas.configure(cursor="")
        self.host.canvas.delete(ROUTE_TEST_TAG)
        self.clear()

    def on_canvas_click(self, event: Any) -> None:
        position = self.host.screen_to_world((event.x, event.y))
        junction = constructed_junction_at(self.host.city_map, position)
        if junction is not None:
            self.select_endpoint(junction)
            return
        lane_position = constructed_lane_position_at(
            self.host.city_map,
            position,
            self.host.camera_zoom,
        )
        if lane_position is None:
            self.message = "No constructed lane there. Click directly on a road lane."
            self._dirty = True
            return
        self.select_position(lane_position)

    def select_lane(self, lane: Lane) -> None:
        """Select a complete lane endpoint; retained for model-level callers."""
        distance = (
            0.0
            if self.start_endpoint is None or self.destination_endpoint is not None
            else float("inf")
        )
        self.select_position(lane_position_at_distance(lane, distance))

    def select_position(self, lane_position: LanePosition) -> None:
        """Advance start/destination selection at an exact lane distance."""
        self.select_endpoint(lane_position)

    def select_endpoint(self, endpoint: VehicleRouteEndpoint) -> None:
        """Advance selection using a precise lane position or whole junction."""
        if self.start_endpoint is None or self.destination_endpoint is not None:
            self.start_endpoint = endpoint
            self.destination_endpoint = None
            self.start_lane = endpoint.lane if isinstance(endpoint, LanePosition) else None
            self.destination_lane = None
            self.start_position = endpoint if isinstance(endpoint, LanePosition) else None
            self.destination_position = None
            self.route = None
            self.message = f"Start: {_endpoint_label(endpoint)}. Click a destination."
        else:
            self.destination_endpoint = endpoint
            self.destination_lane = endpoint.lane if isinstance(endpoint, LanePosition) else None
            self.destination_position = endpoint if isinstance(endpoint, LanePosition) else None
            self.route = self.host.city_map.find_vehicle_route_between(
                self.start_endpoint,
                endpoint,
            )
            if self.route is None:
                self.message = "No directed route found. Click another lane to start again."
            else:
                distance = pixels_to_display_distance(self.route.cost, self.host.unit_system)
                self.message = (
                    f"Route found: {distance:.1f} {distance_unit(self.host.unit_system)} · "
                    "click another lane to start again."
                )
        self._dirty = True

    def clear(self) -> None:
        self.start_lane = None
        self.destination_lane = None
        self.start_position = None
        self.destination_position = None
        self.start_endpoint = None
        self.destination_endpoint = None
        self.route = None
        self.message = "Click a starting lane."
        self._dirty = True

    def reset(self) -> None:
        self.clear()
        if hasattr(self.host, "canvas"):
            self.host.canvas.delete(ROUTE_TEST_TAG)

    def refresh(self) -> None:
        camera_state = (
            self.host.camera_x,
            self.host.camera_y,
            self.host.camera_zoom,
        )
        if camera_state != self._camera_state:
            self._camera_state = camera_state
            self._dirty = True
        if self._dirty:
            self._draw_overlay()
        else:
            # Static world redraws may occur without a camera change.
            self.host.canvas.tag_raise(ROUTE_TEST_TAG)

    def _draw_overlay(self) -> None:
        canvas = self.host.canvas
        canvas.delete(ROUTE_TEST_TAG)
        if self.route is not None:
            width = max(3, round(5 * self.host.camera_zoom))
            for kind, points in route_polylines(self.route):
                canvas.create_line(
                    *self.host.world_points(*points),
                    fill="#ffb000" if kind == "lane_connection" else "#37e6ff",
                    width=width,
                    capstyle="round",
                    joinstyle="round",
                    tags=ROUTE_TEST_TAG,
                )
        self._draw_endpoint_marker(self.start_endpoint, "#48e06f")
        self._draw_endpoint_marker(self.destination_endpoint, "#ff5b72")
        canvas.create_text(
            12,
            12,
            anchor="nw",
            text=self.message,
            fill="#ffffff",
            font=("Arial", 11, "bold"),
            tags=ROUTE_TEST_TAG,
        )
        canvas.tag_raise(ROUTE_TEST_TAG)
        self._dirty = False

    def _draw_endpoint_marker(
        self,
        endpoint: VehicleRouteEndpoint | None,
        color: str,
    ) -> None:
        if endpoint is None:
            return
        point = endpoint.point if isinstance(endpoint, LanePosition) else endpoint.position
        x, y = self.host.world_to_screen(point)
        radius = (
            6
            if isinstance(endpoint, LanePosition)
            else max(6, endpoint.radius * self.host.camera_zoom)
        )
        self.host.canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            fill=color if isinstance(endpoint, LanePosition) else "",
            outline="#ffffff" if isinstance(endpoint, LanePosition) else color,
            width=2 if isinstance(endpoint, LanePosition) else 3,
            tags=ROUTE_TEST_TAG,
        )

    def _escape_event(self, _event: Any) -> str:
        self.clear()
        self.refresh()
        return "break"


def _endpoint_label(endpoint: VehicleRouteEndpoint) -> str:
    if isinstance(endpoint, LanePosition):
        return endpoint.lane.name
    if isinstance(endpoint, Intersection):
        return (
            "cul-de-sac"
            if endpoint.kind is IntersectionKind.CUL_DE_SAC
            else "intersection"
        )
    raise TypeError("Unknown route endpoint")


TOOL_CLASS = RouteTestTool
