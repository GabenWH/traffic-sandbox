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
        )

        self.assertEqual(set(comparison["engines"]), {"legacy", "data_first"})
        for result in comparison["engines"].values():
            self.assertIn("median_tick_ms", result)
            self.assertIn("p95_tick_ms", result)
            self.assertIn("completed", result)
            self.assertIn("overlap_pair_ticks", result)
            self.assertTrue(result["deterministic"])


if __name__ == "__main__":
    unittest.main()
