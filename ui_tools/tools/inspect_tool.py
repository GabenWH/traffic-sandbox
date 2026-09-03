"""Inspect tool: a compact example of the canvas-tool lifecycle."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from city import Building
from config import MAX_SPEED_PREFERENCE_MPH, MIN_SPEED_PREFERENCE_MPH
from models import Car, CityObject, Intersection, Lane, Road, SpeedLimit
from traffic_testbed import RoutedTestCar
from units import (
    acceleration_unit,
    display_distance_to_pixels,
    display_to_mph,
    distance_unit,
    mph_to_display,
    pixels_per_second_to_mph,
    pixels_per_second_squared_to_display_acceleration,
    pixels_to_display_distance,
    speed_limit_bounds,
    speed_unit,
)

from ..base import CanvasTool


TOOL_ID = "inspect"


EditorKind = Literal["slider", "text"]


@dataclass
class InspectionRow:
    """Describe one Inspector field and its optional editing control."""

    label: str
    value: str | float
    editor: EditorKind | None = None
    apply: Callable[[str], None] | None = None
    minimum: float = 0.0
    maximum: float = 100.0
    resolution: float = 1.0
    target: object | None = None


def set_lane_gap(host: Any, lane: Lane, value: str) -> None:
    """Apply a lane gap from an Inspector slider."""
    gap = display_distance_to_pixels(float(value), host.unit_system)
    if lane.following_gap == gap:
        return
    lane.following_gap = gap
    host.simulation.record_event(f"{lane.name} gap {pixels_to_display_distance(gap, host.unit_system):.0f} {distance_unit(host.unit_system)}")


def set_speed_limit(host: Any, sign: SpeedLimit, value: str) -> None:
    """Validate and apply a sign's text-entered speed limit."""
    try:
        speed = display_to_mph(float(value), host.unit_system)
    except ValueError as error:
        raise ValueError("Enter a numeric speed limit.") from error
    minimum, maximum = speed_limit_bounds(host.unit_system)
    if not display_to_mph(minimum, host.unit_system) <= speed <= display_to_mph(maximum, host.unit_system):
        raise ValueError(f"Speed limit must be between {minimum:g} and {maximum:g} {speed_unit(host.unit_system)}.")
    if sign.speed == speed:
        return
    sign.speed = speed
    host.simulation.record_event(
        f"{sign.lane.name} limit changed to {mph_to_display(speed, host.unit_system):.0f} {speed_unit(host.unit_system)}"
    )
    host.draw_speed_limits()


def set_car_preference(host: Any, car: Car, value: str) -> None:
    """Apply a car's preferred offset from its posted speed limit."""
    preference = display_to_mph(float(value), host.unit_system)
    if car.speed_preference_mph == preference:
        return
    car.speed_preference_mph = preference
    host.simulation.record_event(
        f"car preference {mph_to_display(preference, host.unit_system):+.0f} {speed_unit(host.unit_system)}"
    )


def set_simulation_speed(host: Any, value: str) -> None:
    """Apply simulation speed from the Inspector's slider."""
    host.set_simulation_speed(value)


def set_traffic_target(host: Any, value: str) -> None:
    """Apply target car count from the Inspector's slider."""
    host.set_traffic(value)


def set_intersection_all_way_stop(
    host: Any, intersection: Intersection, value: str,
) -> None:
    """Apply an Inspector-entered all-way-stop setting."""
    normalized = value.strip().lower()
    if normalized in {"yes", "true", "stop", "1"}:
        enabled = True
    elif normalized in {"no", "false", "uncontrolled", "0"}:
        enabled = False
    else:
        raise ValueError("Enter yes/no, stop/uncontrolled, true/false, or 1/0.")
    intersection.set_all_way_stop(enabled)
    draw_scene = getattr(host, "draw_scene", None)
    if callable(draw_scene):
        draw_scene()


