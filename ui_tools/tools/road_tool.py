"""Polyline road-construction tool for the city builder."""

from __future__ import annotations

from math import dist
from types import SimpleNamespace
from typing import Any

from city import Building, Parcel, ZoneType
from ..buildables import BuildableSpec, buildables_of_kind
from ..buildables_panel import BuildablesPanel
from ..base import CanvasTool
from ..dropdown_tool import CanvasToolDropdown


TOOL_ID = "road"
MINIMUM_POINT_DISTANCE = 4.0


class RoadTool(CanvasTool):
    """Author road centrelines one vertex at a time."""

    name = "Build road"
    cursor = "crosshair"

    def __init__(
        self,
        host: Any,
        specs: tuple[BuildableSpec, ...] | None = None,
    ) -> None:
        super().__init__(host)
        self.specs = specs or buildables_of_kind("road")
        self.selected_spec = self.specs[0]
        self.points: list[tuple[float, float]] = []
        self.elevations: list[float] = []
        self.draft_elevation = 0.0
        self.pointer: tuple[float, float] | None = None
        self._pointer_screen: tuple[float, float] | None = None
        self.panel: BuildablesPanel | None = None
        self._return_binding: str | None = None
        self._escape_binding: str | None = None
        self._page_up_binding: str | None = None
        self._page_down_binding: str | None = None
        self._preview_dirty = True
        self._camera_state: tuple[float, float, float] | None = None

    def activate(self) -> None:
        self.host.canvas.configure(cursor=self.cursor)
        self.panel = BuildablesPanel(
            self.host,
            self,
            "Road buildables",
            self.specs,
            self.selected_spec,
            self._select_spec,
        )
        self.panel.show()
        self.panel.set_message(
            "Click road vertices · Page Up/Down changes height · Enter finishes · Esc cancels."
        )
        self._return_binding = self.host.root.bind("<Return>", self._finish_event, add="+")
        self._escape_binding = self.host.root.bind("<Escape>", self._cancel_event, add="+")
        self._page_up_binding = self.host.root.bind(
            "<Prior>", lambda _event: self.adjust_elevation(1), add="+",
        )
        self._page_down_binding = self.host.root.bind(
            "<Next>", lambda _event: self.adjust_elevation(-1), add="+",
        )
        self._preview_dirty = True
        self.refresh()

    def deactivate(self) -> None:
        self._unbind_keys()
        self.host.canvas.configure(cursor="")
        if self.panel is not None:
            self.panel.hide()
        self.panel = None
        self._clear_draft()

    def on_canvas_click(self, event: Any) -> None:
        self._pointer_screen = (event.x, event.y)
        endpoint = None
        if not self.points and getattr(self.host, "view3d_active", False):
            endpoint_picker = getattr(self.host, "road_endpoint_from_event", None)
            if endpoint_picker is not None:
                endpoint = endpoint_picker(event)
        if endpoint is None:
            point = self._point_from_event(event)
        else:
            point, self.draft_elevation = endpoint
        if point is None:
            return
        if self.points and dist(self.points[-1], point) < MINIMUM_POINT_DISTANCE:
            return
        self.points.append(point)
        self.elevations.append(self.draft_elevation)
        self.pointer = point
        self._preview_dirty = True

    def on_canvas_motion(self, event: Any) -> None:
        self._pointer_screen = (event.x, event.y)
        self.pointer = self._point_from_event(event)
        self._preview_dirty = True

    def _point_from_event(self, event: Any) -> tuple[float, float] | None:
        if getattr(self.host, "view3d_active", False):
            return self.host.road_point_from_event(event, self.draft_elevation)
        return self.host.screen_to_world((event.x, event.y))

    def adjust_elevation(self, direction: int) -> None:
        """Set the height of the next authored point in ten-foot steps."""
        self.draft_elevation = max(0.0, self.draft_elevation + 10 * direction)
        if self._pointer_screen is not None:
            x, y = self._pointer_screen
            self.pointer = self._point_from_event(SimpleNamespace(x=x, y=y))
        self._preview_dirty = True
        if self.panel is not None:
            self.panel.set_message(f"Next road point: {self.draft_elevation:g} ft high.")

    def refresh(self) -> None:
        camera_state = (self.host.camera_x, self.host.camera_y, self.host.camera_zoom)
        if camera_state != self._camera_state:
            self._camera_state = camera_state
            self._preview_dirty = True
        if self._preview_dirty:
            self._draw_preview()

    def finish(self) -> None:
        if len(self.points) < 2:
            self._preview_dirty = True
            return
        details = self.selected_spec.specs
        road = self.host.city_map.add_road(
            self.points,
            elevations=self.elevations or None,
            name=f"{self.selected_spec.name} {len(self.host.city_map.roads) + 1}",
            lane_width=float(details["lane_width"]),
            forward_lane_count=int(details["forward_lane_count"]),
            reverse_lane_count=int(details["reverse_lane_count"]),
            buildable_id=self.selected_spec.id,
        )
        self._clear_draft()
        self.host.redraw_world()
        if self.panel is not None:
            self.panel.set_message(f"Built {road.name}.")

    def cancel(self) -> None:
        self._clear_draft()

    def reset(self) -> None:
        self._clear_draft()

    def _select_spec(self, spec: BuildableSpec) -> None:
        self.selected_spec = spec
        self._preview_dirty = True

    def _finish_event(self, _event: Any) -> str:
        self.finish()
        return "break"

    def _cancel_event(self, _event: Any) -> str:
        self.cancel()
        return "break"

    def _clear_draft(self) -> None:
        self.points.clear()
        self.elevations.clear()
        self.draft_elevation = 0.0
        self.pointer = None
        self._pointer_screen = None
        self.host.canvas.delete("road_preview")
        if getattr(self.host, "view3d", None) is not None:
            self.host.view3d.clear_preview()
        self._preview_dirty = True

    def _draw_preview(self) -> None:
        if getattr(self.host, "view3d_active", False):
            self.host.view3d.show_road_preview(
                self.points, self.elevations, self.pointer, self.draft_elevation,
            )
            self._preview_dirty = False
            return
        canvas = self.host.canvas
        canvas.delete("road_preview")
        canvas.create_text(
            12, 12, anchor="nw",
            text="Click to add road points · Enter to finish · Esc to cancel",
            fill="#ffffff", font=("Arial", 11, "bold"),
            tags="road_preview",
        )
        preview_points = list(self.points)
        if self.pointer is not None and (not preview_points or self.pointer != preview_points[-1]):
            preview_points.append(self.pointer)
        if len(preview_points) >= 2:
            details = self.selected_spec.specs
            road_width = float(details["lane_width"]) * (
                int(details["forward_lane_count"]) + int(details["reverse_lane_count"])
            )
            canvas.create_line(
                *self.host.world_points(*preview_points),
                fill="#66d9ff", width=max(2, int(road_width * self.host.camera_zoom)),
                dash=(8, 5), joinstyle="round", tags="road_preview",
            )
        for point in self.points:
            x, y = self.host.world_to_screen(point)
            radius = 4
            canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                fill="#ffffff", outline="#168aad", tags="road_preview",
            )
        self._preview_dirty = False

    def _unbind_keys(self) -> None:
        if self._return_binding is not None:
            self.host.root.unbind("<Return>", self._return_binding)
            self._return_binding = None
        if self._escape_binding is not None:
            self.host.root.unbind("<Escape>", self._escape_binding)
            self._escape_binding = None
        if self._page_up_binding is not None:
            self.host.root.unbind("<Prior>", self._page_up_binding)
            self._page_up_binding = None
        if self._page_down_binding is not None:
            self.host.root.unbind("<Next>", self._page_down_binding)
            self._page_down_binding = None


