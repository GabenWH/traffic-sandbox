"""Canvas rendering for terrain, roads, traffic, and signs."""

from __future__ import annotations

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
from models import BuildablePhase, Car, IntersectionKind
from car_brain import SignalIntent
from land_ports import LAND_PORT_CONNECTOR_NAME, land_port_positions
from traffic_testbed import RoutedRoadVehicle
from units import mph_to_display
from vehicle import Vehicle
from color_palette import Palette

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
ROAD_VEHICLE_CAR_TAG = "road_vehicle_cars"
ROAD_VEHICLE_SIGNAL_TAG = "road_vehicle_signals"
TEST_TRAFFIC_CAR_TAG = ROAD_VEHICLE_CAR_TAG
TEST_TRAFFIC_SIGNAL_TAG = ROAD_VEHICLE_SIGNAL_TAG
CONSTRUCTION_TRUCK_TAG = "construction_trucks"
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
        self._draw_regional_land_ports()
        self._draw_buildings()
        if self.blank_map:
            if not any(
                road.name != LAND_PORT_CONNECTOR_NAME
                for road in self.city_map.roads
            ):
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
                    fill=Palette.TREE_CANOPY, width=max(1, round(canopy)),
                    tags=STATIC_TAG,
                )
            else:
                self.canvas.create_oval(
                    x - canopy, y - canopy, x + canopy, y + canopy,
                    fill=Palette.TREE_CANOPY,
                    outline=Palette.TREE_OUTLINE, tags=STATIC_TAG,
                )

    def _draw_empty_world_instructions(self) -> None:
        x, y = self.world_to_screen((self.city_map.width / 2, self.city_map.height / 2))
        self.canvas.create_text(
            x, y,
            text=(
                "Regional land port connects this map to the outside network\n"
                "Choose Build → Build road and extend from its west-edge connector\n"
                "Middle-drag to pan · mouse wheel to zoom"
            ),
            fill=Palette.WHITE,
            font=("Arial", max(10, int(16 * self.camera_zoom)), "bold"),
            justify="center",
            tags=STATIC_TAG,
        )

    def _draw_regional_land_ports(self) -> None:
        """Mark every road connection between this map and the regional network."""
        scale = max(0.7, self.camera_zoom)
        radius = max(5, 7 * scale)
        for position in land_port_positions(self.city_map):
            x, y = self.world_to_screen(position)
            self.canvas.create_line(
                x - 14 * scale, y, x + 10 * scale, y,
                fill="#ffd166",
                width=max(2, 2 * scale),
                arrow="last",
                tags=STATIC_TAG,
            )
            self.canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                fill="#244861",
                outline="#ffd166",
                width=max(2, 2 * scale),
                tags=STATIC_TAG,
            )
            self.canvas.create_text(
                x + 12 * scale, y - 8 * scale,
                text="REGIONAL LAND PORT",
                anchor="sw",
                fill="#fff4cc",
                font=("Arial", max(6, round(9 * scale)), "bold"),
                tags=STATIC_TAG,
            )

    def _draw_buildings(self) -> None:
        """Draw persistent building footprints above the authored road layer."""
        for building in self.city_map.buildings:
            parcel = building.parcel
            under_construction = building.phase is BuildablePhase.UNDER_CONSTRUCTION
            left, top = self.world_to_screen((parcel.x, parcel.y))
            right, bottom = self.world_to_screen((parcel.x + parcel.width, parcel.y + parcel.height))
            if right < 0 or bottom < 0 or left > self.canvas.winfo_width() or top > self.canvas.winfo_height():
                continue
            if self.camera_zoom < CITY_LOW_DETAIL_ZOOM:
                options = {
                    "fill": building.color,
                    "outline": "#ffb000" if under_construction else "",
                    "width": max(1, round(self.camera_zoom)),
                    "tags": STATIC_TAG,
                }
                if under_construction:
                    options["dash"] = (4, 3)
                self.canvas.create_rectangle(
                    left, top, right, bottom,
                    **options,
                )
                continue
            inset = max(1, 3 * self.camera_zoom)
            self.canvas.create_rectangle(
                left + inset,
                top + inset,
                right + inset,
                bottom + inset,
                fill=Palette.BUILDING_SHADOW,
                outline="",
                tags=STATIC_TAG,
            )
            options = {
                "fill": building.color,
                "outline": (
                    "#ffb000" if under_construction else "#eee4d5"
                ),
                "width": max(1, round(self.camera_zoom)),
                "tags": STATIC_TAG,
            }
            if under_construction:
                options["dash"] = (7, 4)
            self.canvas.create_rectangle(left, top, right, bottom, **options)
            if self.camera_zoom >= 0.7:
                self.canvas.create_text(
                    (left + right) / 2,
                    (top + bottom) / 2,
                    text=building.name,
                    fill=Palette.WHITE,
                    font=("Arial", max(7, round(9 * self.camera_zoom)), "bold"),
                    width=max(20, right - left - 6),
                    tags=STATIC_TAG,
                )

    def draw_road_vehicles(self) -> None:
        """Refresh every city road user through the same vehicle collection."""
        self.canvas.delete(CONSTRUCTION_TRUCK_TAG)
        road_vehicles = getattr(self, "road_vehicles", None)
        if road_vehicles is None:
            return
        for vehicle in road_vehicles.vehicles:
            self.draw_road_vehicle(vehicle)

    def draw_road_vehicle(self, vehicle: Vehicle) -> None:
        """Draw any app vehicle through its shared presentation contract."""
        if isinstance(vehicle, Car):
            self.draw_car(vehicle)
        elif vehicle.appearance.shape == "car":
            self.draw_road_car(vehicle)
        else:
            self.draw_construction_truck(vehicle)

    def draw_construction_truck(self, vehicle: Vehicle) -> None:
        """Draw Astra's native cab-over material or crew truck from above."""
        appearance = vehicle.appearance
        if appearance.shape not in ("material_truck", "crew_truck"):
            return
        length = max(10.0, vehicle.length * self.camera_zoom)
        width = max(5.0, vehicle.width * self.camera_zoom)
        kind = "crew" if appearance.shape == "crew_truck" else "material"
        payload_key = appearance.cargo_key or "crew"
        load_fraction = appearance.load_fraction
        truck_key = appearance.visual_key or appearance.shape
        x, y = vehicle.position
        forward_x, forward_y = vehicle.heading
        right_x, right_y = forward_y, -forward_x
        tags = (
            CONSTRUCTION_TRUCK_TAG,
            f"truck-visual:{truck_key}",
            f"payload-visual:{payload_key}",
        )
        outline = "#20252a"
        stroke = max(1, round(self.camera_zoom))

        def polygon(name, f1, f2, s1, s2, fill, *, edge=outline):
            coords = []
            for forward, lateral in ((f1, s1), (f2, s1), (f2, s2), (f1, s2)):
                point = (
                    x + forward_x * forward * length + right_x * lateral * width,
                    y + forward_y * forward * length + right_y * lateral * width,
                )
                coords.extend(self.world_to_screen(point))
            self.canvas.create_polygon(
                *coords,
                fill=fill,
                outline=edge,
                width=stroke,
                tags=(*tags, f"construction-truck-part:{name}"),
            )

        polygon("chassis", -0.46, 0.46, -0.40, 0.40, "#343b40")
        for end, forward in (("front", 0.28), ("rear", -0.31)):
            for side, lateral in (("left", -0.47), ("right", 0.47)):
                polygon(
                    f"wheel-{side}-{end}", forward - 0.10, forward + 0.10,
                    lateral - 0.055, lateral + 0.055, "#16191c",
                )

        if kind == "crew":
            cab_color = "#ffb000"
            polygon("crew-compartment", -0.44, 0.10, -0.42, 0.42, "#eee1c6")
            polygon("crew-windows-left", -0.32, -0.02, -0.45, -0.41,
                    "#29566b", edge="#29566b")
            polygon("crew-windows-right", -0.32, -0.02, 0.41, 0.45,
                    "#29566b", edge="#29566b")
            for index in range(min(3, appearance.workers)):
                lateral = (index - 1) * 0.18
                polygon(
                    f"crew-roof-marker-{index}", -0.26, -0.20,
                    lateral - 0.055, lateral + 0.055,
                    "#ffb000", edge="#ffb000",
                )
        else:
            cab_color = "#37e6ff"
            polygon("flatbed", -0.44, 0.12, -0.43, 0.43, "#8e969b")
            polygon("bed-rail-left", -0.44, 0.12, -0.46, -0.40, "#a9b0b4")
            polygon("bed-rail-right", -0.44, 0.12, 0.40, 0.46, "#a9b0b4")
            if load_fraction > 0:
                load = max(0.25, load_fraction)
                if payload_key == "stone":
                    block_count = max(1, round(4 * load))
                    block_positions = (
                        (-0.23, -0.27), (0.23, -0.27),
                        (-0.23, -0.08), (0.23, -0.08),
                    )
                    for index, (lateral, forward) in enumerate(block_positions[:block_count]):
                        half_lateral = 0.10 * load
                        half_forward = 0.08 * load
                        polygon(
                            f"cargo-stone-{index}",
                            forward - half_forward, forward + half_forward,
                            lateral - half_lateral, lateral + half_lateral,
                            "#8c9296",
                        )
                else:
                    cargo_color = {
                        "lumber": "#bd8956",
                        "steel": "#8295a7",
                    }.get(payload_key, "#a7a7a7")
                    beam_width = 0.075 if payload_key == "lumber" else 0.04
                    for index, lateral in enumerate((-0.23, 0.0, 0.23)):
                        polygon(
                            f"cargo-{payload_key}-{index}",
                            -0.37, -0.37 + 0.43 * load,
                            lateral - beam_width, lateral + beam_width,
                            cargo_color,
                        )
        polygon("cab", 0.10, 0.47, -0.39, 0.39, cab_color)
        polygon("windshield", 0.39, 0.46, -0.30, 0.30, "#29566b")
        polygon("headlights", 0.46, 0.50, -0.31, 0.31, "#fff7b0", edge="#fff7b0")
        for side, lateral in (("left", -0.38), ("right", 0.38)):
            polygon(
                f"indicator-{side}", 0.45, 0.50, lateral - 0.04, lateral + 0.04,
                "#ffb000", edge="#ffb000",
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
                    *points, fill=Palette.ROAD_SURFACE, width=road_width,
                    capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
                )
                if road.forward_lane_count and road.reverse_lane_count:
                    self.canvas.create_line(
                        *points, fill=Palette.ROAD_DIVIDER,
                        width=max(1, round(0.5 * self.camera_zoom)),
                        dash=(max(1, round(12 * self.camera_zoom)), max(1, round(8 * self.camera_zoom))),
                        capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
                    )
            self._draw_junction_surfaces()
            return
        self._draw_ground_work()
        # Draw each material as one global layer. Rendering a complete stack
        # per segment lets the next segment's edge cap cover the previous
        # segment's asphalt, exposing every split at an intersection.
        for road, points, road_width in rendered_roads:
            edge_width = max(
                road_width + 2,
                round((road.width + 4) * self.camera_zoom),
            )
            self.canvas.create_line(
                *points, fill=Palette.ROAD_EDGE, width=edge_width,
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
            fill=Palette.ROAD_EDGE,
                outline="",
                tags=STATIC_TAG,
            )

        for _road, points, road_width in rendered_roads:
            self.canvas.create_line(
                *points, fill=Palette.ROAD_SURFACE, width=road_width,
                capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
            )

        for road, points, _road_width in rendered_roads:
            if road.forward_lane_count and road.reverse_lane_count:
                # Tk canvas strokes are whole physical pixels.  Preserve the
                # intended scaling at larger zoom levels while retaining the
                # smallest drawable divider when zoomed out.
                centerline_width = max(1, round(0.5 * self.camera_zoom))
                self.canvas.create_line(
                    *points, fill=Palette.ROAD_DIVIDER,
                    width=centerline_width,
                    dash=(
                        max(1, round(12 * self.camera_zoom)),
                        max(1, round(8 * self.camera_zoom)),
                    ),
                    capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=STATIC_TAG,
                )
        self._draw_junction_surfaces()
    def _draw_ground_work(self)->None:
        for intersection in self.city_map.intersections:
            if intersection.kind is not IntersectionKind.ROUNDABOUT:
                continue
            x,y = self.world_to_screen(intersection.position)
            from roundabouts import outer_band_width

            outer_radius = (
                intersection.radius + outer_band_width(intersection)
            ) * self.camera_zoom
            self.canvas.create_oval(
                x - outer_radius, y - outer_radius,
                x + outer_radius, y + outer_radius,
                fill=Palette.ROUNDABOUT_APRON, outline="", tags=STATIC_TAG,
            )

    def _draw_junction_surfaces(self) -> None:
        """Draw intersection footprints and cul-de-sac turnaround bulbs."""
        for intersection in self.city_map.intersections:
            if intersection.kind is IntersectionKind.CUL_DE_SAC:
                continue
            if not intersection.connected_roads:
                continue
            roundabout = intersection.kind is IntersectionKind.ROUNDABOUT
            if roundabout:
                from roundabouts import (
                    island_radius, outer_band_width, yield_mark,
                )
                visibility_radius = intersection.radius + outer_band_width(intersection)
            else:
                visibility_radius = intersection.radius
            if not self._circle_is_visible(intersection.position, visibility_radius):
                continue
            x, y = self.world_to_screen(intersection.position)
            surface_radius = max(1, intersection.radius * self.camera_zoom)
            self.canvas.create_oval(
                x - surface_radius, y - surface_radius,
                x + surface_radius, y + surface_radius,
                fill=Palette.ROAD_SURFACE, outline="", tags=STATIC_TAG,
            )
            if roundabout:
                island = max(1, island_radius(intersection) * self.camera_zoom)
                self.canvas.create_oval(
                    x-island, y-island, x+island, y+island,
                    fill=Palette.ROUNDABOUT_ISLAND,
                    outline=Palette.ROUNDABOUT_ISLAND_OUTLINE,
                    width=max(1, 2*self.camera_zoom), tags=STATIC_TAG)
                from mobility import VEHICLE_LAYER, road_output_node
                graph = self.city_map.mobility.layers[VEHICLE_LAYER].graph
                for port in intersection.incoming_ports():
                    entry = next((t.edge.value for t in graph.transitions_from(road_output_node(port))
                                  if getattr(t.edge.value, "roundabout_role", "") == "entry"), None)
                    if entry is None:
                        continue
                    position, heading = yield_mark(entry)
                    side = (-heading[1], heading[0])
                    a = (position[0]-side[0]*port.width/2,
                         position[1]-side[1]*port.width/2)
                    b = (position[0]+side[0]*port.width/2,
                         position[1]+side[1]*port.width/2)
                    self.canvas.create_line(*self.world_points(a, b),
                        fill=Palette.ROAD_MARKING, dash=(3, 3),
                        width=max(2, 2*self.camera_zoom), tags=STATIC_TAG)
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
                    fill=Palette.ROAD_MARKING,
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
                fill=Palette.ROAD_SURFACE,
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
            fill=Palette.ROAD_SURFACE, outline="", tags=STATIC_TAG,
        )
        canvas.create_rectangle(
            *self.world_box(ROAD_START_X, ROAD_TOP - ROAD_EDGE_WIDTH, POST_MERGE_END, ROAD_TOP),
            fill=Palette.ROAD_EDGE, outline="", tags=STATIC_TAG,
        )
        canvas.create_line(
            *self.world_points(
                (ROAD_START_X, ROAD_BOTTOM), (MERGE_START, ROAD_BOTTOM),
                (MERGE_END, ROAD_TOP + LANE_HEIGHT),
                (POST_MERGE_END, ROAD_TOP + LANE_HEIGHT),
            ),
            fill=Palette.ROAD_EDGE,
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
                    fill=Palette.LANE_MARKING, outline="", tags=STATIC_TAG,
                )
        for lane_index, lane in enumerate(self.simulation.entry_lanes):
            x, y = self.world_to_screen((
                LANE_LABEL_X,
                ROAD_TOP + lane_index * LANE_HEIGHT + LANE_LABEL_Y_OFFSET,
            ))
            canvas.create_text(
                x, y, text=lane.name, fill=Palette.LANE_LABEL,
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
            self.draw_road_vehicle(car)
        if hasattr(self, "road_vehicles"):
            self.draw_test_traffic_sources()
            self.draw_road_vehicles()
        elif hasattr(self, "test_traffic"):
            self.draw_test_traffic_sources()
            for car in self.test_traffic.cars:
                self.draw_road_car(car)

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
                outline=Palette.ROUTE_HIGHLIGHT,
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
                outline=Palette.ROUTE_ERROR,
                width=2,
                tags=TEST_TRAFFIC_SOURCE_TAG,
            )
            self.canvas.create_text(
                x,
                y,
                text="⇄",
                fill=Palette.WHITE,
                font=("Arial", max(8, round(11 * self.camera_zoom)), "bold"),
                tags=TEST_TRAFFIC_SOURCE_TAG,
            )
        self.canvas.tag_raise(TEST_TRAFFIC_SOURCE_TAG)

    def draw_road_car(self, car: RoutedRoadVehicle) -> None:
        """Render a routed car only while it is inside the viewport."""
        if car.appearance.shape != "car":
            return
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
                    tags=ROAD_VEHICLE_CAR_TAG,
                )
            else:
                car.item = self.canvas.create_polygon(
                    0, 0, 0, 0,
                    fill=car.color, outline=Palette.CAR_OUTLINE, width=1,
                    tags=ROAD_VEHICLE_CAR_TAG,
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
        self._draw_road_car_signals(car, style, forward_x, forward_y, side_x, side_y)

    def draw_test_car(self, car: RoutedRoadVehicle) -> None:
        """Compatibility name for routed car presentation."""
        self.draw_road_car(car)

    def _draw_road_car_signals(
        self,
        car: RoutedRoadVehicle,
        style: str,
        forward_x: float,
        forward_y: float,
        side_x: float,
        side_y: float,
    ) -> None:
        """Draw route-driven blinkers using the simulation clock."""
        road_vehicles = getattr(self, "road_vehicles", None) or getattr(
            self, "test_traffic", None,
        )
        active = (
            style == "polygon"
            and car.brain.signal_intent is not SignalIntent.NONE
            and road_vehicles is not None
            and road_vehicles.elapsed_time % 1.0 < 0.5
        )
        if style != "polygon" or car.brain.signal_intent is SignalIntent.NONE:
            for item in car.signal_items:
                self.canvas.itemconfigure(item, state="hidden")
            return
        if not car.signal_items:
            car.signal_items = [
                self.canvas.create_oval(
                    0, 0, 0, 0,
                    fill=Palette.SIGNAL_AMBER,
                    outline=Palette.SIGNAL_OUTLINE,
                    tags=(ROAD_VEHICLE_CAR_TAG, ROAD_VEHICLE_SIGNAL_TAG),
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
        x, y = car.position
        forward_x, forward_y = car.heading
        side_x, side_y = -forward_y, forward_x
        self.canvas.coords(car.item, *self.screen_oriented_box(
            x, y, forward_x, forward_y, side_x, side_y,
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
            wheel_x = x + forward_x * forward + side_x * side
            wheel_y = y + forward_y * forward + side_y * side
            self.canvas.coords(item, *self.screen_oriented_box(
                wheel_x, wheel_y, forward_x, forward_y, side_x, side_y,
                car.length * WHEEL_HALF_LENGTH_RATIO,
                car.width * WHEEL_HALF_WIDTH_RATIO,
            ))
        for item, side in zip(car.detail_items[4:6], (
            car.width * HEADLIGHT_CENTER_WIDTH_RATIO,
            -car.width * HEADLIGHT_CENTER_WIDTH_RATIO,
        )):
            light_x = x + forward_x * (car.length * HEADLIGHT_CENTER_LENGTH_RATIO) + side_x * side
            light_y = y + forward_y * (car.length * HEADLIGHT_CENTER_LENGTH_RATIO) + side_y * side
            self.canvas.coords(item, *self.screen_oriented_box(
                light_x, light_y, forward_x, forward_y, side_x, side_y,
                car.length * HEADLIGHT_HALF_LENGTH_RATIO,
                car.width * HEADLIGHT_HALF_WIDTH_RATIO,
            ))
        windshield = car.detail_items[6]
        windshield_x = x + forward_x * (car.length * 0.20)
        windshield_y = y + forward_y * (car.length * 0.10)
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
            self.canvas.create_polygon(
                0, 0, 0, 0,
                fill=Palette.CAR_WHEEL, outline=Palette.CAR_WHEEL_OUTLINE,
            )
            for _ in range(4)
        ]
        body = self.canvas.create_polygon(
            0, 0, 0, 0, outline=Palette.CAR_OUTLINE, width=2,
        )
        headlights = [
            self.canvas.create_polygon(
                0, 0, 0, 0, fill=Palette.HEADLIGHT, outline="",
            )
            for _ in range(2)
        ]
        windshield = self.canvas.create_polygon(
            0, 0, 0, 0,
            fill=Palette.WINDSHIELD, outline=Palette.WINDSHIELD_OUTLINE,
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
                    fill=Palette.SPEED_SIGN, outline=Palette.CAR_OUTLINE,
                    tags=SPEED_LIMIT_TAG,
                )
                continue
            self.canvas.create_rectangle(
                x - 25 * scale, y - 32 * scale, x + 25 * scale, y + 42 * scale,
                fill=Palette.SPEED_SIGN, outline=Palette.CAR_OUTLINE,
                width=2, tags=SPEED_LIMIT_TAG,
            )
            self.canvas.create_text(
                x, y - 12 * scale, text="SPEED", fill=Palette.CAR_OUTLINE,
                font=("Arial", max(6, int(8 * scale)), "bold"), tags=SPEED_LIMIT_TAG,
            )
            self.canvas.create_text(
                x, y + 6 * scale, text="LIMIT", fill=Palette.CAR_OUTLINE,
                font=("Arial", max(6, int(8 * scale)), "bold"), tags=SPEED_LIMIT_TAG,
            )
            self.canvas.create_text(
                x, y + 24 * scale,
                text=f"{mph_to_display(speed_limit.speed, self.unit_system):.0f}",
                fill=Palette.CAR_OUTLINE,
                font=("Arial", max(8, int(12 * scale)), "bold"),
                tags=SPEED_LIMIT_TAG,
            )