def inspection_rows(host: Any, selected: object | None) -> tuple[str, list[InspectionRow]]:
    """Return a title and field descriptions for one selected model object.

    An ``editor`` of ``slider`` or ``text`` makes the row editable; ``None``
    renders a read-only value. Keeping this metadata separate from Tkinter
    makes field behavior easy to test and extend.
    """
    unit_system = host.unit_system
    if isinstance(selected, RoutedTestCar):
        speed_label = speed_unit(unit_system)
        claim = selected.claimed_movement
        return "Routed test car", [
            InspectionRow("ID", selected.id),
            InspectionRow("Brain state", selected.brain.state.value),
            InspectionRow("Turn signal", selected.brain.signal_intent.value),
            InspectionRow("Wait reason", selected.brain.wait_reason or "—"),
            InspectionRow(
                "Speed",
                f"{mph_to_display(pixels_per_second_to_mph(selected.speed), unit_system):.1f} {speed_label}",
            ),
            InspectionRow(
                "Desired speed",
                f"{mph_to_display(pixels_per_second_to_mph(selected.brain.desired_speed), unit_system):.1f} {speed_label}",
            ),
            InspectionRow("Route progress", f"{selected.distance:.1f} / {selected.total_length:.1f}"),
            InspectionRow("Claimed movement", claim.id if claim is not None else "—"),
        ]

    if isinstance(selected, Intersection):
        rows = []
        for item in selected.inspection_properties():
            value = item.value
            if item.unit == "distance":
                value = (
                    f"{pixels_to_display_distance(float(value), unit_system):g} "
                    f"{distance_unit(unit_system)}"
                )
            rows.append(InspectionRow(item.label, str(value), target=item.target))
        if selected.kind.value == "standard":
            rows.insert(
                2,
                InspectionRow(
                    "All-way stop",
                    "yes" if selected.is_all_way_stop else "no",
                    "text",
                    lambda value: set_intersection_all_way_stop(host, selected, value),
                ),
            )
        return selected.inspection_title, rows

    if isinstance(selected, CityObject):
        rows: list[InspectionRow] = []
        for item in selected.inspection_properties():
            value = item.value
            if item.unit == "distance":
                value = (
                    f"{pixels_to_display_distance(float(value), unit_system):g} "
                    f"{distance_unit(unit_system)}"
                )
            rows.append(InspectionRow(item.label, str(value), target=item.target))
        return selected.inspection_title, rows

    simulation = host.simulation
    speed_label = speed_unit(unit_system)
    distance_label = distance_unit(unit_system)
    gap_minimum = pixels_to_display_distance(30.0, unit_system)
    gap_maximum = pixels_to_display_distance(180.0, unit_system)
    gap_resolution = 5.0 if unit_system == "imperial" else 1.0

    if isinstance(selected, Car):
        return "Car", [
            InspectionRow("Lane", selected.lane.name, target=selected.lane),
            InspectionRow("Speed", f"{mph_to_display(pixels_per_second_to_mph(selected.speed), unit_system):.1f} {speed_label}"),
            InspectionRow("Cruise speed", f"{mph_to_display(pixels_per_second_to_mph(selected.cruise_speed), unit_system):.1f} {speed_label}"),
            InspectionRow(
                "Acceleration",
                f"{pixels_per_second_squared_to_display_acceleration(selected.acceleration, unit_system):.2f} {acceleration_unit(unit_system)}",
            ),
            InspectionRow(
                f"Preference ({speed_label})", mph_to_display(selected.speed_preference_mph, unit_system), "slider",
                lambda value: set_car_preference(host, selected, value),
                mph_to_display(MIN_SPEED_PREFERENCE_MPH, unit_system),
                mph_to_display(MAX_SPEED_PREFERENCE_MPH, unit_system),
                1.0,
            ),
            InspectionRow("Posted limit", f"{mph_to_display(simulation.speed_limit_for(selected), unit_system):.0f} {speed_label}"),
            InspectionRow("Position", f"{pixels_to_display_distance(selected.x, unit_system):.1f}, {pixels_to_display_distance(selected.y, unit_system):.1f} {distance_label}"),
            InspectionRow("Next path point", str(selected.next_point)),
        ]

    if isinstance(selected, SpeedLimit):
        return "Speed-limit sign", [
            InspectionRow(
                f"Limit ({speed_label})", f"{mph_to_display(selected.speed, unit_system):g}", "text",
                lambda value: set_speed_limit(host, selected, value),
            ),
            InspectionRow("Lane", selected.lane.name, target=selected.lane),
            InspectionRow("Position", f"{pixels_to_display_distance(selected.x, unit_system):.1f}, {pixels_to_display_distance(selected.y, unit_system):.1f} {distance_label}"),
        ]

    if isinstance(selected, Lane):
        cars = sum(car.lane is selected for car in simulation.cars)
        signs = [sign.speed for sign in simulation.speed_limits if sign.lane is selected]
        limits = ", ".join(f"{mph_to_display(speed, unit_system):.0f}" for speed in signs) or "default"
        rows = [
            InspectionRow("Name", selected.name),
            InspectionRow(
                f"Following gap ({distance_label})", pixels_to_display_distance(selected.following_gap, unit_system), "slider",
                lambda value: set_lane_gap(host, selected, value),
                gap_minimum, gap_maximum, gap_resolution,
            ),
            InspectionRow("Cars", str(cars)),
            InspectionRow(f"Posted limits ({speed_label})", limits),
            InspectionRow("Path points", str(len(selected.points))),
        ]
        parent_road = next(
            (road for road in host.city_map.roads if road.id == selected.road_id),
            None,
        )
        if parent_road is not None:
            rows.insert(1, InspectionRow("Parent road", parent_road.name, target=parent_road))
            rows.insert(2, InspectionRow("Direction", selected.direction.title()))
        return "Lane", rows

    # No selected object means "inspect the whole simulation". These mirror
    # the quick controls and metrics currently spread across the toolbar.
    selected_lane = host.selected_lane
    return "Simulation stats", [
        InspectionRow("State", "Running" if host.running else "Paused"),
        InspectionRow(
            "Simulation speed", host.simulation_speed, "slider",
            lambda value: set_simulation_speed(host, value),
            0.25, 3.0, 0.25,
        ),
        InspectionRow(
            "Traffic target", float(simulation.max_cars), "slider",
            lambda value: set_traffic_target(host, value),
            1.0, 30.0, 1.0,
        ),
        InspectionRow("Active cars", str(len(simulation.cars))),
        InspectionRow("Display units", "Imperial" if unit_system == "imperial" else "Metric"),
        InspectionRow("Average speed", f"{mph_to_display(simulation.average_speed_mph(), unit_system):.0f} {speed_label}"),
        InspectionRow("Exits / minute", f"{simulation.exits_per_minute():.0f}"),
        InspectionRow("Selected lane", selected_lane.name, target=selected_lane),
        InspectionRow(
            f"Following gap ({distance_label})", pixels_to_display_distance(selected_lane.following_gap, unit_system), "slider",
            lambda value: set_lane_gap(host, selected_lane, value),
            gap_minimum, gap_maximum, gap_resolution,
        ),
    ]