class BuildingTool(CanvasTool):
    """Place JSON-defined building templates with one canvas click."""

    name = "Build building"
    cursor = "crosshair"

    def __init__(
        self,
        host: Any,
        specs: tuple[BuildableSpec, ...] | None = None,
    ) -> None:
        super().__init__(host)
        self.specs = specs or buildables_of_kind("building")
        self.selected_spec = self.specs[0]
        self.pointer: tuple[float, float] | None = None
        self.panel: BuildablesPanel | None = None
        self._escape_binding: str | None = None

    def activate(self) -> None:
        self.host.canvas.configure(cursor=self.cursor)
        self.panel = BuildablesPanel(
            self.host,
            self,
            "Building buildables",
            self.specs,
            self.selected_spec,
            self._select_spec,
        )
        self.panel.show()
        self.panel.set_message("Choose a template, then click the map to place it.")
        self._escape_binding = self.host.root.bind("<Escape>", self._escape_event, add="+")

    def deactivate(self) -> None:
        if self._escape_binding is not None:
            self.host.root.unbind("<Escape>", self._escape_binding)
            self._escape_binding = None
        self.host.canvas.configure(cursor="")
        self.host.canvas.delete("building_preview")
        if self.panel is not None:
            self.panel.hide()
        self.panel = None
        self.pointer = None

    def on_canvas_motion(self, event: Any) -> None:
        self.pointer = self.host.screen_to_world((event.x, event.y))
        self._draw_preview()

    def on_canvas_click(self, event: Any) -> None:
        self.place_building(self.host.screen_to_world((event.x, event.y)))

    def place_building(self, position: tuple[float, float]) -> Building | None:
        details = self.selected_spec.specs
        width, height = float(details["width"]), float(details["height"])
        x, y = position[0] - width / 2, position[1] - height / 2
        if x < 0 or y < 0 or x + width > self.host.city_map.width or y + height > self.host.city_map.height:
            if self.panel is not None:
                self.panel.set_message("The entire building must fit inside the city map.", error=True)
            return None
        parcel = Parcel(x, y, width, height, ZoneType(str(details["zone"])))
        building = Building(
            name=f"{self.selected_spec.name} {len(self.host.city_map.buildings) + 1}",
            parcel=parcel,
            residents=int(details["residents"]),
            jobs=int(details["jobs"]),
            buildable_id=self.selected_spec.id,
            color=str(details["color"]),
            construction_needs=dict(details.get("construction_needs", {})),
        )
        self.host.city_map.parcels.append(parcel)
        self.host.city_map.buildings.append(building)
        self.host.redraw_world()
        if self.panel is not None:
            self.panel.set_message(f"Placed {building.name}.")
        return building

    def _select_spec(self, spec: BuildableSpec) -> None:
        self.selected_spec = spec
        self._draw_preview()

    def _draw_preview(self) -> None:
        self.host.canvas.delete("building_preview")
        if self.pointer is None:
            return
        details = self.selected_spec.specs
        width, height = float(details["width"]), float(details["height"])
        x, y = self.pointer
        self.host.canvas.create_rectangle(
            *self.host.world_box(x - width / 2, y - height / 2, x + width / 2, y + height / 2),
            fill=str(details["color"]),
            outline="#ffffff",
            width=2,
            dash=(6, 4),
            tags="building_preview",
        )

    def _escape_event(self, _event: Any) -> str:
        self.host.deactivate_tool(self)
        return "break"

    def reset(self) -> None:
        self.pointer = None


class BuildTool(CanvasToolDropdown):
    """Keep city-construction canvas modes together in the Build menu."""

    name = "Build"

    def create_canvas_tools(self) -> list[CanvasTool]:
        return [RoadTool(self.host), BuildingTool(self.host)]


TOOL_CLASS = BuildTool
