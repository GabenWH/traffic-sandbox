"""The merge lab keeps difficult traffic states reproducible."""

from math import sqrt
import unittest

from merge_lab import MergeLab, _overlapping_pairs, scenario_catalog


class MergeLabTests(unittest.TestCase):
    def test_overlap_audit_checks_nearby_buckets_without_missing_a_collision(self):
        scenario = next(
            item for item in scenario_catalog()
            if item.name == "roundabout-simultaneous-entry"
        )
        _city, traffic = scenario.build(1)
        first, second = traffic.cars
        second.position = first.position

        self.assertEqual(_overlapping_pairs(traffic.cars), [(first, second)])

        second.position = (first.position[0] + 1000, first.position[1] + 1000)
        self.assertEqual(_overlapping_pairs(traffic.cars), [])

    def test_overlap_audit_handles_rotated_large_cars_across_cell_boundaries(self):
        scenario = next(
            item for item in scenario_catalog()
            if item.name == "roundabout-simultaneous-entry"
        )
        _city, traffic = scenario.build(2)
        first, second = traffic.cars
        first.length = first.width = second.length = second.width = 32.0
        first.heading = second.heading = (1 / sqrt(2), 1 / sqrt(2))
        first.position = (31.9, 100.0)
        second.position = (64.1, 100.0)

        self.assertEqual(_overlapping_pairs(traffic.cars), [(first, second)])

    def test_catalog_covers_clear_competing_queued_and_short_link_cases(self):
        names = {scenario.name for scenario in scenario_catalog()}
        self.assertTrue({
            "roundabout-clear-entry",
            "roundabout-circulating-leader",
            "roundabout-simultaneous-entry",
            "roundabout-queued-ring",
            "roundabout-continuous-pressure",
            "slip-lane-short-link",
            "dense-network-gauntlet",
        }.issubset(names))

    def test_dense_gauntlet_combines_varied_junctions_and_high_demand(self):
        scenario = next(
            item for item in scenario_catalog()
            if item.name == "dense-network-gauntlet"
        )

        city, traffic = scenario.build(11)

        self.assertGreaterEqual(len(city.standard_intersections), 12)
        self.assertGreaterEqual(len(city.cul_de_sacs), 8)
        self.assertGreaterEqual(
            sum(junction.kind.value == "roundabout"
                for junction in city.standard_intersections),
            2,
        )
        self.assertTrue(any(road.reverse_lane_count == 0 for road in city.roads))
        self.assertTrue(any(road.reverse_lane_count > 0 for road in city.roads))
        self.assertEqual(
            sum(junction.is_all_way_stop for junction in city.standard_intersections),
            3,
        )
        self.assertGreaterEqual(sum(
            road.reverse_lane_count == 0 and len(road.centerline) >= 3
            for road in city.roads
        ), 2)
        self.assertGreaterEqual(traffic.max_cars, 200)
        self.assertLessEqual(traffic.spawn_interval, 0.25)

    def test_report_slices_long_runs_into_throughput_windows(self):
        report = MergeLab(seed=3).run(
            "roundabout-continuous-pressure",
            seconds=1.0,
            window_seconds=0.25,
            trace=False,
        )

        self.assertEqual(len(report.windows), 4)
        self.assertEqual(
            [(window.started_at, window.ended_at) for window in report.windows],
            [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)],
        )
        self.assertEqual(report.peak_active, max(
            window.peak_active for window in report.windows
        ))
        self.assertTrue(all(window.p99_tick_ms >= 0 for window in report.windows))
        self.assertEqual([window.tick_count for window in report.windows], [5, 5, 5, 5])

    def test_run_returns_frame_trace_and_safety_summary(self):
        report = MergeLab(seed=7).run("roundabout-simultaneous-entry", seconds=1.0)

        self.assertEqual(report.scenario, "roundabout-simultaneous-entry")
        self.assertGreater(len(report.frames), 0)
        self.assertIn("total", report.timing_summary_ms)
        self.assertGreaterEqual(report.overlap_pair_ticks, 0)

    def test_every_catalog_case_is_executable(self):
        lab = MergeLab(seed=3)
        for scenario in scenario_catalog():
            report = lab.run(scenario.name, seconds=0.2)
            self.assertGreater(len(report.frames), 0, scenario.name)

    def test_unknown_scenario_has_an_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "Available scenarios"):
            MergeLab().run("not-a-scenario", seconds=1.0)

    def test_soft_deadlock_resolution_restores_slip_lane_throughput(self):
        report = MergeLab(seed=7).run("slip-lane-short-link", seconds=90.0)
        tail_completions = sum(
            len(frame.completed_ids)
            for frame in report.frames
            if frame.simulated_time > 70.0
        )

        self.assertEqual(report.overlap_pair_ticks, 0, report.first_overlap)
        self.assertGreater(report.completed, 13)
        self.assertGreater(tail_completions, 0)
        self.assertTrue(any(
            frame.temporary_winner_id is not None for frame in report.frames
        ))

    def test_data_first_slip_lane_has_basic_safe_throughput(self):
        report = MergeLab(seed=7).run(
            "slip-lane-short-link", seconds=20.0, engine="data_first",
        )

        self.assertEqual(report.overlap_pair_ticks, 0, report.first_overlap)
        self.assertGreater(report.completed, 0)
