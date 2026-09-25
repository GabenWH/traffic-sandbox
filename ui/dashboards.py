"""Analytics, recent-change, and debug windows."""

from __future__ import annotations

import traceback
import tkinter as tk
from collections.abc import Iterable, Sequence

from config import DEFAULT_SPEED_LIMIT_MPH
from simulation_profiler import SimulationTickSample
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


def stacked_timing_rows(
    samples: Sequence[SimulationTickSample],
    selected_blocks: Iterable[str],
) -> tuple[tuple[int, tuple[tuple[str, float], ...]], ...]:
    """Return selected phase values for a stacked graph, excluding total time."""
    blocks = tuple(block for block in selected_blocks if block != "total")
    return tuple(
        (
            sample.tick,
            tuple((block, sample.timings_ms.get(block, 0.0)) for block in blocks),
        )
        for sample in samples
    )


def profile_tick_at_position(
    samples: Sequence[SimulationTickSample],
    x: float,
    y: float,
    bounds: tuple[float, float, float, float],
) -> int | None:
    """Return the tick in the rendered bar slot under a plot click."""
    sample = profile_sample_at_position(samples, x, y, bounds)
    return sample.tick if sample is not None else None


def profile_sample_at_position(
    samples: Sequence[SimulationTickSample],
    x: float,
    y: float,
    bounds: tuple[float, float, float, float],
) -> SimulationTickSample | None:
    """Return the sample in the equal-width bar slot under a plot click."""
    if not samples:
        return None
    left, top, right, bottom = bounds
    if right <= left or bottom <= top or not (left <= x <= right and top <= y <= bottom):
        return None
    proportion = (x - left) / (right - left)
    index = min(len(samples) - 1, int(proportion * len(samples)))
    return samples[index]


