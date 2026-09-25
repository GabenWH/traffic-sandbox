"""Tests for UI-frame performance calculations."""

import unittest
from types import SimpleNamespace

from simulation_profiler import SimulationProfiler
from ui.dashboards import (
    DashboardMixin,
    frame_statistics,
    profile_tick_at_position,
    selected_profile_sample,
    stacked_timing_rows,
)


class PerformanceMetricTests(unittest.TestCase):
    def test_frame_statistics_reports_frame_time_and_fps(self) -> None:
        statistics = frame_statistics([
            (0.0, 0.010),
            (0.1, 0.020),
            (0.2, 0.030),
        ])

        self.assertEqual(statistics, (30.0, 20.0, 30.0, 50.0))

    def test_frame_statistics_needs_at_least_one_sample(self) -> None:
        self.assertIsNone(frame_statistics([]))

    def test_stacked_profile_data_uses_selected_phases_and_excludes_total(self) -> None:
        profiler = SimulationProfiler()
        profiler.record_tick(
            system="routed_traffic",
            simulated_time=1.0,
            elapsed_seconds=0.05,
            entity_counts={"cars": 3},
            timings_ms={
                "snapshot": 1.5,
                "intent_generation": 2.0,
                "total": 9.0,
            },
        )

        rows = stacked_timing_rows(
            profiler.samples,
            ("intent_generation", "total", "snapshot"),
        )

        self.assertEqual(rows, (
            (1, (("intent_generation", 2.0), ("snapshot", 1.5))),
        ))

    def test_stacked_profile_data_handles_empty_history(self) -> None:
        self.assertEqual(stacked_timing_rows((), ("total",)), ())

    def test_profile_plot_click_selects_ticks_and_ignores_outside_clicks(self) -> None:
        profiler = SimulationProfiler()
        for tick in (1, 2, 3):
            profiler.record_tick(
                system="routed_traffic",
                simulated_time=tick * 0.05,
                elapsed_seconds=0.05,
                entity_counts={"cars": tick},
                timings_ms={"total": float(tick)},
            )

        bounds = (64.0, 76.0, 806.0, 364.0)
        self.assertEqual(profile_tick_at_position(profiler.samples, 64, 100, bounds), 1)
        self.assertEqual(profile_tick_at_position(profiler.samples, 806, 100, bounds), 3)
        self.assertIsNone(profile_tick_at_position(profiler.samples, 806, 400, bounds))
        self.assertIsNone(profile_tick_at_position((), 64, 100, bounds))

    def test_profile_plot_hit_testing_matches_equal_width_bar_slots(self) -> None:
        profiler = SimulationProfiler()
        for tick in (1, 2, 3):
            profiler.record_tick(
                system="routed_traffic",
                simulated_time=tick * 0.05,
                elapsed_seconds=0.05,
                entity_counts={"cars": tick},
                timings_ms={"total": float(tick)},
            )

        bounds = (64.0, 76.0, 806.0, 364.0)
        left, _top, right, _bottom = bounds
        plot_width = right - left
        for index, expected_tick in enumerate((1, 2, 3)):
            center = left + (index + 0.5) * plot_width / 3
            with self.subTest(tick=expected_tick):
                self.assertEqual(
                    profile_tick_at_position(profiler.samples, center, 100, bounds),
                    expected_tick,
                )
        self.assertEqual(
            profile_tick_at_position(
                profiler.samples,
                left + 0.30 * plot_width,
                100,
                bounds,
            ),
            1,
        )

    def test_click_selects_the_sample_from_the_last_rendered_snapshot(self) -> None:
        visible_profiler = SimulationProfiler(max_samples=3)
        for tick in (1, 2, 3):
            visible_profiler.record_tick(
                system="routed_traffic",
                simulated_time=tick * 0.05,
                elapsed_seconds=0.05,
                entity_counts={"cars": tick},
                timings_ms={"total": float(tick)},
            )

        live_profiler = SimulationProfiler(max_samples=3)
        for tick in (1, 2, 3, 4):
            live_profiler.record_tick(
                system="routed_traffic",
                simulated_time=tick * 0.05,
                elapsed_seconds=0.05,
                entity_counts={"cars": tick},
                timings_ms={"total": float(tick)},
            )

        bounds = (64.0, 76.0, 806.0, 364.0)
        dashboard = SimpleNamespace(
            simulation_performance_canvas=SimpleNamespace(
                winfo_width=lambda: 830,
                winfo_height=lambda: 430,
            ),
            simulation_performance_visible_samples=visible_profiler.samples,
            simulation_performance_visible_bounds=bounds,
            simulation_performance_system="routed_traffic",
            simulation_performance_selected_tick=None,
            simulation_performance_selected_sample=None,
            test_traffic=SimpleNamespace(profiler=live_profiler),
            draw_simulation_performance_graph=lambda: None,
        )
        x = bounds[0] + (0.5 / 3) * (bounds[2] - bounds[0])

        DashboardMixin.select_simulation_profile_tick(
            dashboard,
            SimpleNamespace(x=x, y=100),
        )

        self.assertEqual(dashboard.simulation_performance_selected_tick, 1)
        self.assertEqual(dashboard.simulation_performance_selected_sample.tick, 1)
        self.assertNotIn(
            1,
            [sample.tick for sample in live_profiler.samples_for("routed_traffic")],
        )

    def test_selected_profile_sample_survives_history_rollover(self) -> None:
        displayed_profiler = SimulationProfiler(max_samples=3)
        for tick in (1, 2, 3):
            displayed_profiler.record_tick(
                system="routed_traffic",
                simulated_time=tick * 0.05,
                elapsed_seconds=0.05,
                entity_counts={"cars": tick},
                timings_ms={"total": float(tick)},
            )
        selected = displayed_profiler.samples[0]

        live_profiler = SimulationProfiler(max_samples=3)
        for tick in (1, 2, 3, 4):
            live_profiler.record_tick(
                system="routed_traffic",
                simulated_time=tick * 0.05,
                elapsed_seconds=0.05,
                entity_counts={"cars": tick},
                timings_ms={"total": float(tick)},
            )

        current_samples = live_profiler.samples_for("routed_traffic")
        self.assertIs(selected_profile_sample(current_samples, selected), selected)
        self.assertIs(selected_profile_sample(current_samples, None), current_samples[-1])


if __name__ == "__main__":
    unittest.main()
