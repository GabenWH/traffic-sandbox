"""Inspect tool: a compact example of the canvas-tool lifecycle."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from config import MAX_SPEED_PREFERENCE_MPH, MIN_SPEED_PREFERENCE_MPH
from models import Car, Lane, SpeedLimit
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


def inspection_rows(host: Any, selected: object | None) -> tuple[str, list[InspectionRow]]:
    """Return a title and field descriptions for one selected model object.

    An ``editor`` of ``slider`` or ``text`` makes the row editable; ``None``
    renders a read-only value. Keeping this metadata separate from Tkinter
    makes field behavior easy to test and extend.
    """
    simulation = host.simulation
    unit_system = host.unit_system
    speed_label = speed_unit(unit_system)
    distance_label = distance_unit(unit_system)
    gap_minimum = pixels_to_display_distance(30.0, unit_system)
    gap_maximum = pixels_to_display_distance(180.0, unit_system)
    gap_resolution = 5.0 if unit_system == "imperial" else 1.0

    if isinstance(selected, Car):
        return "Car", [
            InspectionRow("Lane", selected.lane.name),
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
            InspectionRow("Lane", selected.lane.name),
            InspectionRow("Position", f"{pixels_to_display_distance(selected.x, unit_system):.1f}, {pixels_to_display_distance(selected.y, unit_system):.1f} {distance_label}"),
        ]

    if isinstance(selected, Lane):
        cars = sum(car.lane is selected for car in simulation.cars)
        signs = [sign.speed for sign in simulation.speed_limits if sign.lane is selected]
        limits = ", ".join(f"{mph_to_display(speed, unit_system):.0f}" for speed in signs) or "default"
        return "Lane", [
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
        InspectionRow("Selected lane", selected_lane.name),
        InspectionRow(
            f"Following gap ({distance_label})", pixels_to_display_distance(selected_lane.following_gap, unit_system), "slider",
            lambda value: set_lane_gap(host, selected_lane, value),
            gap_minimum, gap_maximum, gap_resolution,
        ),
    ]


class InspectTool(CanvasTool):
    """Show live stats and inspect a sign, car, or lane with a left click."""

    name = "Inspect"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.selected: Car | Lane | SpeedLimit | None = None
        self.panel: tk.Frame | None = None
        self.title_label: tk.Label | None = None
        self.fields_frame: tk.Frame | None = None
        self.message_label: tk.Label | None = None
        self._rendered_key: tuple[int | None, int | None] | None = None
        self._row_widgets: list[tuple[EditorKind | Literal["label"], tk.Widget]] = []
        self._syncing = False

    def activate(self) -> None:
        """Create the Inspector overlay or raise its existing panel."""
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
            command=lambda: self.host.deactivate_tool(self),
        ).pack(side="right")
        self.fields_frame = tk.Frame(
            self.panel, bg="#ffffff", relief="sunken", borderwidth=1,
        )
        self.fields_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.message_label = tk.Label(
            self.panel,
            text="Left-click an object; empty space shows global stats.",
            anchor="w", bg="#e8edf2", font=("Arial", 9), wraplength=350,
        )
        self.message_label.pack(fill="x", padx=12, pady=(0, 10))
        self._rendered_key = None
        self.refresh()

    def deactivate(self) -> None:
        """Remove the Inspector overlay and clear its widget references."""
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.destroy()
        self.panel = None
        self.title_label = None
        self.fields_frame = None
        self.message_label = None
        self._rendered_key = None
        self._row_widgets.clear()

    def on_canvas_click(self, event: Any) -> None:
        """Select the topmost inspectable object under a canvas click."""
        world_x, world_y = self.host.screen_to_world((event.x, event.y))

        # Signs visually sit above cars and lanes, so inspect them first.
        sign = self.host.speed_limit_at(world_x, world_y)
        if sign is not None:
            self.selected = sign
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

            if field.editor == "slider":
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
            if kind == "label":
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
        elif isinstance(self.selected, SpeedLimit) and self.selected not in self.host.simulation.speed_limits:
            self.selected = None
        elif isinstance(self.selected, Lane) and self.selected not in self.host.simulation.lanes:
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
