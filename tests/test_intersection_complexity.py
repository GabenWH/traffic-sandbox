"""Checks for the reproducible intersection complexity comparison harness."""

import unittest

from intersection_complexity import (
    build_intersection_city,
    movement_conflict_catalog,
    compare_intersection_complexity,
    make_demand_schedule,
    run_intersection_mode,
)


class IntersectionComplexityTests(unittest.TestCase):
    def test_builder_uses_three_real_intersection_policies(self):
        unsignalized = build_intersection_city("unsignalized")
        four_way = build_intersection_city("four_way_stop")
        roundabout = build_intersection_city("roundabout")

        self.assertTrue(all(
            item.control.kind.value == "uncontrolled"
            for item in unsignalized.standard_intersections[0].lane_connections
        ))
        self.assertTrue(four_way.standard_intersections[0].is_all_way_stop)
        self.assertEqual(roundabout.standard_intersections[0].kind.value, "roundabout")
        self.assertGreater(
            len(roundabout.standard_intersections[0].lane_connections),
            len(unsignalized.standard_intersections[0].lane_connections),
        )
        movements, conflicts = movement_conflict_catalog(roundabout)
        self.assertEqual(len(movements), 8)
        self.assertEqual(sum(map(len, conflicts.values())) // 2, 4)

    def test_seeded_demand_schedule_is_stable_and_uses_all_approaches(self):
        first = make_demand_schedule(seed=23, seconds=4.0, interval=1.0, dt=0.05)
        second = make_demand_schedule(seed=23, seconds=4.0, interval=1.0, dt=0.05)

        self.assertEqual(first, second)
        self.assertEqual({item.source_index for item in first}, {0, 1, 2, 3})
        self.assertTrue(all(item.source_index != item.destination_index for item in first))

    def test_short_run_reports_runtime_and_traffic_outcomes(self):
        report = run_intersection_mode(
            "unsignalized", seed=7, seconds=0.1, interval=10.0,
            dt=0.05, max_cars=10,
        )

        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["admitted"], 1)
        self.assertEqual(report["ticks"], 2)
        self.assertGreater(report["median_tick_ms"], 0)
        self.assertIn("maximum_approach_queue", report)
        self.assertIn("hard_gridlock_seconds", report)
        self.assertIn("sub_1_5s_ttc_proxy_pair_ticks", report)
        self.assertIn("pet_proxy_below_1_5s", report)

    def test_comparison_can_run_one_load_level_with_paired_schedules(self):
        comparison = compare_intersection_complexity(
            seeds=(3,), seconds=0.1, dt=0.05, max_cars=5,
            demand_levels=("high",),
        )

        self.assertEqual(len(comparison["runs"]), 3)
        self.assertEqual(set(comparison["aggregates"]), {"high"})
        self.assertEqual(len({run["schedule_signature"] for run in comparison["runs"]}), 1)
        self.assertEqual(set(comparison["runtime_scaling"]), {
            "unsignalized", "four_way_stop", "roundabout",
        })
        roundabout = comparison["aggregates"]["high"]["roundabout"]
        self.assertEqual(roundabout["mean_conflicting_movement_pairs"], 4.0)
        self.assertIn("median_maximum_total_queue", roundabout)
        self.assertIn("total_pet_proxy_overlapping_movement_pairs", roundabout)


if __name__ == "__main__":
    unittest.main()
