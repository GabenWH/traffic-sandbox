"""Tkinter controls and drawing for the freeway simulator."""

from __future__ import annotations

import time
import csv
import json
import traceback
import tkinter as tk
from math import atan2, cos, sin
from tkinter import filedialog, messagebox, simpledialog

from config import HEIGHT, LANE_HEIGHT, LANES, MERGE_END, MERGE_START, POST_MERGE_END, ROAD_BOTTOM, ROAD_TOP, WIDTH
from models import Car, Lane, Point, SpeedLimit
from simulation import TrafficSimulation


class FreewaySimulator:
    """Present a TrafficSimulation in an interactive canvas."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Freeway Simulator")
        root.report_callback_exception = self.report_callback_exception
        self.running = True
        self.simulation_speed = 1.0
        self.simulation = TrafficSimulation()
        self.analytics_window: tk.Toplevel | None = None
        self.analytics_canvas: tk.Canvas | None = None
        self.recent_window: tk.Toplevel | None = None
        self.recent_canvas: tk.Canvas | None = None
        self.recent_errors: list[str] = []
        self.selected_lane = self.simulation.lanes[0]
        self.last_time = time.perf_counter()
        self.last_dashboard_refresh = 0.0
        self.build_toolbar()
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, highlightthickness=0, bg="#8fc3e6")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-3>", self.show_lane_menu)
        self.select_lane(self.selected_lane)
        self.draw_scene()
        for _ in range(12):
            self.add_car(start_random=True)
        self.create_recent_changes_window()
        self.tick()

    def build_toolbar(self) -> None:
        toolbar = tk.Frame(self.root, padx=10, pady=8, bg="#e8edf2")
        toolbar.pack(fill="x")
        file_button = tk.Menubutton(toolbar, text="File", relief="raised", bg="#e8edf2")
        file_menu = tk.Menu(file_button, tearoff=False)
        file_menu.add_command(label="Save…", command=self.save_state)
        file_menu.add_command(label="Load…", command=self.load_state)
        file_menu.add_separator()
        file_menu.add_command(label="Export graph CSV…", command=self.export_csv)
        file_menu.add_command(label="Export graph SVG…", command=self.export_svg)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.exit_app)
        file_button.config(menu=file_menu)
        file_button.pack(side="left")

        simulation_button = tk.Menubutton(toolbar, text="Simulation", relief="raised", bg="#e8edf2")
        simulation_menu = tk.Menu(simulation_button, tearoff=False)
        simulation_menu.add_command(label="Pause / resume", command=self.toggle_running)
        simulation_menu.add_command(label="Add car", command=self.add_car)
        simulation_menu.add_command(label="Clear traffic", command=self.clear_cars)
        simulation_menu.add_separator()
        simulation_menu.add_command(label="Analytics graph", command=self.show_analytics)
        simulation_menu.add_command(label="Recent changes", command=self.create_recent_changes_window)
        simulation_button.config(menu=simulation_menu)
        simulation_button.pack(side="left", padx=(8, 0))
        tk.Label(toolbar, text="Simulation speed:", bg="#e8edf2").pack(side="left", padx=(24, 4))
        self.speed_label = tk.Label(toolbar, bg="#e8edf2")
        self.speed_label.pack(side="right")
        self.average_speed_label = tk.Label(toolbar, bg="#e8edf2")
        self.average_speed_label.pack(side="right", padx=(0, 24))
        self.exit_label = tk.Label(toolbar, bg="#e8edf2")
        self.exit_label.pack(side="right", padx=(0, 24))
        self.speed_control = tk.Scale(toolbar, from_=0.25, to=3.0, resolution=0.25,
                                      orient="horizontal", length=190,
                                      command=self.set_simulation_speed, showvalue=False, bg="#e8edf2")
        self.speed_control.set(1.0)
        self.speed_control.pack(side="left")
        tk.Label(toolbar, text="Traffic:", bg="#e8edf2").pack(side="left", padx=(24, 4))
        self.traffic_control = tk.Scale(toolbar, from_=1, to=30, resolution=1,
                                        orient="horizontal", length=190,
                                        command=self.set_traffic, bg="#e8edf2")
        self.traffic_control.set(12)
        self.traffic_control.pack(side="left")
        self.gap_lane_label = tk.Label(toolbar, bg="#e8edf2")
        self.gap_lane_label.pack(side="left", padx=(24, 4))
        self.gap_control = tk.Scale(
            toolbar, from_=30, to=180, resolution=5, orient="horizontal", length=150,
            command=self.set_selected_lane_gap, bg="#e8edf2",
        )
        self.gap_control.pack(side="left")

    def draw_scene(self) -> None:
        c = self.canvas
        c.delete("static")
        c.create_polygon(0, ROAD_TOP, POST_MERGE_END, ROAD_TOP, POST_MERGE_END, ROAD_TOP + LANE_HEIGHT,
                         MERGE_END, ROAD_TOP + LANE_HEIGHT, MERGE_START, ROAD_BOTTOM, 0, ROAD_BOTTOM,
                         fill="#4d535a", outline="", tags="static")
        c.create_rectangle(0, ROAD_TOP - 13, POST_MERGE_END, ROAD_TOP, fill="#c9cdd0", outline="", tags="static")
        c.create_line(0, ROAD_BOTTOM, MERGE_START, ROAD_BOTTOM, MERGE_END, ROAD_TOP + LANE_HEIGHT,
                      POST_MERGE_END, ROAD_TOP + LANE_HEIGHT, fill="#c9cdd0", width=13, tags="static")
        for lane_index in range(1, LANES):
            y = ROAD_TOP + lane_index * LANE_HEIGHT
            for x in range(-20, MERGE_START, 70):
                c.create_rectangle(x, y - 2, x + 38, y + 2, fill="#f4f0bd", outline="", tags="static")
        for lane_index, lane in enumerate(self.simulation.entry_lanes):
            c.create_text(26, ROAD_TOP + lane_index * LANE_HEIGHT + 18, text=lane.name,
                          fill="#d9dde0", font=("Arial", 10, "bold"), tags="static")

    def draw_car(self, car: Car) -> None:
        if car.item is None or not car.detail_items:
            if car.item is not None:
                self.canvas.delete(car.item)
            car.item = self.create_car_details(car)
        assert car.item is not None
        if car.next_point < len(car.lane.points):
            target_x, target_y = car.lane.points[car.next_point]
            angle = atan2(target_y - car.y, target_x - car.x)
        else:
            angle = 0.0
        forward_x, forward_y = cos(angle), sin(angle)
        side_x, side_y = -forward_y, forward_x
        self.canvas.coords(
            car.item,
            *self.oriented_box(car.x, car.y, forward_x, forward_y, side_x, side_y,
                               car.length / 2, car.width / 2),
        )
        self.canvas.itemconfigure(car.item, fill=car.color)
        wheelLenghtMult = 0.28
        wheelWidthMult = 0.50
        wheel_positions = (
            (car.length * wheelLenghtMult, car.width * wheelWidthMult),
            (car.length * wheelLenghtMult, -car.width * wheelWidthMult),
            (-car.length * wheelLenghtMult, car.width * wheelWidthMult),
            (-car.length * wheelLenghtMult, -car.width * wheelWidthMult),
        )
        for item, (forward, side) in zip(car.detail_items[:4], wheel_positions):
            x = car.x + forward_x * forward + side_x * side
            y = car.y + forward_y * forward + side_y * side
            self.canvas.coords(
                item,
                *self.oriented_box(x, y, forward_x, forward_y, side_x, side_y, 6, 2),
            )

        for item, side in zip(car.detail_items[4:], (car.width * 0.27, -car.width * 0.27)):
            x = car.x + forward_x * (car.length * 0.46) + side_x * side
            y = car.y + forward_y * (car.length * 0.46) + side_y * side
            self.canvas.coords(
                item,
                *self.oriented_box(x, y, forward_x, forward_y, side_x, side_y, 2.5, 3),
            )

        windshield = car.detail_items[6]
        windshield_x = car.x + forward_x * (car.length * 0.20)
        windshield_y = car.y + forward_y * (car.length * 0.10)
        self.canvas.coords(
            windshield,
            *self.oriented_box(
                windshield_x, windshield_y, forward_x, forward_y, side_x, side_y,
                car.length * 0.08, car.width * 0.34,
            ),
        )

    @staticmethod
    def oriented_box(
        x: float, y: float, forward_x: float, forward_y: float,
        side_x: float, side_y: float, half_length: float, half_width: float,
    ) -> list[float]:
        """Return a rotated rectangle suitable for a Tkinter polygon."""
        points = []
        for forward, side in ((half_length, half_width), (half_length, -half_width),
                              (-half_length, -half_width), (-half_length, half_width)):
            points.extend((x + forward_x * forward + side_x * side,
                           y + forward_y * forward + side_y * side))
        return points

    def create_car_details(self, car: Car) -> int:
        """Create a complete car visual and return its body canvas-item ID."""
        wheels = [
            self.canvas.create_polygon(0, 0, 0, 0, fill="#16191c", outline="#08090a")
            for _ in range(4)
        ]
        body = self.canvas.create_polygon(0, 0, 0, 0, outline="#20252a", width=2)
        headlights = [
            self.canvas.create_polygon(0, 0, 0, 0, fill="#fff7b0", outline="")
            for _ in range(2)
        ]
        windshield = self.canvas.create_polygon(
            0, 0, 0, 0, fill="#8ecae6", outline="#29566b"
        )
        car.detail_items = [*wheels, *headlights, windshield]
        return body

    def add_car(self, start_random: bool = False) -> None:
        car = self.simulation.add_car(start_random)
        
        car.item = self.create_car_details(car)
        self.draw_car(car)

    def clear_cars(self) -> None:
        for car in self.simulation.cars:
            self.canvas.delete(car.item)
            for item in car.detail_items:
                self.canvas.delete(item)
        self.simulation.cars.clear()
        self.simulation.record_event("cleared traffic")

    def toggle_running(self) -> None:
        self.running = not self.running

    def set_simulation_speed(self, value: str) -> None:
        self.simulation_speed = float(value)
        self.simulation.record_event(f"simulation speed {self.simulation_speed:g}x")

    def set_traffic(self, value: str) -> None:
        self.simulation.max_cars = int(float(value))
        self.simulation.record_event(f"traffic target {self.simulation.max_cars}")

    def select_lane(self, lane: Lane) -> None:
        self.selected_lane = lane
        self.gap_lane_label.config(text=f"{lane.name.title()} gap:")
        self.gap_control.set(lane.following_gap)

    def set_selected_lane_gap(self, value: str) -> None:
        """Update and record a genuine following-gap change for one lane."""
        gap = float(value)
        if self.selected_lane.following_gap != gap:
            self.selected_lane.following_gap = gap
            self.simulation.record_event(f"{self.selected_lane.name} gap {gap:.0f}px")

    def lane_at(self, position: Point) -> Lane | None:
        lane = min(self.simulation.lanes, key=lambda candidate: candidate.distance_to(position))
        return lane if lane.distance_to(position) <= LANE_HEIGHT / 2 else None

    def show_lane_menu(self, event: tk.Event[tk.Misc]) -> None:
        speed_limit = self.speed_limit_at(event.x, event.y)
        if speed_limit is not None:
            self.show_speedlimit_menu(event, speed_limit)
            return
        lane = self.lane_at((event.x, event.y))
        if lane is None:
            return
        self.select_lane(lane)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label=f"Set {lane.name} lane gap…", command=lambda: self.prompt_for_gap(lane))
        menu.add_command(
            label=f"Add {lane.name} speed-limit sign",
            command=lambda x=event.x, y=event.y, selected_lane=lane: self.add_speedlimit(
                x, y, selected_lane
            ),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    def speed_limit_at(self, x: float, y: float) -> SpeedLimit | None:
        """Return the sign under a right-click, if any."""
        for speed_limit in reversed(self.simulation.speed_limits):
            if abs(speed_limit.x - x) <= 25 and abs(speed_limit.y - y) <= 42:
                return speed_limit
        return None

    def show_speedlimit_menu(
        self, event: tk.Event[tk.Misc], speed_limit: SpeedLimit
    ) -> None:
        """Offer edits for an existing sign instead of adding another one."""
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label=f"Change {speed_limit.speed:.0f} mph limit",
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
        gap = simpledialog.askfloat("Following gap", f"Preferred following gap for the {lane.name} lane (pixels):",
                                    parent=self.root, initialvalue=lane.following_gap, minvalue=30.0, maxvalue=180.0)
        if gap is not None:
            if lane.following_gap != gap:
                lane.following_gap = gap
                self.simulation.record_event(f"{lane.name} gap {gap:.0f}px")
            self.select_lane(lane)

    def add_speedlimit(self, x: float, y: float, lane: Lane) -> None:
        """Post and draw a speed-limit sign at the selected lane location."""
        speed = simpledialog.askfloat("Speed", f"Speed limit for sign",
            parent=self.root, initialvalue=55.0, minvalue=15.0, maxvalue=70.0)
        if speed is None:
            return
        self.simulation.add_speed_limit(speed, lane, x, y)
        self.draw_speed_limits()

    def change_speed_limit(self, speed_limit: SpeedLimit) -> None:
        speed = simpledialog.askfloat(
            "Speed limit", "Speed limit (MPH):", parent=self.root,
            initialvalue=speed_limit.speed, minvalue=15.0, maxvalue=70.0,
        )
        if speed is not None:
            speed_limit.speed = speed
            self.simulation.record_event(
                f"{speed_limit.lane.name} limit changed to {speed:.0f} mph"
            )
            self.draw_speed_limits()

    def delete_speed_limit(self, speed_limit: SpeedLimit) -> None:
        self.simulation.remove_speed_limit(speed_limit)
        self.draw_speed_limits()

    def draw_speed_limits(self) -> None:
        """Redraw all signs after a sign is added, changed, or deleted."""
        self.canvas.delete("speed_limit")
        for speed_limit in self.simulation.speed_limits:
            x, y = speed_limit.x, speed_limit.y
            self.canvas.create_rectangle(x - 25, y - 32, x + 25, y + 42,
                                         fill="#f8f8f8", outline="#20252a", width=2,
                                         tags="speed_limit")
            self.canvas.create_text(x, y - 12, text="SPEED", fill="#20252a",
                                    font=("Arial", 8, "bold"), tags="speed_limit")
            self.canvas.create_text(x, y + 6, text="LIMIT", fill="#20252a",
                                    font=("Arial", 8, "bold"), tags="speed_limit")
            self.canvas.create_text(x, y + 24, text=f"{speed_limit.speed:.0f}",
                                    fill="#20252a", font=("Arial", 12, "bold"),
                                    tags="speed_limit")

    def show_analytics(self) -> None:
        """Show sampled speed/throughput with state-change markers."""
        if self.analytics_window is None or not self.analytics_window.winfo_exists():
            self.analytics_window = tk.Toplevel(self.root)
            self.analytics_window.title("Traffic analytics")
            self.analytics_canvas = tk.Canvas(self.analytics_window, width=800, height=380, bg="white")
            self.analytics_canvas.pack()
            tk.Button(self.analytics_window, text="Export CSV", command=self.export_csv).pack(side="left", padx=8, pady=6)
            tk.Button(self.analytics_window, text="Export SVG", command=self.export_svg).pack(side="left", padx=8, pady=6)
        else:
            self.analytics_window.lift()
        self.draw_analytics()

    def draw_analytics(self) -> None:
        """Redraw the live analytics graph without creating another window."""
        if (
            self.analytics_window is None
            or not self.analytics_window.winfo_exists()
            or self.analytics_canvas is None
        ):
            self.analytics_window = None
            self.analytics_canvas = None
            return
        canvas = self.analytics_canvas
        canvas.delete("all")
        history = self.simulation.history
        canvas.create_text(20, 12, anchor="nw", text="Timeline (state changes)", font=("Arial", 10, "bold"))
        if not history:
            canvas.create_text(400, 190, text="Waiting for samples…")
            return
        start = history[0][0]
        end = max(history[-1][0], start + 1)
        project_x = lambda t: 55 + (t - start) / (end - start) * 720
        for timestamp, description in self.simulation.events[-12:]:
            if start <= timestamp <= end:
                x = project_x(timestamp)
                canvas.create_line(x, 28, x, 58, fill="#777")
                canvas.create_text(x, 25, text=description[:18], anchor="s", angle=45, font=("Arial", 7))
        canvas.create_rectangle(55, 70, 775, 340, outline="#888")
        max_speed = max(70.0, *(row[1] for row in history))
        max_flow = max(5.0, *(row[2] for row in history))
        speed_points, flow_points = [], []
        for timestamp, speed, flow in history:
            x = project_x(timestamp)
            speed_points.extend((x, 340 - speed / max_speed * 250))
            flow_points.extend((x, 340 - flow / max_flow * 250))
        if len(speed_points) >= 4:
            canvas.create_line(*speed_points, fill="#1976d2", width=2)
            canvas.create_line(*flow_points, fill="#e65100", width=2)
        canvas.create_text(60, 355, anchor="w", text="Blue: average MPH    Orange: exits/min")

    def create_recent_changes_window(self) -> None:
        """Show a compact live timeline of events from the last 10 simulated minutes."""
        if self.recent_window is not None and self.recent_window.winfo_exists():
            self.recent_window.lift()
            return
        self.recent_window = tk.Toplevel(self.root)
        self.recent_window.title("Recent changes")
        right_x = self.root.winfo_screenwidth() - 380
        bottom_y = self.root.winfo_screenheight() - 270
        self.recent_window.geometry(f"360x220+{right_x}+{bottom_y}")
        self.recent_canvas = tk.Canvas(self.recent_window, width=360, height=220, bg="#182028")
        self.recent_canvas.pack(fill="both", expand=True)
        self.draw_recent_changes()

    def draw_recent_changes(self) -> None:
        if self.recent_canvas is None or not self.recent_canvas.winfo_exists():
            return
        canvas = self.recent_canvas
        canvas.delete("all")
        now = self.simulation.simulation_time
        events = [(time, text) for time, text in self.simulation.events if time >= now - 600][-10:]
        canvas.create_text(12, 12, anchor="nw", text="Recent changes — last 10 simulated minutes",
                           fill="#d9e7f2", font=("Arial", 10, "bold"))
        for index, (timestamp, text) in enumerate(reversed(events)):
            y = 42 + index * 17
            canvas.create_oval(12, y, 18, y + 6, fill="#f1c40f", outline="")
            canvas.create_text(26, y + 3, anchor="w", text=f"{timestamp:6.1f}s  {text}",
                               fill="#d9e7f2", font=("Courier", 9))

    def report_callback_exception(self, exception_type: type[BaseException], value: BaseException, trace) -> None:
        """Show Tkinter callback failures in the in-app debug panel as well as stderr."""
        formatted = "".join(traceback.format_exception(exception_type, value, trace)).rstrip()
        self.recent_errors.append(formatted)
        self.recent_errors = self.recent_errors[-3:]
        print(formatted)

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(("simulation_seconds", "average_mph", "exits_per_minute"))
            writer.writerows(self.simulation.history)

    def export_svg(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".svg", filetypes=[("SVG", "*.svg")])
        if not path:
            return
        history = self.simulation.history
        if not history:
            return
        start, end = history[0][0], max(history[-1][0], history[0][0] + 1)
        max_speed = max(70.0, *(row[1] for row in history))
        points = " ".join(
            f"{55 + (timestamp - start) / (end - start) * 720:.1f},{340 - speed / max_speed * 250:.1f}"
            for timestamp, speed, _ in history
        )
        with open(path, "w", encoding="utf-8") as output:
            output.write(
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="380">'
                '<rect x="55" y="70" width="720" height="270" fill="white" stroke="#888"/>'
                f'<polyline points="{points}" fill="none" stroke="#1976d2" stroke-width="2"/>'
                '<text x="60" y="355">Average MPH</text></svg>'
            )

    def save_state(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        state = {"time": self.simulation.simulation_time, "lanes": {lane.name: lane.following_gap for lane in self.simulation.lanes},
                 "speed_limits": [{"speed": sign.speed, "lane": sign.lane.name, "x": sign.x, "y": sign.y} for sign in self.simulation.speed_limits],
                 "cars": [{"lane": car.lane.name, "x": car.x, "y": car.y, "speed": car.speed, "cruise": car.cruise_speed, "color": car.color, "next": car.next_point, "preference": car.speed_preference_mph} for car in self.simulation.cars]}
        with open(path, "w", encoding="utf-8") as output:
            json.dump(state, output)

    def load_state(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, encoding="utf-8") as source:
            state = json.load(source)
        self.clear_cars()
        lanes = {lane.name: lane for lane in self.simulation.lanes}
        for name, gap in state["lanes"].items(): lanes[name].following_gap = gap
        self.simulation.speed_limits.clear()
        for sign in state["speed_limits"]: self.simulation.add_speed_limit(sign["speed"], lanes[sign["lane"]], sign["x"], sign["y"])
        for saved in state["cars"]:
            car = Car(lanes[saved["lane"]], saved["x"], saved["y"], saved["speed"], saved["cruise"], saved["color"], next_point=saved["next"], speed_preference_mph=saved["preference"])
            self.simulation.cars.append(car); car.item = self.create_car_details(car); self.draw_car(car)
        self.simulation.simulation_time = state["time"]
        self.draw_speed_limits()

    def exit_app(self) -> None:
        if messagebox.askyesno("Exit simulator", "Exit the freeway simulator?"):
            self.root.destroy()

    def draw_merge_debug(self) -> None:
        self.canvas.delete("merge_debug")
        self.canvas.create_rectangle(12, ROAD_BOTTOM + 20, WIDTH - 12, HEIGHT - 16,
                                     fill="#182028", outline="#54616e", tags="merge_debug")
        lines = self.simulation.merge_debug_lines()
        if self.recent_errors:
            lines.extend(("", "PYTHON ERRORS:", *self.recent_errors[-1].splitlines()[-3:]))
        self.canvas.create_text(26, ROAD_BOTTOM + 34, anchor="nw",
                                text="\n".join(lines), fill="#d9e7f2",
                                font=("Courier", 10), tags="merge_debug")

    def tick(self) -> None:
        now = time.perf_counter()
        dt = min(now - self.last_time, 0.1)
        self.last_time = now
        if self.running:
            for car in self.simulation.update(dt * self.simulation_speed):
                self.canvas.delete(car.item)
                for item in car.detail_items:
                    self.canvas.delete(item)
            for car in self.simulation.cars:
                if car.item is None:
                    car.item = self.create_car_details(car)
                self.draw_car(car)
                self.canvas.tag_raise("speed_limit")
        self.speed_label.config(text=f"{self.simulation_speed:.2g}x")
        self.exit_label.config(text=f"Cars exited/min: {self.simulation.exits_per_minute():.0f}")
        self.average_speed_label.config(text=f"Average speed: {self.simulation.average_speed_mph():.0f} mph")
        self.draw_merge_debug()
        if now - self.last_dashboard_refresh >= 1.0:
            self.draw_analytics()
            self.draw_recent_changes()
            self.last_dashboard_refresh = now
        self.root.after(16, self.tick)
