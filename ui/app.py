"""Main Tkinter application coordinator."""

from __future__ import annotations

import time
import tkinter as tk
from types import SimpleNamespace

from city import CityMap
from config import DEFAULT_UNIT_SYSTEM, HEIGHT, WIDTH
from construction import ConstructionSimulation, UnlimitedConstructionProvider
from land_ports import ensure_western_land_port, land_port_focus_point
from resources import load_construction_catalog, validate_resource_references
from simulation import TrafficSimulation
from traffic_testbed import RoadVehicleSimulation
from traffic_debugger import TrafficDebugger
from ui_tools import CanvasTool, CanvasToolDropdown, ToolbarTool, load_toolbar_tools
from ui_tools.buildables import load_buildables
from units import validate_unit_system

from .base import SPEED_LIMIT_TAG
from .dashboards import DashboardMixin
from .files import FileActionsMixin
from .interactions import InteractionMixin
from .renderer import (
    RendererMixin,
    ROAD_VEHICLE_CAR_TAG,
    TEST_TRAFFIC_SOURCE_TAG,
)
from .viewport import Viewport, ViewportMixin, city_builder_viewport_origin
from .camera3d import OrbitCamera


PERFORMANCE_HISTORY_SECONDS = 20.0
PERFORMANCE_REFRESH_SECONDS = 0.25