class InspectTool(CanvasTool):
    """Show live stats and inspect a sign, car, or lane with a left click."""

    name = "Inspect"
    provides_inspector = True

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.selected: Car | Lane | SpeedLimit | CityObject | None = None
        self.panel: tk.Frame | None = None
        self.title_label: tk.Label | None = None
        self.fields_frame: tk.Frame | None = None
        self.fields_canvas: tk.Canvas | None = None
        self.fields_window: int | None = None
        self.message_label: tk.Label | None = None
        self._rendered_key: tuple[int | None, int | None] | None = None
        self._row_widgets: list[
            tuple[EditorKind | Literal["label", "link"], tk.Widget]
        ] = []
        self._syncing = False

    def activate(self) -> None:
        """Create the Inspector overlay or raise its existing panel."""
        self.show_panel()

    def show_panel(self) -> None:
        """Show the shared panel without taking over the active canvas mode."""
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.lift()
            self.refresh()
            return

        # ``place`` anchors the panel to the visible canvas instead of world
        # coordinates, so panning and zooming never move the UI overlay.
        self.panel = tk.Frame(
            self.host.canvas, bg="#e8edf2", highlightthickness=1,
            highlightbackground="#7b8792",
        )
        self.panel.place(
            x=12, rely=1.0, y=-12, anchor="sw", width=430, height=365,
        )

        header = tk.Frame(self.panel, bg="#e8edf2")
        header.pack(fill="x", padx=12, pady=(10, 6))

        self.title_label = tk.Label(
            header, anchor="w", bg="#e8edf2", font=("Arial", 13, "bold")
        )
        self.title_label.pack(side="left", fill="x", expand=True)
        tk.Button(
            header, text="×", width=2, relief="flat", bg="#e8edf2",
            command=self._close_panel,
        ).pack(side="right")
        fields_shell = tk.Frame(
            self.panel, bg="#ffffff", relief="sunken", borderwidth=1,
        )
        fields_shell.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        scrollbar = tk.Scrollbar(fields_shell, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.fields_canvas = tk.Canvas(
            fields_shell, bg="#ffffff", highlightthickness=0,
            yscrollcommand=scrollbar.set,
        )
        self.fields_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.fields_canvas.yview)
        self.fields_frame = tk.Frame(self.fields_canvas, bg="#ffffff")
        self.fields_window = self.fields_canvas.create_window(
            0, 0, anchor="nw", window=self.fields_frame,
        )
        self.fields_frame.bind("<Configure>", self._update_fields_scroll_region)
        self.fields_canvas.bind("<Configure>", self._resize_fields_window)
        self.message_label = tk.Label(
            self.panel,
            text="Left-click an object; empty space shows global stats.",
            anchor="w", bg="#e8edf2", font=("Arial", 9), wraplength=350,
        )
        self.message_label.pack(fill="x", padx=12, pady=(0, 10))
        self._rendered_key = None
        self.refresh()

    def show_object(self, selected: object) -> None:
        """Display a model object selected by another canvas tool."""
        self.selected = selected
        self._rendered_key = None
        self.show_panel()

    def deactivate(self) -> None:
        """Remove the Inspector overlay and clear its widget references."""
        self.hide_panel()

    def hide_panel(self) -> None:
        """Hide the shared panel without changing another active canvas mode."""
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.destroy()
        self.panel = None
        self.title_label = None
        self.fields_frame = None
        self.fields_canvas = None
        self.fields_window = None
        self.message_label = None
        self._rendered_key = None
        self._row_widgets.clear()

    def _update_fields_scroll_region(self, _event: object) -> None:
        if self.fields_canvas is not None:
            self.fields_canvas.configure(scrollregion=self.fields_canvas.bbox("all"))

    def _resize_fields_window(self, event: Any) -> None:
        if self.fields_canvas is not None and self.fields_window is not None:
            self.fields_canvas.itemconfigure(self.fields_window, width=event.width)

    def _close_panel(self) -> None:
        if self.host.active_tool is self:
            self.host.deactivate_tool(self)
        else:
            self.hide_panel()

    def on_canvas_click(self, event: Any) -> None:
        """Select the topmost inspectable object under a canvas click."""
        world_x, world_y = self.host.screen_to_world((event.x, event.y))

        # Signs visually sit above cars and lanes, so inspect them first.
        sign = self.host.speed_limit_at(world_x, world_y)
        if sign is not None:
            self.selected = sign
            self.refresh()
            return

        routed_car = self.host.routed_test_car_at((world_x, world_y))
        if routed_car is not None:
            self.selected = routed_car
            self.refresh()
            return

        # Canvas overlap uses the actual car polygons, including small details.
        item_ids = set(self.host.canvas.find_overlapping(
            event.x - 2, event.y - 2, event.x + 2, event.y + 2
        ))
        for car in reversed(self.host.simulation.cars):
            car_items = {car.item, *car.detail_items}
            if item_ids.intersection(car_items):
                self.selected = car
                self.refresh()
                return

        building = self.host.building_at((world_x, world_y))
        if building is not None:
            self.selected = building
            self.refresh()
            return

        intersection = self.host.intersection_at((world_x, world_y))
        if intersection is not None:
            self.selected = intersection
            self.refresh()
            return

        cul_de_sac = self.host.cul_de_sac_at((world_x, world_y))
        if cul_de_sac is not None:
            self.selected = cul_de_sac
            self.refresh()
            return

        road = self.host.road_at((world_x, world_y))
        if road is not None:
            self.selected = road
            self.refresh()
            return

        self.selected = self.host.lane_at((world_x, world_y))
        if isinstance(self.selected, Lane):
            self.host.select_lane(self.selected)
        self.refresh()

    def _selection_key(self) -> tuple[int | None, int | None]:
        """Identify the layout; global fields also depend on selected lane."""
        return (
            id(self.selected) if self.selected is not None else None,
            id(self.host.selected_lane) if self.selected is None else None,
        )

    def _build_fields(self, rows: list[InspectionRow]) -> None:
        """Build a label, slider, or text editor for each field description."""
        assert self.fields_frame is not None
        for child in self.fields_frame.winfo_children():
            child.destroy()
        self._row_widgets.clear()

        for field in rows:
            row = tk.Frame(self.fields_frame, bg="#ffffff")
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(
                row, text=field.label, width=18, anchor="w",
                bg="#ffffff", font=("Arial", 9),
            ).pack(side="left")

            if field.target is not None:
                link = tk.Button(
                    row, text=str(field.value), anchor="w", relief="flat",
                    fg="#125da8", bg="#ffffff", activeforeground="#0b3f75",
                    cursor="hand2",
                    command=lambda target=field.target: self.show_object(target),
                )
                link.pack(side="left", fill="x", expand=True)
                self._row_widgets.append(("link", link))
            elif field.editor == "slider":
                slider = tk.Scale(
                    row, from_=field.minimum, to=field.maximum,
                    resolution=field.resolution, orient="horizontal",
                    showvalue=True, length=205, bg="#ffffff",
                    highlightthickness=0,
                    command=lambda value, item=field: self._apply_slider(item, value),
                )
                self._syncing = True
                slider.set(float(field.value))
                self._syncing = False
                slider.pack(side="left", fill="x", expand=True)
                self._row_widgets.append(("slider", slider))
            elif field.editor == "text":
                entry = tk.Entry(row, width=12)
                entry.insert(0, str(field.value))
                entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
                entry.bind(
                    "<Return>",
                    lambda _event, item=field, widget=entry: self._apply_text(item, widget),
                )
                tk.Button(
                    row, text="Apply",
                    command=lambda item=field, widget=entry: self._apply_text(item, widget),
                ).pack(side="right")
                self._row_widgets.append(("text", entry))
            else:
                value_label = tk.Label(
                    row, text=str(field.value), anchor="w",
                    bg="#ffffff", font=("Courier", 10),
                )
                value_label.pack(side="left", fill="x", expand=True)
                self._row_widgets.append(("label", value_label))

    def _apply_slider(self, field: InspectionRow, value: str) -> None:
        """Apply a slider change unless it came from live-value synchronization."""
        if self._syncing or field.apply is None:
            return
        field.apply(value)
        self._show_message(f"Updated {field.label}.")

    def _apply_text(self, field: InspectionRow, entry: tk.Entry) -> None:
        """Apply an Entry value and display validation errors inside the panel."""
        if field.apply is None:
            return
        try:
            field.apply(entry.get().strip())
        except ValueError as error:
            self._show_message(str(error), error=True)
            return
        self._show_message(f"Updated {field.label}.")

    def _show_message(self, message: str, error: bool = False) -> None:
        """Show concise edit feedback without opening another dialog."""
        if self.message_label is not None:
            self.message_label.config(text=message, fg="#b00020" if error else "#285c2f")

    def _update_field_values(self, rows: list[InspectionRow]) -> None:
        """Synchronize live labels/sliders while preserving active text edits."""
        for field, (kind, widget) in zip(rows, self._row_widgets):
            if kind in ("label", "link"):
                widget.config(text=str(field.value))
            elif kind == "slider":
                slider = widget
                assert isinstance(slider, tk.Scale)
                desired = float(field.value)
                if abs(float(slider.get()) - desired) > field.resolution / 10:
                    self._syncing = True
                    slider.set(desired)
                    self._syncing = False
            elif self.host.root.focus_get() is not widget:
                entry = widget
                assert isinstance(entry, tk.Entry)
                desired = str(field.value)
                if entry.get() != desired:
                    entry.delete(0, "end")
                    entry.insert(0, desired)

    def refresh(self) -> None:
        """Validate the selection and refresh the live Inspector values."""
        if self.panel is None or not self.panel.winfo_exists():
            return

        # A car/sign/lane may disappear while the panel remains open.
        if isinstance(self.selected, Car) and self.selected not in self.host.simulation.cars:
            self.selected = None
        elif (
            isinstance(self.selected, RoutedTestCar)
            and self.selected not in self.host.test_traffic.cars
        ):
            self.selected = None
        elif isinstance(self.selected, SpeedLimit) and self.selected not in self.host.simulation.speed_limits:
            self.selected = None
        elif isinstance(self.selected, Lane):
            city_lanes = (
                lane for road in self.host.city_map.roads for lane in road.lanes
            )
            if self.selected not in self.host.simulation.lanes and self.selected not in city_lanes:
                self.selected = None
        elif isinstance(self.selected, Road) and self.selected not in self.host.city_map.roads:
            self.selected = None
        elif isinstance(self.selected, Building) and self.selected not in self.host.city_map.buildings:
            self.selected = None
        elif (
            isinstance(self.selected, Intersection)
            and self.selected not in self.host.city_map.intersections
        ):
            self.selected = None

        title, rows = inspection_rows(self.host, self.selected)
        assert self.title_label is not None and self.fields_frame is not None
        self.title_label.config(text=title)
        key = self._selection_key()
        if key != self._rendered_key:
            self._build_fields(rows)
            self._rendered_key = key
        else:
            self._update_field_values(rows)

    def reset(self) -> None:
        """Return to global stats after the app replaces the active world."""
        self.selected = None
        self._rendered_key = None
        self.refresh()


TOOL_CLASS = InspectTool
