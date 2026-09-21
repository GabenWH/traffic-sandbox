"""Reproducible aggregate comparison of traffic update engines."""

from __future__ import annotations

from math import ceil
from statistics import median

from merge_lab import MergeLab, MergeLabReport


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def compare_traffic_engines(
    scenario: str,
    *,
    seeds: tuple[int, ...] = (3, 7, 42),
    seconds: float = 120.0,
    repeats: int = 3,
    dt: float = 0.05,
    window_seconds: float = 60.0,
) -> dict[str, object]:
    """Run both engines under identical seeds and summarize useful gates."""
    if not seeds:
        raise ValueError("At least one seed is required")
    if repeats < 1:
        raise ValueError("Repeats must be positive")

    runs: dict[str, list[MergeLabReport]] = {"legacy": [], "data_first": []}
    run_order = []
    for seed_index, seed in enumerate(seeds):
        for repeat_index in range(repeats):
            engines = (
                ("legacy", "data_first")
                if (seed_index + repeat_index) % 2 == 0
                else ("data_first", "legacy")
            )
            run_order.append({
                "seed": seed,
                "repeat": repeat_index + 1,
                "engines": list(engines),
            })
            for engine in engines:
                runs[engine].append(MergeLab(seed).run(
                    scenario,
                    seconds=seconds,
                    dt=dt,
                    engine=engine,
                    trace=False,
                    window_seconds=window_seconds,
                ))

    summaries: dict[str, dict[str, object]] = {}
    for engine, reports in runs.items():
        tick_times = [value for report in reports for value in report.tick_times_ms]
        deterministic = None if repeats < 2 else all(
            len({report.state_digest for report in reports if report.seed == seed}) == 1
            for seed in seeds
        )
        summaries[engine] = {
            "runs": len(reports),
            "completed": round(sum(report.completed for report in reports) / len(reports), 3),
            "remaining": round(sum(report.remaining for report in reports) / len(reports), 3),
            "overlap_pair_ticks": sum(report.overlap_pair_ticks for report in reports),
            "hard_gridlock_seconds": round(
                sum(report.hard_gridlock_seconds for report in reports), 3,
            ),
            "median_tick_ms": round(median(tick_times), 4),
            "p95_tick_ms": round(_percentile(tick_times, 0.95), 4),
            "p99_tick_ms": round(_percentile(tick_times, 0.99), 4),
            "peak_active": max(report.peak_active for report in reports),
            "deterministic": deterministic,
            "state_digests": {
                str(seed): next(
                    report.state_digest for report in reports if report.seed == seed
                )
                for seed in seeds
            },
            "windows": [
                {
                    "started_at": reference.started_at,
                    "ended_at": reference.ended_at,
                    "mean_tick_count": round(sum(
                        report.windows[index].tick_count for report in reports
                    ) / len(reports), 3),
                    "mean_completed": round(sum(
                        report.windows[index].completed for report in reports
                    ) / len(reports), 3),
                    "mean_active": round(sum(
                        report.windows[index].mean_active for report in reports
                    ) / len(reports), 3),
                    "max_peak_active": max(
                        report.windows[index].peak_active for report in reports
                    ),
                    "mean_overlap_pair_ticks": round(sum(
                        report.windows[index].overlap_pair_ticks for report in reports
                    ) / len(reports), 3),
                    "mean_hard_gridlock_seconds": round(sum(
                        report.windows[index].hard_gridlock_seconds for report in reports
                    ) / len(reports), 3),
                    "mean_temporary_winner_ticks": round(sum(
                        report.windows[index].temporary_winner_ticks for report in reports
                    ) / len(reports), 3),
                    "mean_median_tick_ms": round(sum(
                        report.windows[index].median_tick_ms for report in reports
                    ) / len(reports), 4),
                    "mean_p95_tick_ms": round(sum(
                        report.windows[index].p95_tick_ms for report in reports
                    ) / len(reports), 4),
                    "mean_p99_tick_ms": round(sum(
                        report.windows[index].p99_tick_ms for report in reports
                    ) / len(reports), 4),
                }
                for index, reference in enumerate(reports[0].windows)
            ],
        }

    legacy = summaries["legacy"]
    data_first = summaries["data_first"]
    legacy_completed = float(legacy["completed"])
    throughput_ratio = (
        float(data_first["completed"]) / legacy_completed
        if legacy_completed else 1.0
    )
    legacy_median = float(legacy["median_tick_ms"])
    speedup = (
        1.0 - float(data_first["median_tick_ms"]) / legacy_median
        if legacy_median else 0.0
    )
    performance_counterbalanced = repeats >= 2
    return {
        "scenario": scenario,
        "seeds": list(seeds),
        "seconds": seconds,
        "repeats": repeats,
        "dt": dt,
        "window_seconds": window_seconds,
        "run_order": run_order,
        "performance_counterbalanced": performance_counterbalanced,
        "engines": summaries,
        "comparison": {
            "throughput_ratio": round(throughput_ratio, 4),
            "median_tick_reduction": round(speedup, 4),
        },
        "gates": {
            "zero_overlaps": data_first["overlap_pair_ticks"] == 0,
            "deterministic": data_first["deterministic"],
            "throughput_within_10_percent": throughput_ratio >= 0.9,
            "median_tick_at_least_25_percent_faster": (
                speedup >= 0.25 if performance_counterbalanced else None
            ),
        },
    }
