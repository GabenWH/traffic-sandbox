"""Tests for UI-frame performance calculations."""

import unittest

from ui.dashboards import frame_statistics


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


if __name__ == "__main__":
    unittest.main()
