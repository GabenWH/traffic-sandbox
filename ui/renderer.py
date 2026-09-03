"""Canvas rendering for terrain, roads, traffic, and signs."""

from __future__ import annotations

from math import atan2, cos, sin
import tkinter as tk

from city import TREE_CANOPY_RADIUS
from config import (
    HEIGHT,
    LANE_DASH_HALF_HEIGHT,
    LANE_DASH_LENGTH,
    LANE_DASH_SPACING,
    LANE_DASH_START_X,
    LANE_HEIGHT,
    LANE_LABEL_FONT_SIZE,
    LANE_LABEL_MIN_FONT_SIZE,
    LANE_LABEL_X,
    LANE_LABEL_Y_OFFSET,
    LANES,
    MERGE_END,
    MERGE_START,
    MIN_SCALED_STROKE_WIDTH,
    POST_MERGE_END,
    ROAD_BOTTOM,
    ROAD_EDGE_WIDTH,
    ROAD_START_X,
    ROAD_TOP,
    WIDTH,
)
from models import Car, IntersectionKind
from car_brain import SignalIntent
from traffic_testbed import RoutedTestCar
from units import mph_to_display

from .base import SPEED_LIMIT_TAG, STATIC_TAG


WHEEL_CENTER_LENGTH_RATIO = 0.28
WHEEL_CENTER_WIDTH_RATIO = 0.50
WHEEL_HALF_LENGTH_RATIO = 6 / 54
WHEEL_HALF_WIDTH_RATIO = 2 / 25
HEADLIGHT_CENTER_LENGTH_RATIO = 0.46
HEADLIGHT_CENTER_WIDTH_RATIO = 0.27
HEADLIGHT_HALF_LENGTH_RATIO = 2.5 / 54
HEADLIGHT_HALF_WIDTH_RATIO = 3 / 25
TEST_TRAFFIC_SOURCE_TAG = "test_traffic_sources"
TEST_TRAFFIC_CAR_TAG = "test_traffic_cars"
TEST_TRAFFIC_SIGNAL_TAG = "test_traffic_signals"
STOP_LINE_TAG = "stop_lines"
CITY_LOW_DETAIL_ZOOM = 0.55


