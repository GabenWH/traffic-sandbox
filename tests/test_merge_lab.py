"""The merge lab keeps difficult traffic states reproducible."""

import unittest

from merge_lab import MergeLab, scenario_catalog


class MergeLabTests(unittest.TestCase):
    def test_catalog_covers_clear_competing_queued_and_short_link_cases(self):
        names = {scenario.name for scenario in scenario_catalog()}
        self.assertTrue({
            "roundabout-clear-entry",
            "roundabout-circulating-leader",
            "roundabout-simultaneous-entry",
            "roundabout-queued-ring",
            "roundabout-continuous-pressure",
            "slip-lane-short-link",
        }.issubset(names))

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
