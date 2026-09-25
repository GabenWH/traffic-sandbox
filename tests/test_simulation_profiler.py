"""Contracts for bounded, reusable simulation timing samples."""

import csv
import io
import json
import unittest

from simulation_profiler import SimulationProfiler


class SimulationProfilerTests(unittest.TestCase):
    def test_samples_are_bounded_and_tick_ids_keep_increasing(self) -> None:
        profiler = SimulationProfiler(max_samples=2)

        for tick in range(3):
            profiler.record_tick(
                system="routed_traffic",
                simulated_time=float(tick),
                elapsed_seconds=0.05,
                entity_counts={"cars": tick},
                timings_ms={"total": tick + 1.0},
            )

        self.assertEqual([sample.tick for sample in profiler.samples], [2, 3])
        self.assertEqual(profiler.samples[0].entity_counts["cars"], 1)

    def test_statistics_use_nearest_rank_percentiles(self) -> None:
        profiler = SimulationProfiler()
        for tick, value in enumerate((1.0, 2.0, 3.0, 4.0), start=1):
            profiler.record_tick(
                system="routed_traffic",
                simulated_time=float(tick),
                elapsed_seconds=0.05,
                entity_counts={"cars": 2},
                timings_ms={"intent_generation": value, "total": value + 1},
            )

        stats = profiler.statistics("routed_traffic")["intent_generation"]

        self.assertEqual(stats, {
            "mean_ms": 2.5,
            "median_ms": 2.5,
            "p95_ms": 4.0,
            "p99_ms": 4.0,
            "max_ms": 4.0,
        })

    def test_json_and_csv_export_keep_system_counts_and_phase_values(self) -> None:
        profiler = SimulationProfiler()
        profiler.record_tick(
            system="construction",
            simulated_time=12.5,
            elapsed_seconds=0.05,
            entity_counts={"construction_vehicles": 2, "cars": 7},
            timings_ms={"total": 3.5, "work_assignment": 0.4},
        )

        exported = json.loads(json.dumps(profiler.as_dict()))
        rows = list(csv.DictReader(io.StringIO(profiler.to_csv())))

        self.assertEqual(exported["samples"][0]["system"], "construction")
        self.assertEqual(exported["samples"][0]["entity_counts"], {
            "cars": 7,
            "construction_vehicles": 2,
        })
        self.assertEqual(exported["statistics"]["construction"]["work_assignment"]["mean_ms"], 0.4)
        self.assertEqual(rows[0]["system"], "construction")
        self.assertEqual(json.loads(rows[0]["entity_counts_json"]), {
            "cars": 7,
            "construction_vehicles": 2,
        })
        self.assertEqual(float(rows[0]["work_assignment_ms"]), 0.4)

    def test_invalid_sample_data_is_rejected_without_recording(self) -> None:
        profiler = SimulationProfiler()

        with self.assertRaises(ValueError):
            profiler.record_tick(
                system="routed_traffic",
                simulated_time=0.0,
                elapsed_seconds=0.05,
                entity_counts={"cars": -1},
                timings_ms={"total": 1.0},
            )
        with self.assertRaises(ValueError):
            profiler.record_tick(
                system="routed_traffic",
                simulated_time=0.0,
                elapsed_seconds=0.05,
                entity_counts={"cars": 1},
                timings_ms={"total": float("nan")},
            )
        self.assertEqual(profiler.samples, ())


if __name__ == "__main__":
    unittest.main()
