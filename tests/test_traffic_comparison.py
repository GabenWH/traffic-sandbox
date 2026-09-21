"""Legacy and data-first traffic engines can be compared reproducibly."""

import unittest

from traffic_comparison import compare_traffic_engines


class TrafficComparisonTests(unittest.TestCase):
    def test_comparison_reports_safety_throughput_timing_and_determinism(self):
        comparison = compare_traffic_engines(
            "roundabout-clear-entry",
            seeds=(3,),
            seconds=0.2,
            repeats=2,
            window_seconds=0.1,
        )

        self.assertEqual(set(comparison["engines"]), {"legacy", "data_first"})
        self.assertEqual(
            [run["engines"] for run in comparison["run_order"]],
            [["legacy", "data_first"], ["data_first", "legacy"]],
        )
        self.assertTrue(comparison["performance_counterbalanced"])
        for result in comparison["engines"].values():
            self.assertIn("median_tick_ms", result)
            self.assertIn("p95_tick_ms", result)
            self.assertIn("p99_tick_ms", result)
            self.assertIn("peak_active", result)
            self.assertIn("completed", result)
            self.assertIn("overlap_pair_ticks", result)
            self.assertTrue(result["deterministic"])
            self.assertEqual(len(result["windows"]), 2)
            self.assertIn("mean_completed", result["windows"][0])
            self.assertIn("mean_hard_gridlock_seconds", result["windows"][0])
            self.assertIn("mean_p99_tick_ms", result["windows"][0])

    def test_single_run_does_not_claim_determinism(self):
        comparison = compare_traffic_engines(
            "roundabout-clear-entry",
            seeds=(3,),
            seconds=0.1,
            repeats=1,
        )

        self.assertIsNone(comparison["engines"]["legacy"]["deterministic"])
        self.assertIsNone(comparison["engines"]["data_first"]["deterministic"])
        self.assertIsNone(comparison["gates"]["deterministic"])
        self.assertFalse(comparison["performance_counterbalanced"])
        self.assertIsNone(
            comparison["gates"]["median_tick_at_least_25_percent_faster"]
        )


if __name__ == "__main__":
    unittest.main()