class FreewaySimulator(
    FileActionsMixin,
    DashboardMixin,
    InteractionMixin,
    RendererMixin,
    ViewportMixin,
):
    """Coordinate models, windows, tools, rendering, and simulation ticks."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Freeway Simulator")
        root.report_callback_exception = self.report_callback_exception
        root.protocol("WM_DELETE_WINDOW", self.exit_app)

        self.running = True
        self.simulation_speed = 1.0
        self.unit_system = validate_unit_system(DEFAULT_UNIT_SYSTEM)
        self.simulation = TrafficSimulation()
        self.city_map = CityMap()
        ensure_western_land_port(self.city_map)
        # All constructed-road actors share this occupancy and priority model.
        self.road_vehicles = RoadVehicleSimulation(
            update_mode="data_first",
            debugger=TrafficDebugger(),
        )
        self.test_traffic = self.road_vehicles
        construction_resources, construction_trucks = load_construction_catalog()
        validate_resource_references(load_buildables(), construction_resources)
        self.construction_simulation = ConstructionSimulation(
            construction_resources,
            construction_trucks,
            UnlimitedConstructionProvider(),
            road_vehicles=self.road_vehicles,
        )
        self.blank_map = True
        self.viewport = Viewport(*city_builder_viewport_origin(self.city_map.height))
        self._pan_anchor: tuple[int, int] | None = None
        self.view3d_active = False
        self.view3d = None
        self._saved_3d_camera_state: dict[str, object] | None = None

        self.analytics_window: tk.Toplevel | None = None
        self.analytics_canvas: tk.Canvas | None = None
        self.performance_window: tk.Toplevel | None = None
        self.performance_canvas: tk.Canvas | None = None
        self.recent_window: tk.Toplevel | None = None
        self.recent_canvas: tk.Canvas | None = None
        self.debug_window: tk.Toplevel | None = None
        self.debug_canvas: tk.Canvas | None = None
        self.recent_errors: list[str] = []
        self.selected_lane = self.simulation.lanes[0]

        self.tools: list[ToolbarTool] = load_toolbar_tools(self)
        self.inspector_tool = next(
            (tool for item in self.tools for tool in item.iter_canvas_tools()
             if getattr(tool, "provides_inspector", False)),
            None,
        )
        self.active_tool: CanvasTool | None = None
        self.last_time = time.perf_counter()
        self.performance_start_time = self.last_time
        self.frame_history: list[tuple[float, float]] = []
        self._has_ticked = False
        self.last_dashboard_refresh = 0.0
        self.last_performance_refresh = 0.0

        self.build_toolbar()
        self.viewport_shell = tk.Frame(root)
        self.viewport_shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(self.viewport_shell, width=500, bg="#e8edf2")
        self.sidebar.pack_propagate(False)
        self.canvas = tk.Canvas(
            self.viewport_shell, width=WIDTH, height=HEIGHT,
            highlightthickness=0, bg="#e83ccb",
        )
        self.canvas.pack(fill="both", expand=True)
        self._bind_canvas_events()
        self.root.after_idle(self.draw_scene)
        self.create_debug_window()
        self.create_recent_changes_window()
        self.tick()

    def build_toolbar(self) -> None:
        toolbar = tk.Frame(self.root, padx=10, pady=8, bg="#e8edf2")
        toolbar.pack(fill="x")
        self.active_menu_area = tk.Frame(
            toolbar, width=90, height=28, bg="#e8edf2",
        )
        self.active_menu_area.pack(side="left", padx=(0, 8))
        self.active_menu_area.pack_propagate(False)
        ordinary_tools = tk.Frame(toolbar, bg="#e8edf2")
        ordinary_tools.pack(side="left")
        for index, tool in enumerate(self.tools):
            tool.build(ordinary_tools).grid(row=0, column=index, padx=(8, 0) if index else 0)
        self.camera_label = tk.Label(
            toolbar, text="Pan: middle-drag · Zoom: wheel", bg="#e8edf2",
        )
        self.camera_label.pack(side="left", padx=(12, 0))
        self.view_button = tk.Button(
            toolbar, text="3D roads", command=self.toggle_3d_view, bg="#e8edf2",
        )
        self.view_button.pack(side="right")
        from ui_tools.menu_theme import style_panel
        style_panel(toolbar)

    def _bind_canvas_events(self) -> None:
        self.canvas.bind("<Button-1>", self.handle_tool_click)
        self.canvas.bind("<Motion>", self.handle_tool_motion)
        self.canvas.bind("<Button-3>", self.show_lane_menu)
        self.canvas.bind("<ButtonPress-2>", self.start_pan)
        self.canvas.bind("<B2-Motion>", self.pan_camera)
        self.canvas.bind("<ButtonRelease-2>", self.end_pan)
        self.canvas.bind("<MouseWheel>", self.zoom_camera)
        self.canvas.bind("<Button-4>", lambda event: self.zoom_camera(event, 1))
        self.canvas.bind("<Button-5>", lambda event: self.zoom_camera(event, -1))
        self.canvas.bind("<Configure>", lambda _event: self.redraw_world())

    def select_tool(self, tool: CanvasTool) -> None:
        if self.view3d_active:
            from ui_tools.tools.road_tool import RoadTool
            if not isinstance(tool, RoadTool):
                self.toggle_3d_view()
        if self.active_tool is tool:
            self.deactivate_tool(tool)
            return
        if self.active_tool is not None:
            self.active_tool.deactivate()
        self.active_tool = tool
        self.update_tool_buttons()
        tool.activate()

    def deactivate_tool(self, tool: CanvasTool) -> None:
        if self.active_tool is not tool:
            return
        tool.deactivate()
        self.active_tool = None
        self.update_tool_buttons()

    def update_tool_buttons(self) -> None:
        for tool in self.tools:
            if isinstance(tool, CanvasTool):
                tool.set_active(self.active_tool is tool)
            elif isinstance(tool, CanvasToolDropdown):
                tool.set_active_tool(self.active_tool)

    def handle_tool_click(self, event: tk.Event[tk.Misc]) -> None:
        if self.active_tool is not None:
            self.active_tool.on_canvas_click(event)

    def handle_tool_motion(self, event: tk.Event[tk.Misc]) -> None:
        if self.active_tool is not None:
            self.active_tool.on_canvas_motion(event)

    def toggle_3d_view(self) -> None:
        """Swap the map canvas for a 3D road view in the same Tk window."""
        if self.active_tool is not None:
            self.deactivate_tool(self.active_tool)
        if self.view3d_active:
            assert self.view3d is not None
            self.view3d.frame.pack_forget()
            self.sidebar.pack_forget()
            self.canvas.pack(fill="both", expand=True)
            self.view3d_active = False
            self.view_button.configure(text="3D roads")
            self.camera_label.configure(text="Pan: middle-drag · Zoom: wheel")
            self.redraw_world()
            return
        if self.view3d is None:
            try:
                from .view3d import PandaWorldView
            except ImportError as error:
                from tkinter import messagebox
                messagebox.showerror(
                    "3D roads", "Panda3D is required. Install requirements.txt first.",
                    parent=self.root,
                )
                return
            self.view3d = PandaWorldView(self.viewport_shell)
            self.view3d.set_callbacks(
                on_click=self._handle_3d_click,
                on_motion=self._handle_3d_motion,
                on_key=self._handle_3d_key,
            )
        self.canvas.pack_forget()
        self.sidebar.pack(side="right", fill="y")
        self.view3d.frame.pack(side="left", fill="both", expand=True)
        self.view3d_active = True
        self.view_button.configure(text="2D map")
        self.camera_label.configure(
            text="Orbit: right-drag · Pan: middle-drag · Zoom: wheel · Height: Page Up/Down",
        )
        self.root.update_idletasks()
        self.view3d.step()
        self.view3d.show_city(self.city_map)
        if self._saved_3d_camera_state is not None:
            self.restore_3d_camera(self._saved_3d_camera_state)

    def camera_3d_state(self) -> dict[str, object] | None:
        if self.view3d is None:
            return self._saved_3d_camera_state
        orbit = self.view3d.orbit
        return {
            "target": list(orbit.target),
            "yaw": orbit.yaw,
            "pitch": orbit.pitch,
            "distance": orbit.distance,
        }

    def restore_3d_camera(self, state: dict[str, object] | None) -> None:
        """Keep a loaded camera until the 3D view exists, then apply it."""
        if self.view3d is None:
            self._saved_3d_camera_state = state
            return
        self._saved_3d_camera_state = None
        if state is None:
            self.view3d.orbit = OrbitCamera(
                (*land_port_focus_point(self.city_map), 0),
            )
        else:
            target = state["target"]
            self.view3d.orbit = OrbitCamera(
                (float(target[0]), float(target[1]), float(target[2])),
                yaw=float(state["yaw"]),
                pitch=float(state["pitch"]),
                distance=float(state["distance"]),
            )
        self.view3d._apply_camera()

    def road_point_from_event(
        self, event: object, elevation: float,
    ) -> tuple[float, float] | None:
        if self.view3d_active and self.view3d is not None:
            return self.view3d.point_at_screen(event.x, event.y, elevation)
        return self.screen_to_world((event.x, event.y))

    def road_endpoint_from_event(
        self, event: object,
    ) -> tuple[tuple[float, float], float] | None:
        if self.view3d_active and self.view3d is not None:
            return self.view3d.nearest_road_endpoint(event.x, event.y)
        return None

    def _handle_3d_click(self, x: int, y: int) -> None:
        if self.active_tool is not None:
            self.handle_tool_click(SimpleNamespace(x=x, y=y))

    def _handle_3d_motion(self, x: int, y: int) -> None:
        if self.active_tool is not None:
            self.handle_tool_motion(SimpleNamespace(x=x, y=y))

    def _handle_3d_key(self, key: str) -> None:
        from ui_tools.tools.road_tool import RoadTool
        if not isinstance(self.active_tool, RoadTool):
            return
        if key == "page_up":
            self.active_tool.adjust_elevation(1)
        elif key == "page_down":
            self.active_tool.adjust_elevation(-1)
        elif key == "enter":
            self.active_tool.finish()
        elif key == "escape":
            self.active_tool.cancel()
        self.active_tool.refresh()

    def redraw_world(self) -> None:
        FreewaySimulator._sync_road_network(self)
        RendererMixin.redraw_world(self)
        if self.view3d_active and self.view3d is not None:
            self.view3d.show_city(self.city_map)

    def reset_camera(self) -> None:
        if self.view3d_active and self.view3d is not None:
            self.view3d.orbit = OrbitCamera(
                (self.city_map.width / 2, self.city_map.height / 2, 0),
            )
            self.view3d.show_city(self.city_map)
            return
        ViewportMixin.reset_camera(self)

    def _sync_road_network(self) -> None:
        """Remove canvas items for actors invalidated by a lane-graph rebuild."""
        sync_network = getattr(self.construction_simulation, "sync_network", None)
        if callable(sync_network):
            for car in sync_network(self.city_map):
                if car.item is not None:
                    self.canvas.delete(car.item)
                for item in car.signal_items:
                    self.canvas.delete(item)

    def _update_construction(self, elapsed_seconds: float) -> None:
        """Advance construction demand and refresh its runtime truck markers."""
        FreewaySimulator._sync_road_network(self)
        if self.running:
            phases = {
                building.id: building.phase
                for building in self.city_map.buildings
            }
            self.construction_simulation.update(
                self.city_map,
                elapsed_seconds * self.simulation_speed,
            )
            if any(
                phases.get(building.id) != building.phase
                for building in self.city_map.buildings
            ):
                self.redraw_world()
        self.draw_road_vehicles()

    def tick(self) -> None:
        """Advance traffic, refresh tools/windows, and schedule the next frame."""
        now = time.perf_counter()
        frame_interval = max(0.0, now - self.last_time)
        dt = min(frame_interval, 0.1)
        self.last_time = now
        if self._has_ticked:
            elapsed = now - self.performance_start_time
            self.frame_history.append((elapsed, frame_interval))
            cutoff = elapsed - PERFORMANCE_HISTORY_SECONDS
            self.frame_history = [
                sample for sample in self.frame_history if sample[0] >= cutoff
            ]
        self._has_ticked = True
        if self.running and not self.blank_map:
            for car in self.simulation.update(dt * self.simulation_speed):
                self.canvas.delete(car.item)
                for item in car.detail_items:
                    self.canvas.delete(item)
            for car in self.simulation.cars:
                if car.item is None:
                    car.item = self.create_car_details(car)
                self.draw_road_vehicle(car)
                self.canvas.tag_raise(SPEED_LIMIT_TAG)
        self._update_construction(dt)
        if self.running:
            for car in self.construction_simulation.completed_road_vehicles:
                if car.item is not None:
                    self.canvas.delete(car.item)
                for item in car.signal_items:
                    self.canvas.delete(item)
        if self.view3d_active and self.view3d is not None:
            self.view3d.update_road_vehicles(self.road_vehicles)
            self.view3d.step()
        self.canvas.tag_raise(ROAD_VEHICLE_CAR_TAG)
        self.canvas.tag_raise(TEST_TRAFFIC_SOURCE_TAG)
        self.canvas.tag_raise(SPEED_LIMIT_TAG)
        if self.active_tool is not None:
            self.active_tool.refresh()
        if self.inspector_tool is not None and self.active_tool is not self.inspector_tool:
            self.inspector_tool.refresh()
        self.draw_merge_debug()
        if now - self.last_dashboard_refresh >= 1.0:
            self.draw_analytics()
            self.draw_recent_changes()
            self.last_dashboard_refresh = now
        if now - self.last_performance_refresh >= PERFORMANCE_REFRESH_SECONDS:
            self.draw_performance_graph()
            self.last_performance_refresh = now
        self.root.after(16, self.tick)