class RendererMixin:
    """Render model state using the host's canvas and viewport API."""

    def draw_scene(self) -> None:
        """Replace the static world layer for the current camera view."""
        canvas = self.canvas
        canvas.delete(STATIC_TAG)
        canvas_width = max(canvas.winfo_width(), WIDTH)
        canvas_height = max(canvas.winfo_height(), HEIGHT)
        canvas.create_rectangle(
            0, 0, canvas_width, canvas_height,
            fill=self.city_map.terrain.grass_color, outline="", tags=STATIC_TAG,
        )
        self._draw_visible_trees()
        self.draw_city_roads()
        self._draw_buildings()
        if self.blank_map:
            if not self.city_map.roads:
                self._draw_empty_world_instructions()
            canvas.tag_lower(STATIC_TAG)
            return
        self._draw_legacy_merge_road()
        canvas.tag_lower(STATIC_TAG)

    def _draw_visible_trees(self) -> None:
        left, top, right, bottom = self.visible_world_bounds()
        for tree_x, tree_y in self.city_map.terrain.trees:
            if not (left - 20 <= tree_x <= right + 20 and top - 20 <= tree_y <= bottom + 20):
                continue
            x, y = self.world_to_screen((tree_x, tree_y))
            canopy = max(4, TREE_CANOPY_RADIUS * self.camera_zoom)
            if self.camera_zoom < CITY_LOW_DETAIL_ZOOM:
                self.canvas.create_line(
                    x, y, x + 1, y,
                    fill="#397a3e", width=max(1, round(canopy)),
                    tags=STATIC_TAG,
                )
            else:
                self.canvas.create_oval(
                    x - canopy, y - canopy, x + canopy, y + canopy,
                    fill="#397a3e", outline="#2f6835", tags=STATIC_TAG,
                )

    def _draw_empty_world_instructions(self) -> None:
        x, y = self.world_to_screen((self.city_map.width / 2, self.city_map.height / 2))
        self.canvas.create_text(
            x, y,
            text=(
                "City builder prototype\nChoose Build → Build road to draw a polyline\n"
                "Middle-drag to pan · mouse wheel to zoom"
            ),
            fill="#ffffff",
            font=("Arial", max(10, int(16 * self.camera_zoom)), "bold"),
            justify="center",
            tags=STATIC_TAG,
        )

    def _draw_buildings(self) -> None:
        """Draw persistent building footprints above the authored road layer."""
        for building in self.city_map.buildings:
            parcel = building.parcel
            left, top = self.world_to_screen((parcel.x, parcel.y))
            right, bottom = self.world_to_screen((parcel.x + parcel.width, parcel.y + parcel.height))
            if right < 0 or bottom < 0 or left > self.canvas.winfo_width() or top > self.canvas.winfo_height():
                continue
            if self.camera_zoom < CITY_LOW_DETAIL_ZOOM:
                self.canvas.create_rectangle(
                    left, top, right, bottom,
                    fill=building.color, outline="", tags=STATIC_TAG,
                )
                continue
            inset = max(1, 3 * self.camera_zoom)
            self.canvas.create_rectangle(
                left + inset,
                top + inset,
                right + inset,
                bottom + inset,
                fill="#40505a",
                outline="",
                tags=STATIC_TAG,
            )
            self.canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                fill=building.color,
                outline="#eee4d5",
                width=max(1, round(self.camera_zoom)),
                tags=STATIC_TAG,
            )
            if self.camera_zoom >= 0.7:
                self.canvas.create_text(
                    (left + right) / 2,
                    (top + bottom) / 2,
                    text=building.name,
                    fill="#ffffff",
                    font=("Arial", max(7, round(9 * self.camera_zoom)), "bold"),
                    width=max(20, right - left - 6),
                    tags=STATIC_TAG,
                )

    def draw_city_roads(self) -> None:
        """Render authored road centrelines as layered road surfaces."""
        rendered_roads = [
            (
                road,
                self.world_points(*road.centerline),
                max(2, round(road.width * self.camera_zoom)),
            )
            for road in self.city_map.roads
            if self._road_is_visible(road.centerline, road.width / 2 + 4)
        ]

        if self.camera_zoom < CITY_LOW_DETAIL_ZOOM:
            for road, points, road_width in rendered_roads:
                self.canvas.create_line(
                    *points, fill="#4d535a", width=road_width,
                    capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
                )
                if road.forward_lane_count and road.reverse_lane_count:
                    self.canvas.create_line(
                        *points, fill="#f4c542",
                        width=max(1, round(0.5 * self.camera_zoom)),
                        dash=(max(1, round(12 * self.camera_zoom)), max(1, round(8 * self.camera_zoom))),
                        capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
                    )
            self._draw_junction_surfaces()
            return

        # Draw each material as one global layer. Rendering a complete stack
        # per segment lets the next segment's edge cap cover the previous
        # segment's asphalt, exposing every split at an intersection.
        for road, points, road_width in rendered_roads:
            edge_width = max(
                road_width + 2,
                round((road.width + 4) * self.camera_zoom),
            )
            self.canvas.create_line(
                *points, fill="#c9cdd0", width=edge_width,
                capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
            )

        for cul_de_sac in self.city_map.cul_de_sacs:
            if not self._circle_is_visible(cul_de_sac.position, cul_de_sac.radius + 2):
                continue
            x, y = self.world_points(cul_de_sac.position)
            radius = (cul_de_sac.radius + 2) * self.camera_zoom
            self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="#c9cdd0",
                outline="",
                tags=STATIC_TAG,
            )

        for _road, points, road_width in rendered_roads:
            self.canvas.create_line(
                *points, fill="#4d535a", width=road_width,
                capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
            )

        for road, points, _road_width in rendered_roads:
            if road.forward_lane_count and road.reverse_lane_count:
                # Tk canvas strokes are whole physical pixels.  Preserve the
                # intended scaling at larger zoom levels while retaining the
                # smallest drawable divider when zoomed out.
                centerline_width = max(1, round(0.5 * self.camera_zoom))
                self.canvas.create_line(
                    *points, fill="#f4c542",
                    width=centerline_width,
                    dash=(
                        max(1, round(12 * self.camera_zoom)),
                        max(1, round(8 * self.camera_zoom)),
                    ),
                    capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
                )
        self._draw_junction_surfaces()

    def _draw_junction_surfaces(self) -> None:
        """Draw intersection footprints and cul-de-sac turnaround bulbs."""
        for intersection in self.city_map.intersections:
            if intersection.kind is IntersectionKind.CUL_DE_SAC:
                continue
            if not intersection.connected_roads:
                continue
            if not self._circle_is_visible(intersection.position, intersection.radius):
                continue
            x, y = self.world_to_screen(intersection.position)
            surface_radius = max(1, intersection.radius * self.camera_zoom)
            self.canvas.create_oval(
                x - surface_radius, y - surface_radius,
                x + surface_radius, y + surface_radius,
                fill="#4d535a", outline="", tags=STATIC_TAG,
            )
            controlled_ports = {
                connection.source_output
                for connection in intersection.lane_connections
                if connection.control.kind.value == "stop"
            }
            for port in controlled_ports:
                side_x, side_y = -port.heading[1], port.heading[0]
                half_width = port.width / 2
                start = (
                    port.position[0] - side_x * half_width,
                    port.position[1] - side_y * half_width,
                )
                end = (
                    port.position[0] + side_x * half_width,
                    port.position[1] + side_y * half_width,
                )
                self.canvas.create_line(
                    *self.world_points(start, end),
                    fill="#f7f7f2",
                    width=max(2, round(2 * self.camera_zoom)),
                    tags=(STATIC_TAG, STOP_LINE_TAG),
                )
        for cul_de_sac in self.city_map.cul_de_sacs:
            if not self._circle_is_visible(cul_de_sac.position, cul_de_sac.radius):
                continue
            x, y = self.world_points(cul_de_sac.position)
            surface_radius = max(1, cul_de_sac.radius * self.camera_zoom)
            self.canvas.create_oval(
                x - surface_radius,
                y - surface_radius,
                x + surface_radius,
                y + surface_radius,
                fill="#4d535a",
                outline="",
                tags=STATIC_TAG,
            )

    def _road_is_visible(
        self,
        points: list[tuple[float, float]],
        margin: float,
    ) -> bool:
        if not hasattr(self, "visible_world_bounds"):
            return True
        left, top, right, bottom = self.visible_world_bounds()
        point_left = min(point[0] for point in points)
        point_right = max(point[0] for point in points)
        point_top = min(point[1] for point in points)
        point_bottom = max(point[1] for point in points)
        return not (
            point_right < left - margin
            or point_left > right + margin
            or point_bottom < top - margin
            or point_top > bottom + margin
        )

    def _circle_is_visible(self, point: tuple[float, float], radius: float) -> bool:
        if not hasattr(self, "visible_world_bounds"):
            return True
        left, top, right, bottom = self.visible_world_bounds()
        return not (
            point[0] + radius < left
            or point[0] - radius > right
            or point[1] + radius < top
            or point[1] - radius > bottom
        )

    def _draw_legacy_merge_road(self) -> None:
        canvas = self.canvas
        canvas.create_polygon(
            *self.world_points(
                (0, ROAD_TOP), (POST_MERGE_END, ROAD_TOP),
                (POST_MERGE_END, ROAD_TOP + LANE_HEIGHT),
                (MERGE_END, ROAD_TOP + LANE_HEIGHT),
                (MERGE_START, ROAD_BOTTOM), (0, ROAD_BOTTOM),
            ),
            fill="#4d535a", outline="", tags=STATIC_TAG,
        )
        canvas.create_rectangle(
            *self.world_box(ROAD_START_X, ROAD_TOP - ROAD_EDGE_WIDTH, POST_MERGE_END, ROAD_TOP),
            fill="#c9cdd0", outline="", tags=STATIC_TAG,
        )
        canvas.create_line(
            *self.world_points(
                (ROAD_START_X, ROAD_BOTTOM), (MERGE_START, ROAD_BOTTOM),
                (MERGE_END, ROAD_TOP + LANE_HEIGHT),
                (POST_MERGE_END, ROAD_TOP + LANE_HEIGHT),
            ),
            fill="#c9cdd0",
            width=max(MIN_SCALED_STROKE_WIDTH, int(ROAD_EDGE_WIDTH * self.camera_zoom)),
            tags=STATIC_TAG,
        )
        for lane_index in range(1, LANES):
            y = ROAD_TOP + lane_index * LANE_HEIGHT
            for x in range(LANE_DASH_START_X, MERGE_START, LANE_DASH_SPACING):
                canvas.create_rectangle(
                    *self.world_box(
                        x, y - LANE_DASH_HALF_HEIGHT,
                        x + LANE_DASH_LENGTH, y + LANE_DASH_HALF_HEIGHT,
                    ),
                    fill="#f4f0bd", outline="", tags=STATIC_TAG,
                )
        for lane_index, lane in enumerate(self.simulation.entry_lanes):
            x, y = self.world_to_screen((
                LANE_LABEL_X,
                ROAD_TOP + lane_index * LANE_HEIGHT + LANE_LABEL_Y_OFFSET,
            ))
            canvas.create_text(
                x, y, text=lane.name, fill="#d9dde0",
                font=(
                    "Arial",
                    max(LANE_LABEL_MIN_FONT_SIZE, int(LANE_LABEL_FONT_SIZE * self.camera_zoom)),
                    "bold",
                ),
                tags=STATIC_TAG,
            )

    def redraw_world(self) -> None:
        """Rebuild scenery/signs and reproject every vehicle."""
        self.draw_scene()
        self.draw_speed_limits()
        for car in self.simulation.cars:
            self.draw_car(car)
        if hasattr(self, "test_traffic"):
            self.draw_test_traffic_sources()
            for car in self.test_traffic.cars:
                self.draw_test_car(car)

    def draw_test_traffic_sources(self) -> None:
        """Draw junctions enabled as temporary traffic sources and sinks."""
        self.canvas.delete(TEST_TRAFFIC_SOURCE_TAG)
        for junction in self.test_traffic.active_junctions(self.city_map):
            if not self._circle_is_visible(junction.position, junction.radius):
                continue
            x, y = self.world_to_screen(junction.position)
            radius = max(9, junction.radius * self.camera_zoom)
            self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="",
                outline="#37e6ff",
                width=3,
                tags=TEST_TRAFFIC_SOURCE_TAG,
            )
            inner = max(5, radius - 6)
            self.canvas.create_oval(
                x - inner,
                y - inner,
                x + inner,
                y + inner,
                fill="",
                outline="#ff5b72",
                width=2,
                tags=TEST_TRAFFIC_SOURCE_TAG,
            )
            self.canvas.create_text(
                x,
                y,
                text="⇄",
                fill="#ffffff",
                font=("Arial", max(8, round(11 * self.camera_zoom)), "bold"),
                tags=TEST_TRAFFIC_SOURCE_TAG,
            )
        self.canvas.tag_raise(TEST_TRAFFIC_SOURCE_TAG)

    def draw_test_car(self, car: RoutedTestCar) -> None:
        """Render a routed car only while it is inside the viewport."""
        left, top, right, bottom = self.visible_world_bounds()
        margin = car.length * 1.5
        x, y = car.position
        visible = left - margin <= x <= right + margin and top - margin <= y <= bottom + margin
        if not visible:
            if car.item is not None and car.rendered:
                self.canvas.itemconfigure(car.item, state="hidden")
                for item in car.signal_items:
                    self.canvas.itemconfigure(item, state="hidden")
                car.rendered = False
            return

        style = "line" if self.camera_zoom < 0.65 else "polygon"
        if car.item is None or car.render_style != style:
            if car.item is not None:
                self.canvas.delete(car.item)
            for item in car.signal_items:
                self.canvas.delete(item)
            car.signal_items.clear()
            if style == "line":
                car.item = self.canvas.create_line(
                    0, 0, 0, 0,
                    fill=car.color, width=2, capstyle=tk.ROUND,
                    tags=TEST_TRAFFIC_CAR_TAG,
                )
            else:
                car.item = self.canvas.create_polygon(
                    0, 0, 0, 0,
                    fill=car.color, outline="#20252a", width=1,
                    tags=TEST_TRAFFIC_CAR_TAG,
                )
            car.render_style = style
            car.rendered = True
        elif not car.rendered:
            self.canvas.itemconfigure(car.item, state="normal")
            car.rendered = True
        forward_x, forward_y = car.heading
        side_x, side_y = -forward_y, forward_x
        if style == "line":
            self.canvas.coords(
                car.item,
                *self.world_points(
                    (car.position[0] - forward_x * car.length / 2, car.position[1] - forward_y * car.length / 2),
                    (car.position[0] + forward_x * car.length / 2, car.position[1] + forward_y * car.length / 2),
                ),
            )
        else:
            self.canvas.coords(
                car.item,
                *self.screen_oriented_box(
                    car.position[0], car.position[1], forward_x, forward_y,
                    side_x, side_y, car.length / 2, car.width / 2,
                ),
            )
        self._draw_test_car_signals(car, style, forward_x, forward_y, side_x, side_y)

    def _draw_test_car_signals(
        self,
        car: RoutedTestCar,
        style: str,
        forward_x: float,
        forward_y: float,
        side_x: float,
        side_y: float,
    ) -> None:
        """Draw route-driven blinkers using the simulation clock."""
        active = (
            style == "polygon"
            and car.brain.signal_intent is not SignalIntent.NONE
            and self.test_traffic.elapsed_time % 1.0 < 0.5
        )
        if style != "polygon" or car.brain.signal_intent is SignalIntent.NONE:
            for item in car.signal_items:
                self.canvas.itemconfigure(item, state="hidden")
            return
        if not car.signal_items:
            car.signal_items = [
                self.canvas.create_oval(
                    0, 0, 0, 0,
                    fill="#ffb000",
                    outline="#5f3e00",
                    tags=(TEST_TRAFFIC_CAR_TAG, TEST_TRAFFIC_SIGNAL_TAG),
                )
                for _ in range(2)
            ]
        side_sign = -1.0 if car.brain.signal_intent is SignalIntent.LEFT else 1.0
        radius = max(1.0, 1.25 * self.camera_zoom)
        for item, forward in zip(car.signal_items, (0.40, -0.40)):
            world_x = (
                car.position[0]
                + forward_x * car.length * forward
                + side_x * car.width * 0.42 * side_sign
            )
            world_y = (
                car.position[1]
                + forward_y * car.length * forward
                + side_y * car.width * 0.42 * side_sign
            )
            screen_x, screen_y = self.world_points((world_x, world_y))
            self.canvas.coords(
                item,
                screen_x - radius,
                screen_y - radius,
                screen_x + radius,
                screen_y + radius,
            )
            self.canvas.itemconfigure(item, state="normal" if active else "hidden")

    def draw_car(self, car: Car) -> None:
        """Create if needed and update all canvas polygons for one vehicle."""
        if car.item is None or not car.detail_items:
            if car.item is not None:
                self.canvas.delete(car.item)
            car.item = self.create_car_details(car)
        assert car.item is not None
        if car.next_point < len(car.lane.points):
            target_x, target_y = car.lane.points[car.next_point]
            angle = atan2(target_y - car.y, target_x - car.x)
        else:
            angle = 0.0
        forward_x, forward_y = cos(angle), sin(angle)
        side_x, side_y = -forward_y, forward_x
        self.canvas.coords(car.item, *self.screen_oriented_box(
            car.x, car.y, forward_x, forward_y, side_x, side_y,
            car.length / 2, car.width / 2,
        ))
        self.canvas.itemconfigure(car.item, fill=car.color)
        wheel_positions = (
            (car.length * WHEEL_CENTER_LENGTH_RATIO, car.width * WHEEL_CENTER_WIDTH_RATIO),
            (car.length * WHEEL_CENTER_LENGTH_RATIO, -car.width * WHEEL_CENTER_WIDTH_RATIO),
            (-car.length * WHEEL_CENTER_LENGTH_RATIO, car.width * WHEEL_CENTER_WIDTH_RATIO),
            (-car.length * WHEEL_CENTER_LENGTH_RATIO, -car.width * WHEEL_CENTER_WIDTH_RATIO),
        )
        for item, (forward, side) in zip(car.detail_items[:4], wheel_positions):
            x = car.x + forward_x * forward + side_x * side
            y = car.y + forward_y * forward + side_y * side
            self.canvas.coords(item, *self.screen_oriented_box(
                x, y, forward_x, forward_y, side_x, side_y,
                car.length * WHEEL_HALF_LENGTH_RATIO,
                car.width * WHEEL_HALF_WIDTH_RATIO,
            ))
        for item, side in zip(car.detail_items[4:6], (
            car.width * HEADLIGHT_CENTER_WIDTH_RATIO,
            -car.width * HEADLIGHT_CENTER_WIDTH_RATIO,
        )):
            x = car.x + forward_x * (car.length * HEADLIGHT_CENTER_LENGTH_RATIO) + side_x * side
            y = car.y + forward_y * (car.length * HEADLIGHT_CENTER_LENGTH_RATIO) + side_y * side
            self.canvas.coords(item, *self.screen_oriented_box(
                x, y, forward_x, forward_y, side_x, side_y,
                car.length * HEADLIGHT_HALF_LENGTH_RATIO,
                car.width * HEADLIGHT_HALF_WIDTH_RATIO,
            ))
        windshield = car.detail_items[6]
        windshield_x = car.x + forward_x * (car.length * 0.20)
        windshield_y = car.y + forward_y * (car.length * 0.10)
        self.canvas.coords(windshield, *self.screen_oriented_box(
            windshield_x, windshield_y, forward_x, forward_y, side_x, side_y,
            car.length * 0.08, car.width * 0.34,
        ))

    @staticmethod
    def oriented_box(
        x: float, y: float, forward_x: float, forward_y: float,
        side_x: float, side_y: float, half_length: float, half_width: float,
    ) -> list[float]:
        """Return a rotated rectangle suitable for a Tkinter polygon."""
        points: list[float] = []
        for forward, side in (
            (half_length, half_width), (half_length, -half_width),
            (-half_length, -half_width), (-half_length, half_width),
        ):
            points.extend((
                x + forward_x * forward + side_x * side,
                y + forward_y * forward + side_y * side,
            ))
        return points

    def screen_oriented_box(
        self, x: float, y: float, forward_x: float, forward_y: float,
        side_x: float, side_y: float, half_length: float, half_width: float,
    ) -> list[float]:
        """Project a world-space vehicle rectangle into the current view."""
        coordinates = self.oriented_box(
            x, y, forward_x, forward_y, side_x, side_y, half_length, half_width,
        )
        return self.world_points(*list(zip(coordinates[::2], coordinates[1::2])))

    def create_car_details(self, car: Car) -> int:
        """Create a complete car visual and return its body item ID."""
        wheels = [
            self.canvas.create_polygon(0, 0, 0, 0, fill="#16191c", outline="#08090a")
            for _ in range(4)
        ]
        body = self.canvas.create_polygon(0, 0, 0, 0, outline="#20252a", width=2)
        headlights = [
            self.canvas.create_polygon(0, 0, 0, 0, fill="#fff7b0", outline="")
            for _ in range(2)
        ]
        windshield = self.canvas.create_polygon(
            0, 0, 0, 0, fill="#8ecae6", outline="#29566b",
        )
        car.detail_items = [*wheels, *headlights, windshield]
        return body

    def draw_speed_limits(self) -> None:
        """Rebuild the speed-limit visual layer."""
        self.canvas.delete(SPEED_LIMIT_TAG)
        for speed_limit in self.simulation.speed_limits:
            if not self._circle_is_visible((speed_limit.x, speed_limit.y), 45):
                continue
            x, y = self.world_to_screen((speed_limit.x, speed_limit.y))
            scale = self.camera_zoom
            if scale < CITY_LOW_DETAIL_ZOOM:
                radius = max(2, round(5 * scale))
                self.canvas.create_oval(
                    x - radius, y - radius, x + radius, y + radius,
                    fill="#f8f8f8", outline="#20252a", tags=SPEED_LIMIT_TAG,
                )
                continue
            self.canvas.create_rectangle(
                x - 25 * scale, y - 32 * scale, x + 25 * scale, y + 42 * scale,
                fill="#f8f8f8", outline="#20252a", width=2, tags=SPEED_LIMIT_TAG,
            )
            self.canvas.create_text(
                x, y - 12 * scale, text="SPEED", fill="#20252a",
                font=("Arial", max(6, int(8 * scale)), "bold"), tags=SPEED_LIMIT_TAG,
            )
            self.canvas.create_text(
                x, y + 6 * scale, text="LIMIT", fill="#20252a",
                font=("Arial", max(6, int(8 * scale)), "bold"), tags=SPEED_LIMIT_TAG,
            )
            self.canvas.create_text(
                x, y + 24 * scale,
                text=f"{mph_to_display(speed_limit.speed, self.unit_system):.0f}",
                fill="#20252a", font=("Arial", max(8, int(12 * scale)), "bold"),
                tags=SPEED_LIMIT_TAG,
            )
