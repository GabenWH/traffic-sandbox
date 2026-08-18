"""Tkinter controls and drawing for the freeway simulator."""

from __future__ import annotations

import time
import csv
import json
import traceback
import tkinter as tk
from math import atan2, cos, sin
from tkinter import filedialog, messagebox, simpledialog

from config import (
    DEFAULT_SPEED_LIMIT_MPH,
    DEFAULT_UNIT_SYSTEM,
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
    POST_MERGE_END,
    ROAD_BOTTOM,
    ROAD_EDGE_WIDTH,
    ROAD_START_X,
    ROAD_TOP,
    MIN_SCALED_STROKE_WIDTH,
    WIDTH,
)
from city import CityMap
from models import Car, Lane, Point, SpeedLimit
from simulation import TrafficSimulation
from ui_tools import CanvasTool, ToolbarTool, load_toolbar_tools
from units import (
    display_distance_to_pixels,
    display_to_mph,
    distance_unit,
    mph_to_display,
    pixels_to_display_distance,
    speed_limit_bounds,
    speed_unit,
    validate_unit_system,
)

# Vehicle-detail proportions are based on the original 54 × 25 car art.  They
# intentionally scale with each Car's dimensions, so the current 14 × 6 model
# and future vehicle sizes keep the same visual design.
WHEEL_CENTER_LENGTH_RATIO = 0.28
WHEEL_CENTER_WIDTH_RATIO = 0.50
WHEEL_HALF_LENGTH_RATIO = 6 / 54
WHEEL_HALF_WIDTH_RATIO = 2 / 25
HEADLIGHT_CENTER_LENGTH_RATIO = 0.46
HEADLIGHT_CENTER_WIDTH_RATIO = 0.27
HEADLIGHT_HALF_LENGTH_RATIO = 2.5 / 54
HEADLIGHT_HALF_WIDTH_RATIO = 3 / 25


