"""Select junctions that generate temporary routed test traffic."""

from __future__ import annotations

from typing import Any

from .route_test_tool import constructed_junction_at
from ..base import CanvasTool


__test__ = False
TOOL_ID = "test_traffic"
TEST_TRAFFIC_TOOL_TAG = "test_traffic_tool_overlay"


class TestTrafficTool(CanvasTool):
    """Toggle intersections as combined car sources and destinations."""

    name = "Test traffic"
    cursor = "crosshair"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.message = "Select at least two intersections as traffic sources/sinks."
        self._escape_binding: str | None = None
        self._camera_state: tuple[float, float, float] | None = None
        self._dirty = True

    def activate(self) -> None:
        self.host.canvas.configure(cursor=self.cursor)
        self._escape_binding = self.host.root.bind(
            "<Escape>", self._escape_event, add="+",
        )
        self._dirty = True
        self.refresh()

    def deactivate(self) -> None:
        if self._escape_binding is not None:
            self.host.root.unbind("<Escape>", self._escape_binding)
            self._escape_binding = None
        self.host.canvas.configure(cursor="")
        self.host.canvas.delete(TEST_TRAFFIC_TOOL_TAG)

    def on_canvas_click(self, event: Any) -> None:
        position = self.host.screen_to_world((event.x, event.y))
        junction = constructed_junction_at(self.host.city_map, position)
        if junction is None:
            self.message = "No intersection there. Click inside a junction footprint."
            self._dirty = True
            return
        active = self.host.test_traffic.toggle_junction(junction)
        count = len(self.host.test_traffic.active_junction_ids)
        state = "enabled" if active else "disabled"
        self.message = (
            f"{state.title()} junction · {count} active source/sink"
            f"{'s' if count != 1 else ''}."
        )
        self.inspect_object(junction)
        self.host.draw_test_traffic_sources()
        self._dirty = True

    def refresh(self) -> None:
        camera_state = (
            self.host.camera_x,
            self.host.camera_y,
            self.host.camera_zoom,
        )
        if camera_state != self._camera_state:
            self._camera_state = camera_state
            self.host.draw_test_traffic_sources()
            self._dirty = True
        if not self._dirty:
            self.host.canvas.tag_raise(TEST_TRAFFIC_TOOL_TAG)
            return
        self.host.canvas.delete(TEST_TRAFFIC_TOOL_TAG)
        self.host.canvas.create_text(
            12,
            12,
            anchor="nw",
            text=self.message,
            fill="#ffffff",
            font=("Arial", 11, "bold"),
            tags=TEST_TRAFFIC_TOOL_TAG,
        )
        self.host.canvas.tag_raise(TEST_TRAFFIC_TOOL_TAG)
        self._dirty = False

    def reset(self) -> None:
        for car in self.host.test_traffic.clear():
            if hasattr(self.host, "canvas") and car.item is not None:
                self.host.canvas.delete(car.item)
            if hasattr(self.host, "canvas"):
                for item in car.signal_items:
                    self.host.canvas.delete(item)
        if hasattr(self.host, "canvas"):
            self.host.canvas.delete(TEST_TRAFFIC_TOOL_TAG)
            self.host.draw_test_traffic_sources()
        self.message = "Select at least two intersections as traffic sources/sinks."
        self._dirty = True

    def _escape_event(self, _event: Any) -> str:
        self.reset()
        self.refresh()
        return "break"


TOOL_CLASS = TestTrafficTool
