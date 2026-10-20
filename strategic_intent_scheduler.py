"""Experimental staggered scheduling for non-safety-critical traffic decisions.

This scheduler must never gate following, braking, occupancy, control-state,
merge-gap, or collision checks. It only determines when an independent
strategic decision is due for recomputation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite


@dataclass
class StrategicDecisionScheduler:
    interval_seconds: float = 1.0
    _next_due: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isfinite(self.interval_seconds) or self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be finite and positive")

    def due(self, vehicle_id: str, now: float, *, invalidate: bool = False) -> bool:
        """True when strategic work is due; caller recomputes before consuming it.

        A stable phase based on the vehicle identifier spreads first updates
        across the interval. New vehicles can request immediate work using
        invalidate=True. This method does not cache or reuse safety decisions.
        """
        if not isfinite(now):
            raise ValueError("now must be finite")
        if invalidate:
            self._next_due.pop(vehicle_id, None)
        next_due = self._next_due.get(vehicle_id)
        if next_due is None:
            # Initial work is always immediate: no vehicle runs without a route.
            return True
        return now >= next_due

    def completed(self, vehicle_id: str, now: float) -> None:
        """Mark a successfully recomputed strategic decision as current."""
        if not isfinite(now):
            raise ValueError("now must be finite")
        # Deterministic stable phase (not Python's randomized hash).
        phase = (sum((i + 1) * ord(ch) for i, ch in enumerate(vehicle_id)) % 997) / 997
        self._next_due[vehicle_id] = now + self.interval_seconds * (0.5 + phase)

    def forget(self, vehicle_id: str) -> None:
        self._next_due.pop(vehicle_id, None)

    def retain(self, active_vehicle_ids: set[str]) -> None:
        """Release state for exited/despawned vehicles."""
        self._next_due = {
            key: due for key, due in self._next_due.items()
            if key in active_vehicle_ids
        }
