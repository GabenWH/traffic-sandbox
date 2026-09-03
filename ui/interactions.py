"""Traffic controls and context-menu interactions."""

from __future__ import annotations

from math import dist
import tkinter as tk
from tkinter import simpledialog

from config import DEFAULT_SPEED_LIMIT_MPH, LANE_HEIGHT
from city import Building
from models import Intersection, Lane, Point, Road, SpeedLimit
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


class InteractionMixin:
    """Own non-camera user actions that mutate traffic presentation state."""

    def add_car(self, start_random: bool = False) -> None:
        """Ask the legacy simulation for a car and create its visual."""
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
        for car in self.test_traffic.clear_cars():
            if car.item is not None:
                self.canvas.delete(car.item)
            for item in car.signal_items:
                self.canvas.delete(item)
        self.simulation.record_event("cleared traffic")

    def toggle_running(self) -> None:
        """Pause or resume simulation updates."""
        self.running = not self.running

    def set_simulation_speed(self, value: str) -> None:
        """Apply an Inspector speed-slider value."""
        speed = float(value)
        if self.simulation_speed == speed:
            return
        self.simulation_speed = speed
        self.simulation.record_event(f"simulation speed {self.simulation_speed:g}x")

    def set_traffic(self, value: str) -> None:
        """Apply an Inspector target-fleet value."""
        target = int(float(value))
        if self.simulation.max_cars == target:
            return
        self.simulation.max_cars = target
        self.simulation.record_event(f"traffic target {self.simulation.max_cars}")

    def select_lane(self, lane: Lane) -> None:
        self.selected_lane = lane

    def set_selected_lane_gap(self, value: str) -> None:
        gap = float(value)
        if self.selected_lane.following_gap != gap:
            self.selected_lane.following_gap = gap
            self.simulation.record_event(f"{self.selected_lane.name} gap {gap:.0f}px")

    def set_unit_system(self, unit_system: str) -> None:
        """Switch display units without changing canonical model values."""
        unit_system = validate_unit_system(unit_system)
        if self.unit_system == unit_system:
            return
        self.unit_system = unit_system
        self.draw_speed_limits()
        if self.active_tool is not None:
            self.active_tool.refresh()
        self.draw_analytics()

    def lane_at(self, position: Point) -> Lane | None:
        """Return a nearby legacy-simulation lane."""
        if self.blank_map:
            return None
        lane = min(self.simulation.lanes, key=lambda candidate: candidate.distance_to(position))
        return lane if lane.distance_to(position) <= LANE_HEIGHT / 2 else None

    def road_at(self, position: Point) -> Road | None:
        """Return the topmost constructed road beneath a world position."""
        screen_tolerance = 4.0 / self.camera_zoom
        for road in reversed(self.city_map.roads):
            if road.distance_to(position) <= road.width / 2 + screen_tolerance:
                return road
        return None

    def intersection_at(self, position: Point) -> Intersection | None:
        """Return the topmost explicit junction beneath a world position."""
        for intersection in reversed(self.city_map.intersections):
            if dist(position, intersection.position) <= intersection.radius + 4 / self.camera_zoom:
                return intersection
        return None

    def cul_de_sac_at(self, position: Point) -> Intersection | None:
        """Return the topmost derived road-end turnaround beneath a position."""
        for cul_de_sac in reversed(self.city_map.cul_de_sacs):
            if dist(position, cul_de_sac.position) <= cul_de_sac.radius + 4 / self.camera_zoom:
                return cul_de_sac
        return None

    def building_at(self, position: Point) -> Building | None:
        """Return the topmost building footprint beneath a world position."""
        return next(
            (building for building in reversed(self.city_map.buildings) if building.contains(position)),
            None,
        )

    def routed_test_car_at(self, position: Point) -> object | None:
        """Return the topmost constructed-road test car near a world point."""
        for car in reversed(self.test_traffic.cars):
            radius = max(car.length, car.width) / 2 + 3 / self.camera_zoom
            if dist(position, car.position) <= radius:
                return car
        return None

    def show_lane_menu(self, event: tk.Event[tk.Misc]) -> None:
        """Open the appropriate context menu for a sign or lane."""
        world_position = self.screen_to_world((event.x, event.y))
        speed_limit = self.speed_limit_at(*world_position)
        if speed_limit is not None:
            self.show_speedlimit_menu(event, speed_limit)
            return
        lane = self.lane_at(world_position)
        if lane is None:
            return
        self.select_lane(lane)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label=f"Set {lane.name} lane gap…",
            command=lambda: self.prompt_for_gap(lane),
        )
        menu.add_command(
            label=f"Add {lane.name} speed-limit sign",
            command=lambda: self.add_speedlimit(world_position[0], world_position[1], lane),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def speed_limit_at(self, x: float, y: float) -> SpeedLimit | None:
        for speed_limit in reversed(self.simulation.speed_limits):
            if abs(speed_limit.x - x) <= 25 and abs(speed_limit.y - y) <= 42:
                return speed_limit
        return None

    def show_speedlimit_menu(
        self, event: tk.Event[tk.Misc], speed_limit: SpeedLimit,
    ) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label=(
                f"Change {mph_to_display(speed_limit.speed, self.unit_system):.0f} "
                f"{speed_unit(self.unit_system)} limit"
            ),
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
        unit = distance_unit(self.unit_system)
        gap = simpledialog.askfloat(
            "Following gap", f"Preferred following gap for the {lane.name} lane ({unit}):",
            parent=self.root,
            initialvalue=pixels_to_display_distance(lane.following_gap, self.unit_system),
            minvalue=pixels_to_display_distance(30.0, self.unit_system),
            maxvalue=pixels_to_display_distance(180.0, self.unit_system),
        )
        if gap is None:
            return
        gap_pixels = display_distance_to_pixels(gap, self.unit_system)
        if lane.following_gap != gap_pixels:
            lane.following_gap = gap_pixels
            self.simulation.record_event(f"{lane.name} gap {gap:.0f} {unit}")
        self.select_lane(lane)

    def add_speedlimit(self, x: float, y: float, lane: Lane) -> None:
        minimum, maximum = speed_limit_bounds(self.unit_system)
        unit = speed_unit(self.unit_system)
        speed = simpledialog.askfloat(
            "Speed", f"Speed limit for sign ({unit})", parent=self.root,
            initialvalue=mph_to_display(DEFAULT_SPEED_LIMIT_MPH, self.unit_system),
            minvalue=minimum, maxvalue=maximum,
        )
        if speed is None:
            return
        self.simulation.add_speed_limit(
            display_to_mph(speed, self.unit_system), lane, x, y,
        )
        self.draw_speed_limits()

    def change_speed_limit(self, speed_limit: SpeedLimit) -> None:
        minimum, maximum = speed_limit_bounds(self.unit_system)
        unit = speed_unit(self.unit_system)
        speed = simpledialog.askfloat(
            "Speed limit", f"Speed limit ({unit}):", parent=self.root,
            initialvalue=mph_to_display(speed_limit.speed, self.unit_system),
            minvalue=minimum, maxvalue=maximum,
        )
        if speed is None:
            return
        speed_limit.speed = display_to_mph(speed, self.unit_system)
        self.simulation.record_event(
            f"{speed_limit.lane.name} limit changed to {speed:.0f} {unit}"
        )
        self.draw_speed_limits()

    def delete_speed_limit(self, speed_limit: SpeedLimit) -> None:
        self.simulation.remove_speed_limit(speed_limit)
        self.draw_speed_limits()
