"""Bounded, timing-only samples shared by simulation systems."""

from __future__ import annotations

import csv
import io
import json
from collections import deque
from dataclasses import dataclass
from math import ceil, isfinite
from statistics import mean, median
from types import MappingProxyType
from typing import Mapping


DEFAULT_PROFILE_HISTORY = 600


@dataclass(frozen=True)
class SimulationTickSample:
    """Timing and counts for one system update; it retains no entity objects."""

    tick: int
    system: str
    simulated_time: float
    elapsed_seconds: float
    entity_counts: Mapping[str, int]
    timings_ms: Mapping[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "tick": self.tick,
            "system": self.system,
            "simulated_time": self.simulated_time,
            "elapsed_seconds": self.elapsed_seconds,
            "entity_counts": dict(self.entity_counts),
            "timings_ms": dict(self.timings_ms),
        }


class SimulationProfiler:
    """Record bounded per-tick timings from any simulation system."""

    def __init__(self, max_samples: int = DEFAULT_PROFILE_HISTORY) -> None:
        if not isinstance(max_samples, int) or isinstance(max_samples, bool) or max_samples < 1:
            raise ValueError("Simulation profiler history must be a positive integer")
        self.max_samples = max_samples
        self._samples: deque[SimulationTickSample] = deque(maxlen=max_samples)
        self._next_tick = 0

    @property
    def samples(self) -> tuple[SimulationTickSample, ...]:
        return tuple(self._samples)

    @property
    def systems(self) -> tuple[str, ...]:
        return tuple(sorted({sample.system for sample in self._samples}))

    def samples_for(self, system: str) -> tuple[SimulationTickSample, ...]:
        return tuple(sample for sample in self._samples if sample.system == system)

    def record_tick(
        self,
        *,
        system: str,
        simulated_time: float,
        elapsed_seconds: float,
        entity_counts: Mapping[str, int],
        timings_ms: Mapping[str, float],
    ) -> SimulationTickSample:
        """Validate and retain one update without retaining caller-owned data."""
        system = system.strip() if isinstance(system, str) else ""
        if not system:
            raise ValueError("Simulation profiler samples need a system name")
        simulated_time = self._finite_nonnegative(simulated_time, "simulated time")
        elapsed_seconds = self._finite_nonnegative(elapsed_seconds, "elapsed seconds")

        copied_counts: dict[str, int] = {}
        for name, count in entity_counts.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Entity count names must be non-empty strings")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("Entity counts must be nonnegative integers")
            copied_counts[name] = count

        copied_timings: dict[str, float] = {}
        for name, duration in timings_ms.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Timing block names must be non-empty strings")
            copied_timings[name] = self._finite_nonnegative(
                duration, f"{name} timing",
            )

        self._next_tick += 1
        sample = SimulationTickSample(
            tick=self._next_tick,
            system=system,
            simulated_time=simulated_time,
            elapsed_seconds=elapsed_seconds,
            entity_counts=MappingProxyType(copied_counts),
            timings_ms=MappingProxyType(copied_timings),
        )
        self._samples.append(sample)
        return sample

    def statistics(
        self, system: str | None = None,
    ) -> dict[str, dict[str, float]] | dict[str, dict[str, dict[str, float]]]:
        """Return per-block mean, median, p95, p99, and maximum timings."""
        if system is None:
            return {name: self.statistics(name) for name in self.systems}

        samples = self.samples_for(system)
        block_names = sorted({
            block for sample in samples for block in sample.timings_ms
        })
        return {
            block: self._summarize([
                sample.timings_ms.get(block, 0.0) for sample in samples
            ])
            for block in block_names
        }

    def as_dict(self) -> dict[str, object]:
        """Return JSON-ready samples and aggregates for stress-test reports."""
        return {
            "max_samples": self.max_samples,
            "sample_count": len(self._samples),
            "samples": [sample.as_dict() for sample in self._samples],
            "statistics": self.statistics(),
        }

    def to_csv(self) -> str:
        """Return a wide CSV with one row per retained system tick."""
        phase_names = sorted({
            phase for sample in self._samples for phase in sample.timings_ms
        })
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow((
            "tick", "system", "simulated_time_seconds", "elapsed_seconds",
            "entity_counts_json", *(f"{phase}_ms" for phase in phase_names),
        ))
        for sample in self._samples:
            writer.writerow((
                sample.tick,
                sample.system,
                sample.simulated_time,
                sample.elapsed_seconds,
                json.dumps(dict(sample.entity_counts), sort_keys=True),
                *(sample.timings_ms.get(phase, "") for phase in phase_names),
            ))
        return output.getvalue()

    @classmethod
    def _finite_nonnegative(cls, value: float, label: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{label.capitalize()} must be finite and nonnegative")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label.capitalize()} must be finite and nonnegative") from error
        if not isfinite(number) or number < 0:
            raise ValueError(f"{label.capitalize()} must be finite and nonnegative")
        return number

    @classmethod
    def _summarize(cls, values: list[float]) -> dict[str, float]:
        if not values:
            return {
                "mean_ms": 0.0,
                "median_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_ms": 0.0,
            }
        ordered = sorted(values)
        p95_index = max(0, ceil(0.95 * len(ordered)) - 1)
        p99_index = max(0, ceil(0.99 * len(ordered)) - 1)
        return {
            "mean_ms": round(mean(values), 4),
            "median_ms": round(median(values), 4),
            "p95_ms": round(ordered[p95_index], 4),
            "p99_ms": round(ordered[p99_index], 4),
            "max_ms": round(ordered[-1], 4),
        }
