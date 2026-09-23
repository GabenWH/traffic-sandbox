"""Panda3D child window hosted by an ordinary Tk frame."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from math import cos, hypot, radians, sin

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    LineSegs, NativeWindowHandle, Point2, Point3, Vec3, WindowProperties,
    loadPrcFileData,
)

from city import CityMap
from models import Road
from models import Intersection
from .camera3d import OrbitCamera, map_to_panda, panda_to_map, ray_to_height
from .scene3d import (
    SceneRegistry, TerrainFeature, TreeFeature, attach_map_root, draw_intersection,
    draw_road, draw_terrain, draw_tree, update_car_layer,
)


class PandaWorldView:
    """Own the native 3D viewport while Tk keeps the application loop."""

    def __init__(self, parent: tk.Misc) -> None:
        self.frame = tk.Frame(parent, bg="#202a33")
        loadPrcFileData("", "audio-library-name null")
        self.base = ShowBase(windowType="none")
        self.base.disableMouse()
        self.base.setBackgroundColor(0.55, 0.7, 0.85)
        self.orbit = OrbitCamera((2500, 1750, 0))
        self.city: CityMap | None = None
        self.scene = SceneRegistry(attach_map_root(self.base.render, "city"))
        self.preview_root = attach_map_root(self.base.render, "preview-layer")
        self.vehicle_root = attach_map_root(self.base.render, "vehicles")
        self.vehicle_nodes = {}
        self.scene.register(TerrainFeature, draw_terrain)
        self.scene.register(Road, draw_road)
        self.scene.register(Intersection, draw_intersection)
        self.scene.register(TreeFeature, draw_tree)
        self.on_click: Callable[[int, int], None] | None = None
        self.on_motion: Callable[[int, int], None] | None = None
        self.on_key: Callable[[str], None] | None = None
        self._last_pointer: tuple[int, int] | None = None
        self._drag_mode: str | None = None
        self.base.accept("mouse1", self._click)
        self.base.accept("mouse3", lambda: self._start_drag("orbit"))
        self.base.accept("mouse3-up", self._end_drag)
        self.base.accept("mouse2", lambda: self._start_drag("pan"))
        self.base.accept("mouse2-up", self._end_drag)
        self.base.accept("wheel_up", lambda: self._wheel(0.82))
        self.base.accept("wheel_down", lambda: self._wheel(1.22))
        for key in ("page_up", "page_down", "enter", "escape"):
            self.base.accept(key, self._emit_key, [key])
        self.frame.bind("<Configure>", self._resize)

    def set_callbacks(
        self,
        *,
        on_click: Callable[[int, int], None] | None = None,
        on_motion: Callable[[int, int], None] | None = None,
        on_key: Callable[[str], None] | None = None,
    ) -> None:
        self.on_click = on_click
        self.on_motion = on_motion
        self.on_key = on_key

    def _open(self) -> None:
        properties = WindowProperties()
        properties.setParentWindow(NativeWindowHandle.makeInt(self.frame.winfo_id()))
        # Panda's desktop default origin also applies to child windows.
        properties.setOrigin(0, 0)
        properties.setSize(max(2, self.frame.winfo_width()), max(2, self.frame.winfo_height()))
        self.base.openWindow(props=properties, requireWindow=True)
        self.base.setupMouse(self.base.win)
        self.base.camLens.setNearFar(1, 20000)
        self._apply_camera()

    def _resize(self, _event: object) -> None:
        if self.base.win is None:
            return
        properties = WindowProperties()
        properties.setOrigin(0, 0)
        properties.setSize(max(2, self.frame.winfo_width()), max(2, self.frame.winfo_height()))
        self.base.win.requestProperties(properties)

    def step(self) -> None:
        if self.base.win is None:
            self._open()
        self.base.taskMgr.step()
        self._process_pointer()

    def _pointer(self) -> tuple[int, int] | None:
        watcher = self.base.mouseWatcherNode
        if watcher is None or not watcher.hasMouse():
            return None
        mouse = watcher.getMouse()
        return (
            round((mouse.x + 1) * self.frame.winfo_width() / 2),
            round((1 - mouse.y) * self.frame.winfo_height() / 2),
        )

    def _click(self) -> None:
        point = self._pointer()
        if point is not None and self.on_click is not None:
            self.on_click(*point)

    def _emit_key(self, key: str) -> None:
        if self.on_key is not None:
            self.on_key(key)

    def _start_drag(self, mode: str) -> None:
        self._drag_mode = mode
        self._last_pointer = self._pointer()

    def _end_drag(self) -> None:
        self._drag_mode = None

    def _wheel(self, factor: float) -> None:
        self.orbit.zoom(factor)
        self._apply_camera()

    def _process_pointer(self) -> None:
        point = self._pointer()
        if point is None:
            self._last_pointer = None
            return
        if self._last_pointer is not None and point != self._last_pointer:
            dx = point[0] - self._last_pointer[0]
            dy = point[1] - self._last_pointer[1]
            if self._drag_mode == "orbit":
                # Pointer Y grows down, while positive pitch raises the camera.
                self.orbit.rotate(-dx * 0.35, -dy * 0.35)
                self._apply_camera()
            elif self._drag_mode == "pan":
                scale = self.orbit.distance / max(1, self.frame.winfo_height())
                orientation = self.base.camera.getQuat(self.base.render)
                right = orientation.xform(Vec3(1, 0, 0))
                up = orientation.xform(Vec3(0, 0, 1))
                right_length = hypot(right.x, right.y) or 1
                up_length = hypot(up.x, up.y) or 1
                target_x, target_y, target_z = self.orbit.target
                self.orbit.target = (
                    target_x + (
                        -right.x / right_length * dx + up.x / up_length * dy
                    ) * scale,
                    target_y - (
                        -right.y / right_length * dx + up.y / up_length * dy
                    ) * scale,
                    target_z,
                )
                self._apply_camera()
            if self.on_motion is not None:
                self.on_motion(*point)
        self._last_pointer = point

    def show_city(self, city: CityMap) -> None:
        """Refresh terrain, roads, and trees without resetting the camera."""
        if self.city is not city:
            self.orbit.target = (city.width / 2, city.height / 2, 0)
        self.city = city
        self.scene.replace([
            TerrainFeature(city.width, city.height, city.terrain.grass_color),
            *city.roads,
            *city.intersections,
            *(
                TreeFeature(
                    "redwood" if index % 4 == 0 else "pine",
                    height=55 if index % 4 == 0 else 30,
                    x=x, y=y,
                )
                for index, (x, y) in enumerate(city.terrain.trees)
            ),
        ])
        self._apply_camera()

    def update_cars(self, cars, elapsed_seconds: float) -> None:
        """Refresh the 3D vehicle layer while preserving static geometry."""
        update_car_layer(cars, self.vehicle_root, self.vehicle_nodes, elapsed_seconds)

    def _apply_camera(self) -> None:
        if self.base.camera is None or self.base.camera.isEmpty():
            return
        self.base.camera.setPos(*map_to_panda(self.orbit.position))
        target = Point3(*map_to_panda(self.orbit.target))
        # Keep Z vertical while orbiting; derive the zenith up direction from
        # yaw because world-up becomes parallel to the view at exactly 90°.
        camera_up = Vec3(0, 0, 1)
        if self.orbit.pitch >= 90:
            yaw = radians(self.orbit.yaw)
            camera_up = Vec3(-cos(yaw), sin(yaw), 0)
        self.base.camera.lookAt(target, camera_up)

    def point_at_screen(
        self, screen_x: float, screen_y: float, elevation: float,
    ) -> tuple[float, float] | None:
        """Intersect a screen coordinate with a road construction plane."""
        if self.base.win is None:
            return None
        x = screen_x / max(1, self.frame.winfo_width()) * 2 - 1
        y = 1 - screen_y / max(1, self.frame.winfo_height()) * 2
        near, far = Point3(), Point3()
        if not self.base.camLens.extrude(Point2(x, y), near, far):
            return None
        transform = self.base.camera.getMat(self.base.render)
        start = transform.xformPoint(near)
        end = transform.xformPoint(far)
        point = ray_to_height(
            (start.x, start.y, start.z),
            (end.x - start.x, end.y - start.y, end.z - start.z),
            elevation,
        )
        if point is None:
            return None
        return panda_to_map((point[0], point[1], elevation))[:2]

    def screen_position(
        self, point: tuple[float, float], elevation: float,
    ) -> tuple[float, float] | None:
        """Project a world point so elevated road ends can be picked precisely."""
        if self.base.win is None:
            return None
        camera_point = self.base.camera.getRelativePoint(
            self.base.render, Point3(*map_to_panda((*point, elevation))),
        )
        projected = Point2()
        if not self.base.camLens.project(camera_point, projected):
            return None
        return (
            (projected.x + 1) * self.frame.winfo_width() / 2,
            (1 - projected.y) * self.frame.winfo_height() / 2,
        )

    def nearest_road_endpoint(
        self, screen_x: float, screen_y: float, tolerance: float = 14,
    ) -> tuple[tuple[float, float], float] | None:
        """Return the visible road end nearest a click within a pixel radius."""
        if self.city is None:
            return None
        closest = None
        closest_distance = tolerance
        for road in self.city.roads:
            for point, elevation in (
                (road.centerline[0], road.elevations[0]),
                (road.centerline[-1], road.elevations[-1]),
            ):
                screen = self.screen_position(point, elevation)
                if screen is None:
                    continue
                distance = hypot(screen[0] - screen_x, screen[1] - screen_y)
                if distance <= closest_distance:
                    closest = (point, elevation)
                    closest_distance = distance
        return closest

    def show_road_preview(
        self,
        points: list[tuple[float, float]],
        elevations: list[float],
        pointer: tuple[float, float] | None,
        pointer_elevation: float,
    ) -> None:
        """Draw the draft road and its next sloped segment above the world."""
        self.clear_preview()
        path = [(*point, height + 1) for point, height in zip(points, elevations)]
        if pointer is not None:
            path.append((*pointer, pointer_elevation + 1))
        if len(path) < 2:
            return
        segments = LineSegs("road-preview-line")
        segments.setColor(0.2, 0.9, 1.0, 1)
        segments.setThickness(4)
        segments.moveTo(*path[0])
        for point in path[1:]:
            segments.drawTo(*point)
        root = self.preview_root.attachNewNode("road-preview")
        root.attachNewNode(segments.create())

    def clear_preview(self) -> None:
        for child in self.preview_root.getChildren():
            child.removeNode()

    def close(self) -> None:
        if self.base.win is not None:
            self.base.closeWindow(self.base.win)
        self.base.destroy()
