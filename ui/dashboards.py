"""Analytics, recent-change, and debug windows."""

from __future__ import annotations

import traceback
import tkinter as tk

from config import DEFAULT_SPEED_LIMIT_MPH
from units import mph_to_display, speed_unit

from .base import window_exists


def routed_car_debug_lines(cars: list[object]) -> list[str]:
    """Format compact, live decision state for constructed-road cars."""
    lines: list[str] = []
    for car in cars:
        brain = car.brain
        reason = f" · {brain.wait_reason}" if brain.wait_reason else ""
        lines.append(
            f"{car.id}: {brain.state.value} "
            f"v={car.speed:.1f} target={brain.desired_speed:.1f} "
            f"signal={brain.signal_intent.value}{reason}"
        )
    return lines


def frame_statistics(samples: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    """Return latest/average/worst frame time in ms and average FPS."""
    if not samples:
        return None
    intervals = [sample[1] for sample in samples]
    latest_ms = intervals[-1] * 1000
    average_ms = sum(intervals) / len(intervals) * 1000
    worst_ms = max(intervals) * 1000
    average_fps = 1000 / average_ms if average_ms > 0 else 0.0
    return latest_ms, average_ms, worst_ms, average_fps


class DashboardMixin:
    """Create and refresh secondary diagnostic windows."""

    def show_analytics(self) -> None:
        if not window_exists(self.analytics_window):
            self.analytics_window = tk.Toplevel(self.root)
            self.analytics_window.title("Traffic analytics")
            self.analytics_canvas = tk.Canvas(
                self.analytics_window, width=800, height=380, bg="white",
            )
            self.analytics_canvas.pack()
            tk.Button(
                self.analytics_window, text="Export CSV", command=self.export_csv,
            ).pack(side="left", padx=8, pady=6)
            tk.Button(
                self.analytics_window, text="Export SVG", command=self.export_svg,
            ).pack(side="left", padx=8, pady=6)
        else:
            self.analytics_window.lift()
        self.draw_analytics()

    def show_performance_graph(self) -> None:
        """Show a bounded live graph of UI frame timing and frame rate."""
        if not window_exists(self.performance_window):
            self.performance_window = tk.Toplevel(self.root)
            self.performance_window.title("Performance")
            self.performance_canvas = tk.Canvas(
                self.performance_window, width=800, height=420, bg="white",
            )
            self.performance_canvas.pack()
        else:
            self.performance_window.lift()
        self.draw_performance_graph()

    def draw_performance_graph(self) -> None:
        if not window_exists(self.performance_window) or self.performance_canvas is None:
            self.performance_window = None
            self.performance_canvas = None
            return
        canvas = self.performance_canvas
        canvas.delete("all")
        samples = self.frame_history
        stats = frame_statistics(samples)
        canvas.create_text(
            20, 12, anchor="nw", text="UI performance (last 20 seconds)",
            font=("Arial", 11, "bold"),
        )
        if stats is None:
            canvas.create_text(400, 210, text="Waiting for frame samples…")
            return
        latest_ms, average_ms, worst_ms, average_fps = stats
        canvas.create_text(
            20,
            32,
            anchor="nw",
            text=(
                f"Latest: {latest_ms:.1f} ms  ·  Average: {average_ms:.1f} ms "
                f"({average_fps:.1f} FPS)  ·  Worst: {worst_ms:.1f} ms"
            ),
            font=("Arial", 9),
        )
        if len(samples) < 2:
            return

        start = samples[0][0]
        end = max(samples[-1][0], start + 0.001)

        def project_x(timestamp: float) -> float:
            return 60 + (timestamp - start) / (end - start) * 710

        def draw_plot(
            top: float,
            bottom: float,
            values: list[float],
            label: str,
            color: str,
            unit: str,
            target: float | None = None,
        ) -> None:
            maximum = max(1.0, max(values) * 1.1, (target or 0.0) * 1.15)
            canvas.create_rectangle(60, top, 770, bottom, outline="#888")
            canvas.create_text(12, top, anchor="w", text=label, font=("Arial", 9, "bold"))
            canvas.create_text(55, top, anchor="e", text=f"{maximum:.0f} {unit}", font=("Arial", 8))
            canvas.create_text(55, bottom, anchor="e", text=f"0 {unit}", font=("Arial", 8))
            if target is not None:
                y = bottom - min(1.0, target / maximum) * (bottom - top)
                canvas.create_line(60, y, 770, y, fill="#b0b0b0", dash=(4, 3))
                canvas.create_text(772, y, anchor="w", text=f"{target:g}", fill="#777", font=("Arial", 8))
            points: list[float] = []
            for (timestamp, _interval), value in zip(samples, values):
                points.extend((
                    project_x(timestamp),
                    bottom - min(1.0, value / maximum) * (bottom - top),
                ))
            canvas.create_line(*points, fill=color, width=2)

        frame_ms = [interval * 1000 for _timestamp, interval in samples]
        fps = [1 / interval if interval > 0 else 0.0 for _timestamp, interval in samples]
        draw_plot(72, 220, frame_ms, "Frame time", "#d84315", "ms", 16.67)
        draw_plot(260, 408, fps, "Frame rate", "#1565c0", "FPS", 60.0)

    def draw_analytics(self) -> None:
        if not window_exists(self.analytics_window) or self.analytics_canvas is None:
            self.analytics_window = None
            self.analytics_canvas = None
            return
        canvas = self.analytics_canvas
        canvas.delete("all")
        history = self.simulation.history
        canvas.create_text(
            20, 12, anchor="nw", text="Timeline (state changes)",
            font=("Arial", 10, "bold"),
        )
        if not history:
            canvas.create_text(400, 190, text="Waiting for samples…")
            return
        start = history[0][0]
        end = max(history[-1][0], start + 1)

        def project_x(timestamp: float) -> float:
            return 55 + (timestamp - start) / (end - start) * 720

        for timestamp, description in self.simulation.events[-12:]:
            if start <= timestamp <= end:
                x = project_x(timestamp)
                canvas.create_line(x, 28, x, 58, fill="#777")
                canvas.create_text(
                    x, 25, text=description[:18], anchor="s", angle=45,
                    font=("Arial", 7),
                )
        canvas.create_rectangle(55, 70, 775, 340, outline="#888")
        display_speeds = [mph_to_display(row[1], self.unit_system) for row in history]
        max_speed = max(
            mph_to_display(DEFAULT_SPEED_LIMIT_MPH, self.unit_system), *display_speeds,
        )
        max_flow = max(5.0, *(row[2] for row in history))
        speed_points: list[float] = []
        flow_points: list[float] = []
        for (timestamp, _speed, flow), speed in zip(history, display_speeds):
            x = project_x(timestamp)
            speed_points.extend((x, 340 - speed / max_speed * 250))
            flow_points.extend((x, 340 - flow / max_flow * 250))
        if len(speed_points) >= 4:
            canvas.create_line(*speed_points, fill="#1976d2", width=2)
            canvas.create_line(*flow_points, fill="#e65100", width=2)
        canvas.create_text(
            60, 355, anchor="w",
            text=f"Blue: average {speed_unit(self.unit_system)}    Orange: exits/min",
        )

    def create_recent_changes_window(self) -> None:
        if window_exists(self.recent_window):
            self.recent_window.lift()
            return
        self.recent_window = tk.Toplevel(self.root)
        self.recent_window.title("Recent changes")
        right_x = self.root.winfo_screenwidth() - 380
        bottom_y = self.root.winfo_screenheight() - 270
        self.recent_window.geometry(f"360x220+{right_x}+{bottom_y}")
        self.recent_canvas = tk.Canvas(
            self.recent_window, width=360, height=220, bg="#182028",
        )
        self.recent_canvas.pack(fill="both", expand=True)
        self.draw_recent_changes()

    def draw_recent_changes(self) -> None:
        if not window_exists(self.recent_canvas):
            return
        canvas = self.recent_canvas
        canvas.delete("all")
        now = self.simulation.simulation_time
        events = [
            (timestamp, text)
            for timestamp, text in self.simulation.events
            if timestamp >= now - 600
        ][-10:]
        canvas.create_text(
            12, 12, anchor="nw", text="Recent changes — last 10 simulated minutes",
            fill="#d9e7f2", font=("Arial", 10, "bold"),
        )
        for index, (timestamp, text) in enumerate(reversed(events)):
            y = 42 + index * 17
            canvas.create_oval(12, y, 18, y + 6, fill="#f1c40f", outline="")
            canvas.create_text(
                26, y + 3, anchor="w", text=f"{timestamp:6.1f}s  {text}",
                fill="#d9e7f2", font=("Courier", 9),
            )

    def report_callback_exception(
        self, exception_type: type[BaseException], value: BaseException, trace,
    ) -> None:
        formatted = "".join(
            traceback.format_exception(exception_type, value, trace)
        ).rstrip()
        self.recent_errors.append(formatted)
        self.recent_errors = self.recent_errors[-3:]
        print(formatted)

    def draw_merge_debug(self) -> None:
        if not window_exists(self.debug_canvas):
            return
        self.debug_canvas.delete("all")
        self.debug_canvas.create_rectangle(
            0, 0, 500, 260, fill="#182028", outline="#54616e",
        )
        lines = self.simulation.merge_debug_lines()
        routed_lines = routed_car_debug_lines(self.test_traffic.cars)
        if routed_lines:
            lines.extend(("", "ROUTED CAR BRAINS:", *routed_lines[:8]))
        if self.recent_errors:
            lines.extend(("", "PYTHON ERRORS:", *self.recent_errors[-1].splitlines()[-3:]))
        self.debug_canvas.create_text(
            14, 14, anchor="nw", text="\n".join(lines), fill="#d9e7f2",
            font=("Courier", 10),
        )

    def create_debug_window(self) -> None:
        if window_exists(self.debug_window):
            return
        self.debug_window = tk.Toplevel(self.root)
        self.debug_window.title("Simulator debug")
        bottom_y = self.root.winfo_screenheight() - 310
        self.debug_window.geometry(f"500x260+0+{bottom_y}")
        self.debug_canvas = tk.Canvas(
            self.debug_window, width=500, height=260, highlightthickness=0,
        )
        self.debug_canvas.pack(fill="both", expand=True)
        self.draw_merge_debug()