def selected_profile_sample(
    samples: Sequence[SimulationTickSample],
    selected: SimulationTickSample | None,
) -> SimulationTickSample | None:
    """Keep an explicitly selected sample available after history rolls over."""
    if selected is None:
        return samples[-1] if samples else None
    return next(
        (
            sample for sample in samples
            if sample.system == selected.system and sample.tick == selected.tick
        ),
        selected,
    )


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
            tk.Button(
                self.performance_window,
                text="Simulation profiler…",
                command=self.show_simulation_performance_graph,
            ).pack(anchor="e", padx=8, pady=(0, 6))
        else:
            self.performance_window.lift()
        self.draw_performance_graph()

    def show_simulation_performance_graph(self) -> None:
        """Open a phase-level simulation profiler separate from UI frame time."""
        if not window_exists(self.simulation_performance_window):
            window = tk.Toplevel(self.root)
            self.simulation_performance_window = window
            window.title("Simulation performance")
            width, height = 1120, 740
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            if window_exists(self.performance_window):
                x = self.performance_window.winfo_x() + self.performance_window.winfo_width() + 8
                y = self.performance_window.winfo_y()
            else:
                x, y = screen_width - width, 50
            x = min(max(0, x), max(0, screen_width - width))
            y = min(max(0, y), max(0, screen_height - height))
            window.geometry(f"{width}x{height}+{x}+{y}")

            controls = tk.Frame(window, padx=8, pady=6)
            controls.pack(fill="x")
            tk.Label(controls, text="System:").pack(side="left")
            self.simulation_performance_system_var = tk.StringVar(master=window)
            self.simulation_performance_system_menu = tk.OptionMenu(
                controls,
                self.simulation_performance_system_var,
                "",
            )
            self.simulation_performance_system_menu.pack(side="left", padx=(4, 12))
            tk.Button(
                controls,
                text="Export JSON",
                command=self.export_simulation_profile_json,
            ).pack(side="right", padx=(4, 0))
            tk.Button(
                controls,
                text="Export CSV",
                command=self.export_simulation_profile_csv,
            ).pack(side="right", padx=(4, 0))

            content = tk.Frame(window, padx=8, pady=4)
            content.pack(fill="both", expand=True)
            phase_panel = tk.Frame(content)
            phase_panel.pack(side="left", fill="y", padx=(0, 8))
            tk.Label(phase_panel, text="Timing blocks (multi-select)").pack(anchor="w")
            block_list_frame = tk.Frame(phase_panel)
            block_list_frame.pack(fill="y", expand=True)
            self.simulation_performance_block_list = tk.Listbox(
                block_list_frame,
                width=25,
                height=14,
                selectmode="extended",
                exportselection=False,
            )
            scrollbar = tk.Scrollbar(
                block_list_frame,
                orient="vertical",
                command=self.simulation_performance_block_list.yview,
            )
            self.simulation_performance_block_list.configure(
                yscrollcommand=scrollbar.set,
            )
            self.simulation_performance_block_list.pack(side="left", fill="y", expand=True)
            scrollbar.pack(side="right", fill="y")
            self.simulation_performance_block_list.bind(
                "<<ListboxSelect>>",
                lambda _event: self.draw_simulation_performance_graph(),
            )

            graph_panel = tk.Frame(content)
            graph_panel.pack(side="left", fill="both", expand=True)
            self.simulation_performance_canvas = tk.Canvas(
                graph_panel,
                width=830,
                height=430,
                bg="white",
                highlightthickness=1,
                highlightbackground="#888",
            )
            self.simulation_performance_canvas.pack(fill="both", expand=True)
            self.simulation_performance_canvas.bind(
                "<Button-1>", self.select_simulation_profile_tick,
            )
            self.simulation_performance_summary = tk.Label(
                graph_panel,
                anchor="nw",
                justify="left",
                font=("Courier", 9),
            )
            self.simulation_performance_summary.pack(fill="x", pady=(8, 2))
            self.simulation_performance_tick_details = tk.Label(
                graph_panel,
                anchor="nw",
                justify="left",
                font=("Courier", 9),
            )
            self.simulation_performance_tick_details.pack(fill="x", pady=(4, 0))
            window.protocol(
                "WM_DELETE_WINDOW", self.close_simulation_performance_graph,
            )
        else:
            self.simulation_performance_window.lift()
        self.draw_simulation_performance_graph()

    def close_simulation_performance_graph(self) -> None:
        if window_exists(self.simulation_performance_window):
            self.simulation_performance_window.destroy()
        self.simulation_performance_window = None
        self.simulation_performance_system_var = None
        self.simulation_performance_system_menu = None
        self.simulation_performance_block_list = None
        self.simulation_performance_canvas = None
        self.simulation_performance_summary = None
        self.simulation_performance_tick_details = None
        self.simulation_performance_block_names = ()
        self.simulation_performance_selected_tick = None
        self.simulation_performance_selected_sample = None
        self.simulation_performance_visible_samples = ()
        self.simulation_performance_visible_bounds = None
        self.simulation_performance_system = ""

    def _select_simulation_profile_system(self, system: str) -> None:
        self.simulation_performance_system = system
        self.simulation_performance_system_var.set(system)
        self.simulation_performance_block_names = ()
        self.simulation_performance_selected_tick = None
        self.simulation_performance_selected_sample = None
        self.draw_simulation_performance_graph()

    def _refresh_simulation_profile_systems(self, systems: tuple[str, ...]) -> str:
        variable = self.simulation_performance_system_var
        menu_widget = self.simulation_performance_system_menu
        if variable is None or menu_widget is None:
            return ""
        selected = variable.get()
        if selected not in systems:
            selected = systems[0] if systems else ""
            variable.set(selected)
        menu = menu_widget["menu"]
        menu.delete(0, "end")
        for system in systems:
            menu.add_command(
                label=system,
                command=lambda item=system: self._select_simulation_profile_system(item),
            )
        if selected != self.simulation_performance_system:
            self.simulation_performance_system = selected
            self.simulation_performance_block_names = ()
            self.simulation_performance_selected_tick = None
            self.simulation_performance_selected_sample = None
        return selected

    def _refresh_simulation_profile_blocks(self, block_names: tuple[str, ...]) -> None:
        block_list = self.simulation_performance_block_list
        if block_list is None or block_names == self.simulation_performance_block_names:
            return
        block_list.delete(0, "end")
        for name in block_names:
            block_list.insert("end", name)
        for index in range(len(block_names)):
            block_list.selection_set(index)
        self.simulation_performance_block_names = block_names

    def select_simulation_profile_tick(self, event: tk.Event[tk.Misc]) -> None:
        samples = self.simulation_performance_visible_samples
        bounds = self.simulation_performance_visible_bounds
        if not samples or bounds is None:
            return

        selected_sample = profile_sample_at_position(
            samples,
            event.x,
            event.y,
            bounds,
        )
        if selected_sample is None:
            return
        self.simulation_performance_selected_sample = selected_sample
        self.simulation_performance_selected_tick = selected_sample.tick
        self.draw_simulation_performance_graph()

    def draw_simulation_performance_graph(self) -> None:
        window = self.simulation_performance_window
        canvas = self.simulation_performance_canvas
        if not window_exists(window) or canvas is None:
            self.simulation_performance_window = None
            self.simulation_performance_canvas = None
            return

        profiler = self.test_traffic.profiler
        system = self._refresh_simulation_profile_systems(profiler.systems)
        samples = profiler.samples_for(system) if system else ()
        self.simulation_performance_visible_samples = ()
        self.simulation_performance_visible_bounds = None
        phases = tuple(sorted({
            phase for sample in samples for phase in sample.timings_ms
        }))
        self._refresh_simulation_profile_blocks(phases)
        selected_indices = self.simulation_performance_block_list.curselection()
        selected_blocks = tuple(
            self.simulation_performance_block_list.get(index)
            for index in selected_indices
        )

        canvas.delete("all")
        canvas.create_text(
            16,
            12,
            anchor="nw",
            text=f"{system or 'Simulation'} phase timing (retained ticks)",
            font=("Arial", 11, "bold"),
        )
        if not samples:
            canvas.create_text(
                max(400, canvas.winfo_width() / 2),
                max(210, canvas.winfo_height() / 2),
                text="Waiting for simulation tick samples…",
            )
            self._set_simulation_profile_labels("No timing samples yet.", "")
            return
        if not selected_blocks:
            canvas.create_text(
                max(400, canvas.winfo_width() / 2),
                max(210, canvas.winfo_height() / 2),
                text="Select one or more timing blocks to graph.",
            )
            self._set_simulation_profile_labels(
                "Select timing blocks to see aggregate statistics.", "",
            )
            return

        rows = stacked_timing_rows(samples, selected_blocks)
        row_values = [sum(value for _name, value in values) for _tick, values in rows]
        selected_totals = [
            sample.timings_ms.get("total", 0.0)
            for sample in samples
        ] if "total" in selected_blocks else []
        maximum = max(
            1.0,
            max(row_values, default=0.0) * 1.1,
            max(selected_totals, default=0.0) * 1.1,
        )
        width = max(830, int(canvas.winfo_width()))
        height = max(430, int(canvas.winfo_height()))
        left, right, top, bottom = 64.0, width - 24.0, 76.0, height - 66.0
        self.simulation_performance_visible_samples = tuple(samples)
        self.simulation_performance_visible_bounds = (left, top, right, bottom)
        canvas.create_rectangle(left, top, right, bottom, outline="#888")
        for step in range(5):
            value = maximum * step / 4
            y = bottom - step / 4 * (bottom - top)
            canvas.create_line(left, y, right, y, fill="#e0e0e0")
            canvas.create_text(
                left - 6, y, anchor="e", text=f"{value:.1f} ms",
                font=("Arial", 8),
            )

        palette = (
            "#1565c0", "#ef6c00", "#2e7d32", "#8e24aa",
            "#00838f", "#c62828", "#6d4c41", "#546e7a",
        )
        colors = {
            name: palette[index % len(palette)]
            for index, name in enumerate(sorted(
                name for name in selected_blocks if name != "total"
            ))
        }
        plot_width = right - left
        slot_width = plot_width / max(1, len(rows))
        for index, (_tick, values) in enumerate(rows):
            x0 = left + index * slot_width + min(0.5, slot_width * 0.08)
            x1 = left + (index + 1) * slot_width - min(0.5, slot_width * 0.08)
            if x1 <= x0:
                x1 = x0 + 0.5
            y_bottom = bottom
            for name, value in values:
                if name == "total" or value <= 0:
                    continue
                segment_height = value / maximum * (bottom - top)
                y_top = y_bottom - segment_height
                canvas.create_rectangle(
                    x0, y_top, x1, y_bottom,
                    fill=colors[name], outline="",
                )
                y_bottom = y_top

        if "total" in selected_blocks:
            total_points: list[float] = []
            for index, sample in enumerate(samples):
                total_points.extend((
                    left + (index + 0.5) * slot_width,
                    bottom - min(1.0, sample.timings_ms.get("total", 0.0) / maximum)
                    * (bottom - top),
                ))
            if len(total_points) >= 4:
                canvas.create_line(
                    *total_points, fill="#263238", width=2, dash=(4, 3),
                )

        if rows:
            canvas.create_text(
                left, bottom + 18, anchor="w",
                text=f"tick {rows[0][0]}", font=("Arial", 8),
            )
            canvas.create_text(
                right, bottom + 18, anchor="e",
                text=f"tick {rows[-1][0]}", font=("Arial", 8),
            )

        selected_sample = selected_profile_sample(
            samples,
            self.simulation_performance_selected_sample,
        )
        if selected_sample is None:
            return
        self.simulation_performance_selected_tick = selected_sample.tick
        sample_index = next((
            index for index, sample in enumerate(samples)
            if sample.tick == selected_sample.tick
        ), None)
        if sample_index is not None:
            marker_x = left + (sample_index + 0.5) * slot_width
            canvas.create_line(marker_x, top, marker_x, bottom, fill="#d32f2f", width=2)
            canvas.create_text(
                min(right - 4, marker_x + 4), top + 4, anchor="nw",
                text=f"tick {selected_sample.tick}",
                fill="#d32f2f", font=("Arial", 8, "bold"),
            )
        else:
            canvas.create_text(
                left + 8, top + 8, anchor="nw",
                text=f"Selected tick {selected_sample.tick} has rolled out of retained history",
                fill="#d32f2f", font=("Arial", 9, "bold"),
            )

        legend_blocks = tuple(selected_blocks)
        for index, block in enumerate(legend_blocks):
            legend_x = left + (index % 4) * 180
            legend_y = 40 + (index // 4) * 14
            if block == "total":
                canvas.create_line(
                    legend_x, legend_y + 5, legend_x + 12, legend_y + 5,
                    fill="#263238", width=2, dash=(4, 3),
                )
            else:
                canvas.create_rectangle(
                    legend_x, legend_y, legend_x + 10, legend_y + 10,
                    fill=colors[block], outline="",
                )
            canvas.create_text(
                legend_x + 15, legend_y + 5, anchor="w",
                text=block, font=("Arial", 8),
            )

        stats = profiler.statistics(system)
        summary_lines = [
            "Selected-block statistics over retained ticks:",
            "block                     mean    median      p95      p99      max (ms)",
        ]
        for block in selected_blocks:
            if block not in stats:
                continue
            stat = stats[block]
            summary_lines.append(
                f"{block[:24]:<24} {stat['mean_ms']:>7.2f} {stat['median_ms']:>9.2f} "
                f"{stat['p95_ms']:>8.2f} {stat['p99_ms']:>8.2f} {stat['max_ms']:>8.2f}"
            )
        sample = selected_sample
        counts = ", ".join(
            f"{name}={count}" for name, count in sorted(sample.entity_counts.items())
        ) or "no entity counts"
        detail_lines = [
            f"Selected tick {sample.tick} · sim={sample.simulated_time:.3f}s · "
            f"dt={sample.elapsed_seconds:.3f}s · {counts}",
            "Block timings:",
        ]
        detail_lines.extend(
            f"  {name}: {duration:.4f} ms"
            for name, duration in sorted(
                sample.timings_ms.items(), key=lambda item: (-item[1], item[0]),
            )
        )
        self._set_simulation_profile_labels(
            "\n".join(summary_lines), "\n".join(detail_lines),
        )

    def _set_simulation_profile_labels(self, summary: str, details: str) -> None:
        if self.simulation_performance_summary is not None:
            self.simulation_performance_summary.configure(text=summary)
        if self.simulation_performance_tick_details is not None:
            self.simulation_performance_tick_details.configure(text=details)

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
        trace_summary = self.test_traffic.debugger.latest_summary()
        if trace_summary is not None:
            lines.extend(("", trace_summary))
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
