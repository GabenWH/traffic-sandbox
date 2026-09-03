"""File dialogs, world persistence, and analytics exports."""

from __future__ import annotations

import csv
import json
from tkinter import filedialog, messagebox

from city import CityMap
from config import DEFAULT_SPEED_LIMIT_MPH
from persistence import WorldFormatError, world_from_dict, world_to_dict
from simulation import TrafficSimulation
from units import mph_to_display, speed_unit


class FileActionsMixin:
    """Own user-facing file operations without rendering implementation."""

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow((
                "simulation_seconds",
                f"average_{speed_unit(self.unit_system)}",
                "exits_per_minute",
            ))
            writer.writerows(
                (timestamp, mph_to_display(speed, self.unit_system), flow)
                for timestamp, speed, flow in self.simulation.history
            )

    def export_svg(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".svg", filetypes=[("SVG", "*.svg")],
        )
        if not path:
            return
        history = self.simulation.history
        if not history:
            return
        start = history[0][0]
        end = max(history[-1][0], start + 1)
        display_speeds = [mph_to_display(row[1], self.unit_system) for row in history]
        max_speed = max(
            mph_to_display(DEFAULT_SPEED_LIMIT_MPH, self.unit_system), *display_speeds,
        )
        points = " ".join(
            f"{55 + (timestamp - start) / (end - start) * 720:.1f},"
            f"{340 - speed / max_speed * 250:.1f}"
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
        path = filedialog.asksaveasfilename(
            initialdir="saves",
            defaultextension=".json", filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        state = world_to_dict(
            self.city_map,
            unit_system=self.unit_system,
            camera_x=self.camera_x,
            camera_y=self.camera_y,
            camera_zoom=self.camera_zoom,
        )
        try:
            with open(path, "w", encoding="utf-8") as output:
                json.dump(state, output, indent=2)
                output.write("\n")
        except OSError as error:
            messagebox.showerror(
                "Save world", f"Could not save the world:\n{error}", parent=self.root,
            )

    def new_world(self) -> None:
        if not messagebox.askyesno(
            "New world", "Create a new blank world? Unsaved changes will be lost.",
        ):
            return
        self.clear_cars()
        self.simulation = TrafficSimulation()
        self.city_map = CityMap()
        self.blank_map = True
        self.select_lane(self.simulation.lanes[0])
        for toolbar_tool in self.tools:
            for tool in toolbar_tool.iter_canvas_tools():
                tool.reset()
        self.reset_camera()

    def load_state(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as source:
                loaded = world_from_dict(json.load(source))
        except (OSError, json.JSONDecodeError, WorldFormatError, ValueError) as error:
            messagebox.showerror(
                "Load world", f"Could not load the world:\n{error}", parent=self.root,
            )
            return
        for toolbar_tool in self.tools:
            for tool in toolbar_tool.iter_canvas_tools():
                tool.reset()
        self.clear_cars()
        self.simulation = TrafficSimulation()
        self.city_map = loaded.city_map
        self.blank_map = True
        self.unit_system = loaded.unit_system
        self.camera_x = loaded.camera_x
        self.camera_y = loaded.camera_y
        self.camera_zoom = max(0.35, min(3.0, loaded.camera_zoom))
        self.select_lane(self.simulation.lanes[0])
        self.redraw_world()

    def exit_app(self) -> None:
        if messagebox.askyesno("Exit simulator", "Exit the freeway simulator?"):
            self.root.destroy()
