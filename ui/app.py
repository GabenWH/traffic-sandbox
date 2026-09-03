"""Main Tkinter application coordinator."""

from __future__ import annotations

import time
import tkinter as tk

from city import CityMap
from config import DEFAULT_UNIT_SYSTEM, HEIGHT, WIDTH
from simulation import TrafficSimulation
from traffic_testbed import TestTrafficSimulation
from ui_tools import CanvasTool, CanvasToolDropdown, ToolbarTool, load_toolbar_tools
from units import validate_unit_system

from .base import SPEED_LIMIT_TAG
from .dashboards import DashboardMixin
from .files import FileActionsMixin
from .interactions import InteractionMixin
from .renderer import (
    RendererMixin,
    TEST_TRAFFIC_CAR_TAG,
    TEST_TRAFFIC_SOURCE_TAG,
)
from .viewport import Viewport, ViewportMixin


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

        self.running = True
        self.simulation_speed = 1.0
        self.unit_system = validate_unit_system(DEFAULT_UNIT_SYSTEM)
        self.simulation = TrafficSimulation()
        self.city_map = CityMap()
        self.test_traffic = TestTrafficSimulation()
        self.blank_map = True
        self.viewport = Viewport(
            (self.city_map.width - WIDTH) / 2,
            (self.city_map.height - HEIGHT) / 2,
        )
        self._pan_anchor: tuple[int, int] | None = None

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
        self.canvas = tk.Canvas(
            root, width=WIDTH, height=HEIGHT, highlightthickness=0, bg="#e83ccb",
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
                self.draw_car(car)
                self.canvas.tag_raise(SPEED_LIMIT_TAG)
        if self.running:
            for car in self.test_traffic.update(
                self.city_map,
                dt * self.simulation_speed,
            ):
                if car.item is not None:
                    self.canvas.delete(car.item)
                for item in car.signal_items:
                    self.canvas.delete(item)
        for car in self.test_traffic.cars:
            self.draw_test_car(car)
        self.canvas.tag_raise(TEST_TRAFFIC_CAR_TAG)
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