class FreewaySimulator:
    """Present and control a :class:`TrafficSimulation` with Tkinter.

    This class owns only presentation state: widgets, camera position, canvas
    item IDs, dialogs, and exports. The traffic rules and persistent domain
    data stay in ``TrafficSimulation`` and the model classes.
    """

    def __init__(self, root: tk.Tk) -> None:
        """Build the windows, initialize the blank city view, and start ticks."""
        self.root = root
        root.title("Freeway Simulator")
        root.report_callback_exception = self.report_callback_exception
        self.running = True
        self.simulation_speed = 1.0
        self.unit_system = validate_unit_system(DEFAULT_UNIT_SYSTEM)
        self.simulation = TrafficSimulation()
        self.city_map = CityMap()
        self.blank_map = True
        self.camera_x = (self.city_map.width - WIDTH) / 2
        self.camera_y = (self.city_map.height - HEIGHT) / 2
        self.camera_zoom = 1.0
        self._pan_anchor: tuple[int, int] | None = None
        self.analytics_window: tk.Toplevel | None = None
        self.analytics_canvas: tk.Canvas | None = None
        self.recent_window: tk.Toplevel | None = None
        self.recent_canvas: tk.Canvas | None = None
        self.debug_window: tk.Toplevel | None = None
        self.debug_canvas: tk.Canvas | None = None
        self.recent_errors: list[str] = []
        self.selected_lane = self.simulation.lanes[0]
        # toolbar.json controls which independently defined tools appear and
        # their order.  The registry discovers the concrete modules in
        # ui_tools/tools and constructs only the enabled entries here.
        self.tools: list[ToolbarTool] = load_toolbar_tools(self)
        self.active_tool: CanvasTool | None = None
        self.last_time = time.perf_counter()
        self.last_dashboard_refresh = 0.0
        self.build_toolbar()
        # This is the canvas fallback color, not part of the world. It can show
        # briefly during startup because ``draw_scene`` runs before ``pack`` has
        # finalized an expanded canvas that may be larger than WIDTH × HEIGHT.
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, highlightthickness=0, bg="#e83ccb")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.handle_tool_click)
        self.canvas.bind("<Button-3>", self.show_lane_menu)
        self.canvas.bind("<ButtonPress-2>", self.start_pan)
        self.canvas.bind("<B2-Motion>", self.pan_camera)
        self.canvas.bind("<ButtonRelease-2>", self.end_pan)
        self.canvas.bind("<MouseWheel>", self.zoom_camera)
        self.canvas.bind("<Button-4>", lambda event: self.zoom_camera(event, 1))
        self.canvas.bind("<Button-5>", lambda event: self.zoom_camera(event, -1))
        self.canvas.bind("<Configure>", lambda _event: self.redraw_world())
        self.root.after_idle(self.draw_scene)
        self.create_debug_window()
        self.create_recent_changes_window()
        self.tick()

    def build_toolbar(self) -> None:
        """Build the toolbar from registered dropdown, canvas, and command tools."""
        toolbar = tk.Frame(self.root, padx=10, pady=8, bg="#e8edf2")
        toolbar.pack(fill="x")
        for index, tool in enumerate(self.tools):
            tool.build(toolbar).pack(side="left", padx=(8, 0) if index else 0)
        self.camera_label = tk.Label(toolbar, text="Pan: middle-drag · Zoom: wheel", bg="#e8edf2")
        self.camera_label.pack(side="left", padx=(12, 0))

    def select_tool(self, tool: CanvasTool) -> None:
        """Toggle one canvas tool while ensuring no other tool stays active."""
        if self.active_tool is tool:
            self.deactivate_tool(tool)
            return
        if self.active_tool is not None:
            self.active_tool.deactivate()
        self.active_tool = tool
        self.update_tool_buttons()
        tool.activate()

    def deactivate_tool(self, tool: CanvasTool) -> None:
        """Deactivate ``tool`` if it is the currently selected canvas tool."""
        if self.active_tool is not tool:
            return
        tool.deactivate()
        self.active_tool = None
        self.update_tool_buttons()

    def update_tool_buttons(self) -> None:
        """Make toolbar button relief reflect the selected tool."""
        for tool in self.tools:
            if isinstance(tool, CanvasTool):
                tool.set_active(self.active_tool is tool)

    def handle_tool_click(self, event: tk.Event[tk.Misc]) -> None:
        """Delegate a main-canvas left click to the selected tool, if any."""
        if self.active_tool is not None:
            self.active_tool.on_canvas_click(event)

    def draw_scene(self) -> None:
        """Replace the static world layer for the current camera view.

        Static items are deliberately rebuilt on camera changes and then sent
        behind cars and signs with the ``static`` canvas tag.
        """
        c = self.canvas
        # Dynamic vehicle/sign items have no ``static`` tag and survive this.
        c.delete("static")
        canvas_width = max(c.winfo_width(), WIDTH)
        canvas_height = max(c.winfo_height(), HEIGHT)
        # The grass is the actual world background; the canvas ``bg`` is only a
        # fallback for area not covered by this rectangle.
        c.create_rectangle(0, 0, canvas_width, canvas_height,
                           fill=self.city_map.terrain.grass_color, outline="", tags="static")
        left, top, right, bottom = self.visible_world_bounds()
        # Cull trees outside the camera view instead of creating all of them.
        for tree_x, tree_y in self.city_map.terrain.trees:
            if left - 20 <= tree_x <= right + 20 and top - 20 <= tree_y <= bottom + 20:
                x, y = self.world_to_screen((tree_x, tree_y))
                canopy = max(4, 11 * self.camera_zoom)
                trunk = max(2, 3 * self.camera_zoom)
                c.create_rectangle(x - trunk, y + canopy * .45, x + trunk, y + canopy * 1.1,
                                   fill="#71492b", outline="", tags="static")
                c.create_oval(x - canopy, y - canopy, x + canopy, y + canopy,
                              fill="#397a3e", outline="#2f6835", tags="static")
        # A save switches out of this instructional city-builder placeholder.
        if self.blank_map:
            center_x, center_y = self.world_to_screen((self.city_map.width / 2, self.city_map.height / 2))
            c.create_text(
                center_x, center_y,
                text="City builder prototype\nMiddle-drag to pan · mouse wheel to zoom\nLoad saves/current-merge-demo.json to restore the merge scenario",
                fill="#ffffff", font=("Arial", max(10, int(16 * self.camera_zoom)), "bold"), justify="center", tags="static",
            )
            c.tag_lower("static")
            return
        # Merge-demo road geometry is stored in world coordinates in config.py.
        c.create_polygon(*self.world_points((0, ROAD_TOP), (POST_MERGE_END, ROAD_TOP),
                         (POST_MERGE_END, ROAD_TOP + LANE_HEIGHT), (MERGE_END, ROAD_TOP + LANE_HEIGHT),
                         (MERGE_START, ROAD_BOTTOM), (0, ROAD_BOTTOM)),
                         fill="#4d535a", outline="", tags="static")
        # Paint the straight light-gray rim immediately above the dark road.
        # It extends from the road's left edge to the end of the post-merge lane.
        c.create_rectangle(
            *self.world_box(ROAD_START_X, ROAD_TOP - ROAD_EDGE_WIDTH, POST_MERGE_END, ROAD_TOP),
            fill="#c9cdd0", outline="", tags="static",
        )
        # Trace the light-gray rim along the lower edge, then up the outside of
        # the merging lane, and finally along the post-merge lane's lower edge.
        # This line is scenery only; it does not affect lane geometry or cars.
        c.create_line(
            *self.world_points(
                (ROAD_START_X, ROAD_BOTTOM), (MERGE_START, ROAD_BOTTOM),
                (MERGE_END, ROAD_TOP + LANE_HEIGHT), (POST_MERGE_END, ROAD_TOP + LANE_HEIGHT),
            ),
            fill="#c9cdd0", width=max(MIN_SCALED_STROKE_WIDTH, int(ROAD_EDGE_WIDTH * self.camera_zoom)),
            tags="static",
        )
        for lane_index in range(1, LANES):
            y = ROAD_TOP + lane_index * LANE_HEIGHT
            for x in range(LANE_DASH_START_X, MERGE_START, LANE_DASH_SPACING):
                c.create_rectangle(
                    *self.world_box(
                        x, y - LANE_DASH_HALF_HEIGHT,
                        x + LANE_DASH_LENGTH, y + LANE_DASH_HALF_HEIGHT,
                    ),
                    fill="#f4f0bd", outline="", tags="static",
                )
        for lane_index, lane in enumerate(self.simulation.entry_lanes):
            x, y = self.world_to_screen((
                LANE_LABEL_X,
                ROAD_TOP + lane_index * LANE_HEIGHT + LANE_LABEL_Y_OFFSET,
            ))
            c.create_text(
                x, y, text=lane.name, fill="#d9dde0",
                font=("Arial", max(LANE_LABEL_MIN_FONT_SIZE, int(LANE_LABEL_FONT_SIZE * self.camera_zoom)), "bold"),
                tags="static",
            )
        # Preserve scenery beneath the dynamic canvas items regardless of its
        # recreation order during a pan, zoom, reset, or load.
        c.tag_lower("static")

    def world_to_screen(self, point: Point) -> Point:
        """Project one world-space coordinate into the current canvas view."""
        return ((point[0] - self.camera_x) * self.camera_zoom,
                (point[1] - self.camera_y) * self.camera_zoom)

    def screen_to_world(self, point: Point) -> Point:
        """Convert a canvas coordinate back into the simulation's world space."""
        return (point[0] / self.camera_zoom + self.camera_x,
                point[1] / self.camera_zoom + self.camera_y)

    def world_points(self, *points: Point) -> list[float]:
        """Project points and flatten them for Tkinter polygon/line APIs."""
        return [coordinate for point in points for coordinate in self.world_to_screen(point)]

    def world_box(self, left: float, top: float, right: float, bottom: float) -> tuple[float, float, float, float]:
        """Project the opposite corners of a world-aligned rectangle."""
        return (*self.world_to_screen((left, top)), *self.world_to_screen((right, bottom)))

    def visible_world_bounds(self) -> tuple[float, float, float, float]:
        """Return the world-space rectangle currently visible on the canvas."""
        width = max(self.canvas.winfo_width(), WIDTH)
        height = max(self.canvas.winfo_height(), HEIGHT)
        return (*self.screen_to_world((0, 0)), *self.screen_to_world((width, height)))

    def redraw_world(self) -> None:
        """Rebuild static/sign layers and reproject every vehicle after camera movement."""
        self.draw_scene()
        self.draw_speed_limits()
        for car in self.simulation.cars:
            self.draw_car(car)

    def start_pan(self, event: tk.Event[tk.Misc]) -> None:
        """Begin a middle-button pan from the event's screen position."""
        self._pan_anchor = (event.x, event.y)
        self.canvas.configure(cursor="fleur")

    def pan_camera(self, event: tk.Event[tk.Misc]) -> None:
        """Move the camera opposite a middle-drag, then redraw the world."""
        if self._pan_anchor is None:
            return
        previous_x, previous_y = self._pan_anchor
        self.camera_x -= (event.x - previous_x) / self.camera_zoom
        self.camera_y -= (event.y - previous_y) / self.camera_zoom
        self._pan_anchor = (event.x, event.y)
        self.redraw_world()

    def end_pan(self, _event: tk.Event[tk.Misc]) -> None:
        """Finish a middle-button pan and restore the default cursor."""
        self._pan_anchor = None
        self.canvas.configure(cursor="")

    def zoom_camera(self, event: tk.Event[tk.Misc], direction: int | None = None) -> None:
        """Zoom around the pointer while keeping its world coordinate fixed."""
        direction = direction if direction is not None else (1 if event.delta > 0 else -1)
        old_world = self.screen_to_world((event.x, event.y))
        self.camera_zoom = max(0.35, min(3.0, self.camera_zoom * (1.15 if direction > 0 else 1 / 1.15)))
        self.camera_x = old_world[0] - event.x / self.camera_zoom
        self.camera_y = old_world[1] - event.y / self.camera_zoom
        self.redraw_world()

    def reset_camera(self) -> None:
        """Restore the blank-map center or merge-demo origin at 1× zoom."""
        if self.blank_map:
            self.camera_x = (self.city_map.width - WIDTH) / 2
            self.camera_y = (self.city_map.height - HEIGHT) / 2
        else:
            self.camera_x = self.camera_y = 0.0
        self.camera_zoom = 1.0
        self.redraw_world()

    def draw_car(self, car: Car) -> None:
        """Create if needed and update all canvas polygons for one vehicle."""
        if car.item is None or not car.detail_items:
            if car.item is not None:
                self.canvas.delete(car.item)
            car.item = self.create_car_details(car)
        assert car.item is not None
        # The next lane point gives the car's heading; completed paths face right.
        if car.next_point < len(car.lane.points):
            target_x, target_y = car.lane.points[car.next_point]
            angle = atan2(target_y - car.y, target_x - car.x)
        else:
            angle = 0.0
        forward_x, forward_y = cos(angle), sin(angle)
        side_x, side_y = -forward_y, forward_x
        self.canvas.coords(car.item, *self.screen_oriented_box(
            car.x, car.y, forward_x, forward_y, side_x, side_y, car.length / 2, car.width / 2,
        ))
        self.canvas.itemconfigure(car.item, fill=car.color)
        wheel_positions = (
            (car.length * WHEEL_CENTER_LENGTH_RATIO, car.width * WHEEL_CENTER_WIDTH_RATIO),
            (car.length * WHEEL_CENTER_LENGTH_RATIO, -car.width * WHEEL_CENTER_WIDTH_RATIO),
            (-car.length * WHEEL_CENTER_LENGTH_RATIO, car.width * WHEEL_CENTER_WIDTH_RATIO),
            (-car.length * WHEEL_CENTER_LENGTH_RATIO, -car.width * WHEEL_CENTER_WIDTH_RATIO),
        )
        # The first four detail IDs are wheels; later IDs are lights and glass.
        for item, (forward, side) in zip(car.detail_items[:4], wheel_positions):
            x = car.x + forward_x * forward + side_x * side
            y = car.y + forward_y * forward + side_y * side
            self.canvas.coords(item, *self.screen_oriented_box(
                x, y, forward_x, forward_y, side_x, side_y,
                car.length * WHEEL_HALF_LENGTH_RATIO,
                car.width * WHEEL_HALF_WIDTH_RATIO,
            ))
        # Headlights are detail items four and five; the windshield follows.
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
        points = []
        for forward, side in ((half_length, half_width), (half_length, -half_width),
                              (-half_length, -half_width), (-half_length, half_width)):
            points.extend((x + forward_x * forward + side_x * side,
                           y + forward_y * forward + side_y * side))
        return points

    def screen_oriented_box(
        self, x: float, y: float, forward_x: float, forward_y: float,
        side_x: float, side_y: float, half_length: float, half_width: float,
    ) -> list[float]:
        """Project a world-space vehicle rectangle into the current camera view."""
        coordinates = self.oriented_box(x, y, forward_x, forward_y, side_x, side_y, half_length, half_width)
        return self.world_points(*list(zip(coordinates[::2], coordinates[1::2])))

    def create_car_details(self, car: Car) -> int:
        """Create a complete car visual and return its body canvas-item ID.

        Creation order is also render order: wheels sit behind the body, then
        headlights and windshield sit above it.
        """
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
            0, 0, 0, 0, fill="#8ecae6", outline="#29566b"
        )
        car.detail_items = [*wheels, *headlights, windshield]
        return body

    def add_car(self, start_random: bool = False) -> None:
        """Ask the simulation for a car and create its visual in merge-demo mode."""
        if self.blank_map:
            return
        car = self.simulation.add_car(start_random)
        
        car.item = self.create_car_details(car)
        self.draw_car(car)

    def clear_cars(self) -> None:
        """Delete every car visual, empty the fleet, and record the action."""
        for car in self.simulation.cars:
            self.canvas.delete(car.item)
            for item in car.detail_items:
                self.canvas.delete(item)
        self.simulation.cars.clear()
        self.simulation.record_event("cleared traffic")

    def toggle_running(self) -> None:
        """Pause or resume updates; canvas/event windows continue refreshing."""
        self.running = not self.running

    def set_simulation_speed(self, value: str) -> None:
        """Apply an Inspector speed slider value and log it as an event."""
        speed = float(value)
        if self.simulation_speed == speed:
            return
        self.simulation_speed = speed
        self.simulation.record_event(f"simulation speed {self.simulation_speed:g}x")

    def set_traffic(self, value: str) -> None:
        """Apply an Inspector target-fleet slider value and log it as an event."""
        target = int(float(value))
        if self.simulation.max_cars == target:
            return
        self.simulation.max_cars = target
        self.simulation.record_event(f"traffic target {self.simulation.max_cars}")

    def select_lane(self, lane: Lane) -> None:
        """Make ``lane`` the selected lane for Inspector global stats."""
        self.selected_lane = lane

    def set_selected_lane_gap(self, value: str) -> None:
        """Update and record a genuine following-gap change for one lane."""
        gap = float(value)
        if self.selected_lane.following_gap != gap:
            self.selected_lane.following_gap = gap
            self.simulation.record_event(f"{self.selected_lane.name} gap {gap:.0f}px")

    def set_unit_system(self, unit_system: str) -> None:
        """Switch UI units while preserving canonical model values and saves."""
        unit_system = validate_unit_system(unit_system)
        if self.unit_system == unit_system:
            return
        self.unit_system = unit_system
        self.draw_speed_limits()
        if self.active_tool is not None:
            self.active_tool.refresh()
        self.draw_analytics()

    def lane_at(self, position: Point) -> Lane | None:
        """Return a nearby merge-demo lane, or ``None`` if the click is off-road."""
        if self.blank_map:
            return None
        lane = min(self.simulation.lanes, key=lambda candidate: candidate.distance_to(position))
        return lane if lane.distance_to(position) <= LANE_HEIGHT / 2 else None

    def show_lane_menu(self, event: tk.Event[tk.Misc]) -> None:
        """Open the appropriate right-click menu for a sign or lane."""
        world_position = self.screen_to_world((event.x, event.y))
        # Signs take precedence over their underlying lane when hit-testing.
        speed_limit = self.speed_limit_at(*world_position)
        if speed_limit is not None:
            self.show_speedlimit_menu(event, speed_limit)
            return
        lane = self.lane_at(world_position)
        if lane is None:
            return
        self.select_lane(lane)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label=f"Set {lane.name} lane gap…", command=lambda: self.prompt_for_gap(lane))
        menu.add_command(
            label=f"Add {lane.name} speed-limit sign",
            command=lambda x=world_position[0], y=world_position[1], selected_lane=lane: self.add_speedlimit(
                x, y, selected_lane
            ),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    def speed_limit_at(self, x: float, y: float) -> SpeedLimit | None:
        """Return the sign under a right-click, if any."""
        for speed_limit in reversed(self.simulation.speed_limits):
            if abs(speed_limit.x - x) <= 25 and abs(speed_limit.y - y) <= 42:
                return speed_limit
        return None

    def show_speedlimit_menu(
        self, event: tk.Event[tk.Misc], speed_limit: SpeedLimit
    ) -> None:
        """Offer edits for an existing sign instead of adding another one."""
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label=f"Change {mph_to_display(speed_limit.speed, self.unit_system):.0f} {speed_unit(self.unit_system)} limit",
            command=lambda: self.change_speed_limit(speed_limit),
        )
        menu.add_command(
            label=f"Delete {speed_limit.speed:.0f} mph limit",
            command=lambda: self.delete_speed_limit(speed_limit),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def prompt_for_gap(self, lane: Lane) -> None:
        """Prompt for a lane following gap, record a change, and select that lane."""
        unit = distance_unit(self.unit_system)
        gap = simpledialog.askfloat(
            "Following gap", f"Preferred following gap for the {lane.name} lane ({unit}):",
            parent=self.root,
            initialvalue=pixels_to_display_distance(lane.following_gap, self.unit_system),
            minvalue=pixels_to_display_distance(30.0, self.unit_system),
            maxvalue=pixels_to_display_distance(180.0, self.unit_system),
        )
        if gap is not None:
            gap_pixels = display_distance_to_pixels(gap, self.unit_system)
            if lane.following_gap != gap_pixels:
                lane.following_gap = gap_pixels
                self.simulation.record_event(f"{lane.name} gap {gap:.0f} {unit}")
            self.select_lane(lane)

    def add_speedlimit(self, x: float, y: float, lane: Lane) -> None:
        """Post and draw a speed-limit sign at the selected lane location."""
        minimum, maximum = speed_limit_bounds(self.unit_system)
        unit = speed_unit(self.unit_system)
        speed = simpledialog.askfloat(
            "Speed", f"Speed limit for sign ({unit})",
            parent=self.root, initialvalue=mph_to_display(DEFAULT_SPEED_LIMIT_MPH, self.unit_system),
            minvalue=minimum, maxvalue=maximum,
        )
        if speed is None:
            return
        self.simulation.add_speed_limit(display_to_mph(speed, self.unit_system), lane, x, y)
        self.draw_speed_limits()

    def change_speed_limit(self, speed_limit: SpeedLimit) -> None:
        """Prompt for and apply a sign speed in the selected display unit."""
        minimum, maximum = speed_limit_bounds(self.unit_system)
        unit = speed_unit(self.unit_system)
        speed = simpledialog.askfloat(
            "Speed limit", f"Speed limit ({unit}):", parent=self.root,
            initialvalue=mph_to_display(speed_limit.speed, self.unit_system), minvalue=minimum, maxvalue=maximum,
        )
        if speed is not None:
            speed_limit.speed = display_to_mph(speed, self.unit_system)
            self.simulation.record_event(
                f"{speed_limit.lane.name} limit changed to {speed:.0f} {unit}"
            )
            self.draw_speed_limits()

    def delete_speed_limit(self, speed_limit: SpeedLimit) -> None:
        """Remove one sign through the simulation and rebuild its visual layer."""
        self.simulation.remove_speed_limit(speed_limit)
        self.draw_speed_limits()

    def draw_speed_limits(self) -> None:
        """Redraw all signs after a sign is added, changed, or deleted.

        All sign components share a tag so the layer can be recreated and
        raised above moving cars as one unit.
        """
        self.canvas.delete("speed_limit")
        for speed_limit in self.simulation.speed_limits:
            x, y = self.world_to_screen((speed_limit.x, speed_limit.y))
            scale = self.camera_zoom
            self.canvas.create_rectangle(x - 25 * scale, y - 32 * scale, x + 25 * scale, y + 42 * scale,
                                         fill="#f8f8f8", outline="#20252a", width=2,
                                         tags="speed_limit")
            self.canvas.create_text(x, y - 12 * scale, text="SPEED", fill="#20252a",
                                    font=("Arial", max(6, int(8 * scale)), "bold"), tags="speed_limit")
            self.canvas.create_text(x, y + 6 * scale, text="LIMIT", fill="#20252a",
                                    font=("Arial", max(6, int(8 * scale)), "bold"), tags="speed_limit")
            self.canvas.create_text(x, y + 24 * scale,
                                    text=f"{mph_to_display(speed_limit.speed, self.unit_system):.0f}",
                                    fill="#20252a", font=("Arial", max(8, int(12 * scale)), "bold"),
                                    tags="speed_limit")

    def show_analytics(self) -> None:
        """Show sampled speed/throughput with state-change markers."""
        if self.analytics_window is None or not self.analytics_window.winfo_exists():
            self.analytics_window = tk.Toplevel(self.root)
            self.analytics_window.title("Traffic analytics")
            self.analytics_canvas = tk.Canvas(self.analytics_window, width=800, height=380, bg="white")
            self.analytics_canvas.pack()
            tk.Button(self.analytics_window, text="Export CSV", command=self.export_csv).pack(side="left", padx=8, pady=6)
            tk.Button(self.analytics_window, text="Export SVG", command=self.export_svg).pack(side="left", padx=8, pady=6)
        else:
            self.analytics_window.lift()
        self.draw_analytics()

    def draw_analytics(self) -> None:
        """Redraw the live analytics graph without creating another window.

        The blue line is average speed in the selected unit; orange is flow.
        series are independently scaled to fit the same plot area.
        """
        if (
            self.analytics_window is None
            or not self.analytics_window.winfo_exists()
            or self.analytics_canvas is None
        ):
            self.analytics_window = None
            self.analytics_canvas = None
            return
        canvas = self.analytics_canvas
        canvas.delete("all")
        history = self.simulation.history
        canvas.create_text(20, 12, anchor="nw", text="Timeline (state changes)", font=("Arial", 10, "bold"))
        if not history:
            canvas.create_text(400, 190, text="Waiting for samples…")
            return
        start = history[0][0]
        end = max(history[-1][0], start + 1)
        project_x = lambda t: 55 + (t - start) / (end - start) * 720
        # The event markers make recent configuration changes visible in time.
        for timestamp, description in self.simulation.events[-12:]:
            if start <= timestamp <= end:
                x = project_x(timestamp)
                canvas.create_line(x, 28, x, 58, fill="#777")
                canvas.create_text(x, 25, text=description[:18], anchor="s", angle=45, font=("Arial", 7))
        canvas.create_rectangle(55, 70, 775, 340, outline="#888")
        display_speeds = [mph_to_display(row[1], self.unit_system) for row in history]
        max_speed = max(mph_to_display(DEFAULT_SPEED_LIMIT_MPH, self.unit_system), *display_speeds)
        max_flow = max(5.0, *(row[2] for row in history))
        speed_points, flow_points = [], []
        for (timestamp, _speed, flow), speed in zip(history, display_speeds):
            x = project_x(timestamp)
            speed_points.extend((x, 340 - speed / max_speed * 250))
            flow_points.extend((x, 340 - flow / max_flow * 250))
        if len(speed_points) >= 4:
            canvas.create_line(*speed_points, fill="#1976d2", width=2)
            canvas.create_line(*flow_points, fill="#e65100", width=2)
        canvas.create_text(60, 355, anchor="w", text=f"Blue: average {speed_unit(self.unit_system)}    Orange: exits/min")

    def create_recent_changes_window(self) -> None:
        """Show a compact live timeline of events from the last 10 simulated minutes."""
        if self.recent_window is not None and self.recent_window.winfo_exists():
            self.recent_window.lift()
            return
        self.recent_window = tk.Toplevel(self.root)
        self.recent_window.title("Recent changes")
        right_x = self.root.winfo_screenwidth() - 380
        bottom_y = self.root.winfo_screenheight() - 270
        self.recent_window.geometry(f"360x220+{right_x}+{bottom_y}")
        self.recent_canvas = tk.Canvas(self.recent_window, width=360, height=220, bg="#182028")
        self.recent_canvas.pack(fill="both", expand=True)
        self.draw_recent_changes()

    def draw_recent_changes(self) -> None:
        """Render the ten newest events within the last 600 simulated seconds."""
        if self.recent_canvas is None or not self.recent_canvas.winfo_exists():
            return
        canvas = self.recent_canvas
        canvas.delete("all")
        now = self.simulation.simulation_time
        events = [(time, text) for time, text in self.simulation.events if time >= now - 600][-10:]
        canvas.create_text(12, 12, anchor="nw", text="Recent changes — last 10 simulated minutes",
                           fill="#d9e7f2", font=("Arial", 10, "bold"))
        for index, (timestamp, text) in enumerate(reversed(events)):
            y = 42 + index * 17
            canvas.create_oval(12, y, 18, y + 6, fill="#f1c40f", outline="")
            canvas.create_text(26, y + 3, anchor="w", text=f"{timestamp:6.1f}s  {text}",
                               fill="#d9e7f2", font=("Courier", 9))

    def report_callback_exception(self, exception_type: type[BaseException], value: BaseException, trace) -> None:
        """Show Tkinter callback failures in the in-app debug panel as well as stderr."""
        formatted = "".join(traceback.format_exception(exception_type, value, trace)).rstrip()
        self.recent_errors.append(formatted)
        self.recent_errors = self.recent_errors[-3:]
        print(formatted)

    def export_csv(self) -> None:
        """Write sampled time, average speed, and flow metrics to a CSV file."""
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(("simulation_seconds", f"average_{speed_unit(self.unit_system)}", "exits_per_minute"))
            writer.writerows(
                (timestamp, mph_to_display(speed, self.unit_system), flow)
                for timestamp, speed, flow in self.simulation.history
            )

    def export_svg(self) -> None:
        """Write the average-speed history as a compact standalone SVG plot."""
        path = filedialog.asksaveasfilename(defaultextension=".svg", filetypes=[("SVG", "*.svg")])
        if not path:
            return
        history = self.simulation.history
        if not history:
            return
        start, end = history[0][0], max(history[-1][0], history[0][0] + 1)
        display_speeds = [mph_to_display(row[1], self.unit_system) for row in history]
        max_speed = max(mph_to_display(DEFAULT_SPEED_LIMIT_MPH, self.unit_system), *display_speeds)
        points = " ".join(
            f"{55 + (timestamp - start) / (end - start) * 720:.1f},{340 - speed / max_speed * 250:.1f}"
            for (timestamp, _speed, _flow), speed in zip(history, display_speeds)
        )
        with open(path, "w", encoding="utf-8") as output:
            output.write(
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="380">'
                '<rect x="55" y="70" width="720" height="270" fill="white" stroke="#888"/>'
                f'<polyline points="{points}" fill="none" stroke="#1976d2" stroke-width="2"/>'
                f'<text x="60" y="355">Average {speed_unit(self.unit_system)}</text></svg>'
            )

    def save_state(self) -> None:
        """Serialize the merge-demo model state; Tkinter canvas IDs are omitted."""
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        state = {"scenario": "merge_demo", "time": self.simulation.simulation_time, "lanes": {lane.name: lane.following_gap for lane in self.simulation.lanes},
                 "speed_limits": [{"speed": sign.speed, "lane": sign.lane.name, "x": sign.x, "y": sign.y} for sign in self.simulation.speed_limits],
                 "cars": [{"lane": car.lane.name, "x": car.x, "y": car.y, "speed": car.speed, "cruise": car.cruise_speed, "color": car.color, "next": car.next_point, "preference": car.speed_preference_mph} for car in self.simulation.cars]}
        with open(path, "w", encoding="utf-8") as output:
            json.dump(state, output)

    def new_world(self) -> None:
        """Replace the current scenario with a fresh blank city-builder world."""
        if not messagebox.askyesno(
            "New world", "Create a new blank world? Unsaved changes will be lost."
        ):
            return
        # Replacing both models clears merge-specific lanes, traffic, signs,
        # metrics, and events before returning to the city-builder view.
        self.clear_cars()
        self.simulation = TrafficSimulation()
        self.city_map = CityMap()
        self.blank_map = True
        self.select_lane(self.simulation.lanes[0])
        for tool in self.tools:
            if isinstance(tool, CanvasTool):
                tool.reset()
        self.reset_camera()

    def load_state(self) -> None:
        """Load a merge-demo JSON save and recreate its dynamic canvas items."""
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, encoding="utf-8") as source:
            state = json.load(source)
        # Other scenario schemas are intentionally ignored by this UI.
        if state.get("scenario", "merge_demo") != "merge_demo":
            return
        for tool in self.tools:
            if isinstance(tool, CanvasTool):
                tool.reset()
        self.clear_cars()
        self.blank_map = False
        self.reset_camera()
        lanes = {lane.name: lane for lane in self.simulation.lanes}
        for name, gap in state["lanes"].items(): lanes[name].following_gap = gap
        self.simulation.speed_limits.clear()
        for sign in state["speed_limits"]: self.simulation.add_speed_limit(sign["speed"], lanes[sign["lane"]], sign["x"], sign["y"])
        for saved in state["cars"]:
            car = Car(lanes[saved["lane"]], saved["x"], saved["y"], saved["speed"], saved["cruise"], saved["color"], next_point=saved["next"], speed_preference_mph=saved["preference"])
            self.simulation.cars.append(car); car.item = self.create_car_details(car); self.draw_car(car)
        self.simulation.simulation_time = state["time"]
        self.draw_scene()
        self.draw_speed_limits()

    def exit_app(self) -> None:
        """Close the Tk application after a confirmation dialog."""
        if messagebox.askyesno("Exit simulator", "Exit the freeway simulator?"):
            self.root.destroy()

    def draw_merge_debug(self) -> None:
        """Refresh merge diagnostics and the latest captured callback error."""
        if self.debug_canvas is None or not self.debug_canvas.winfo_exists():
            return
        self.debug_canvas.delete("all")
        self.debug_canvas.create_rectangle(0, 0, 500, 260, fill="#182028", outline="#54616e")
        lines = self.simulation.merge_debug_lines()
        if self.recent_errors:
            lines.extend(("", "PYTHON ERRORS:", *self.recent_errors[-1].splitlines()[-3:]))
        self.debug_canvas.create_text(14, 14, anchor="nw",
                                text="\n".join(lines), fill="#d9e7f2",
                                font=("Courier", 10))

    def create_debug_window(self) -> None:
        """Create a separate live window for merge state and captured errors."""
        if self.debug_window is not None and self.debug_window.winfo_exists():
            return
        self.debug_window = tk.Toplevel(self.root)
        self.debug_window.title("Simulator debug")
        bottom_y = self.root.winfo_screenheight() - 310
        self.debug_window.geometry(f"500x260+0+{bottom_y}")
        self.debug_canvas = tk.Canvas(self.debug_window, width=500, height=260, highlightthickness=0)
        self.debug_canvas.pack(fill="both", expand=True)
        self.draw_merge_debug()

    def tick(self) -> None:
        """Advance traffic, refresh UI state, and schedule the next ~60 Hz frame."""
        now = time.perf_counter()
        # Avoid a large simulation jump when the window/event loop stalls.
        dt = min(now - self.last_time, 0.1)
        self.last_time = now
        if self.running and not self.blank_map:
            # update() returns cars that left the world so their visuals can go.
            for car in self.simulation.update(dt * self.simulation_speed):
                self.canvas.delete(car.item)
                for item in car.detail_items:
                    self.canvas.delete(item)
            for car in self.simulation.cars:
                if car.item is None:
                    car.item = self.create_car_details(car)
                self.draw_car(car)
                # Signs are the top dynamic layer and remain legible over cars.
                self.canvas.tag_raise("speed_limit")
        if self.active_tool is not None:
            self.active_tool.refresh()
        self.draw_merge_debug()
        # Graph/event windows need not redraw at the animation frame rate.
        if now - self.last_dashboard_refresh >= 1.0:
            self.draw_analytics()
            self.draw_recent_changes()
            self.last_dashboard_refresh = now
        self.root.after(16, self.tick)
