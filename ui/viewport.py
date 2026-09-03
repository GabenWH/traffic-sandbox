"""Camera state, projection helpers, and pan/zoom interaction."""

from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk

from config import HEIGHT, WIDTH
from models import Point


MIN_ZOOM = 0.35
MAX_ZOOM = 3.0
ZOOM_STEP = 1.15


@dataclass
class Viewport:
    x: float
    y: float
    zoom: float = 1.0

    def world_to_screen(self, point: Point) -> Point:
        return ((point[0] - self.x) * self.zoom, (point[1] - self.y) * self.zoom)

    def screen_to_world(self, point: Point) -> Point:
        return (point[0] / self.zoom + self.x, point[1] / self.zoom + self.y)


class ViewportMixin:
    """Expose viewport operations through the application host API."""

    viewport: Viewport
    _pan_anchor: tuple[int, int] | None

    @property
    def camera_x(self) -> float:
        return self.viewport.x

    @camera_x.setter
    def camera_x(self, value: float) -> None:
        self.viewport.x = value

    @property
    def camera_y(self) -> float:
        return self.viewport.y

    @camera_y.setter
    def camera_y(self, value: float) -> None:
        self.viewport.y = value

    @property
    def camera_zoom(self) -> float:
        return self.viewport.zoom

    @camera_zoom.setter
    def camera_zoom(self, value: float) -> None:
        self.viewport.zoom = value

    def world_to_screen(self, point: Point) -> Point:
        """Project one world-space coordinate into the current canvas view."""
        return self.viewport.world_to_screen(point)

    def screen_to_world(self, point: Point) -> Point:
        """Convert a screen coordinate back into world space."""
        return self.viewport.screen_to_world(point)

    def world_points(self, *points: Point) -> list[float]:
        """Project points and flatten them for Tkinter canvas APIs."""
        return [coordinate for point in points for coordinate in self.world_to_screen(point)]

    def world_box(
        self, left: float, top: float, right: float, bottom: float,
    ) -> tuple[float, float, float, float]:
        """Project opposite corners of a world-aligned rectangle."""
        return (*self.world_to_screen((left, top)), *self.world_to_screen((right, bottom)))

    def visible_world_bounds(self) -> tuple[float, float, float, float]:
        """Return the world-space rectangle currently visible on the canvas."""
        width = max(self.canvas.winfo_width(), WIDTH)
        height = max(self.canvas.winfo_height(), HEIGHT)
        return (*self.screen_to_world((0, 0)), *self.screen_to_world((width, height)))

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
        """Finish a middle-button pan and restore the active tool cursor."""
        self._pan_anchor = None
        cursor = getattr(self.active_tool, "cursor", "")
        self.canvas.configure(cursor=cursor)

    def zoom_camera(self, event: tk.Event[tk.Misc], direction: int | None = None) -> None:
        """Zoom around the pointer while keeping its world coordinate fixed."""
        direction = direction if direction is not None else (1 if event.delta > 0 else -1)
        old_world = self.screen_to_world((event.x, event.y))
        factor = ZOOM_STEP if direction > 0 else 1 / ZOOM_STEP
        self.camera_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.camera_zoom * factor))
        self.camera_x = old_world[0] - event.x / self.camera_zoom
        self.camera_y = old_world[1] - event.y / self.camera_zoom
        self.redraw_world()

    def reset_camera(self) -> None:
        """Restore the city-builder center or legacy simulation origin."""
        if self.blank_map:
            self.camera_x = (self.city_map.width - WIDTH) / 2
            self.camera_y = (self.city_map.height - HEIGHT) / 2
        else:
            self.camera_x = self.camera_y = 0.0
        self.camera_zoom = 1.0
        self.redraw_world()
