"""Frame-by-frame facts captured from the routed traffic simulator.

This is deliberately a notebook, not another driving system.  The simulator
hands it observations and decisions after it has made them, so enabling a trace
cannot change priority, gap acceptance, or the order in which cars move.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CarFrame:
    """One car's intent and resulting motion during one simulation frame."""

    car_id: str
    state: str
    wait_reason: str
    distance_before: float
    distance_after: float
    speed_before: float
    speed_after: float
    desired_speed: float
    position_after: tuple[float, float]
    movement_id: str | None
    movement_role: str | None
    has_priority: bool
    has_claim: bool
    merge_vehicle_ids: tuple[str, ...]
    reservation_count: int


@dataclass(frozen=True)
class FrameTrace:
    """A complete tick: simulated time, work timing, and every car result."""

    index: int
    simulated_time: float
    elapsed_seconds: float
    car_count: int
    completed_ids: tuple[str, ...]
    timings_ms: dict[str, float]
    cars: tuple[CarFrame, ...]
    deadlock_stall_seconds: float = 0.0
    temporary_winner_id: str | None = None
    hard_gridlock: bool = False


class TrafficDebugger:
    """Keep a bounded history of routed-traffic frames for inspection/export."""

    def __init__(self, max_frames: int = 600) -> None:
        if max_frames < 1:
            raise ValueError("Traffic debugger needs room for at least one frame")
        self.max_frames = max_frames
        self.frames: deque[FrameTrace] = deque(maxlen=max_frames)
        self._cars: list[CarFrame] = []
        self._index = 0

    @property
    def latest_frame(self) -> FrameTrace | None:
        return self.frames[-1] if self.frames else None

    def begin_frame(self) -> None:
        self._cars = []

    def record_car(
        self,
        car: Any,
        *,
        distance_before: float,
        speed_before: float,
        decision: Any,
        movement: Any,
        has_priority: bool,
        has_claim: bool,
        merge_observation: Any,
    ) -> None:
        """Record the resolved result, after the simulator has moved ``car``."""
        self._cars.append(CarFrame(
            car_id=car.id,
            state=car.brain.state.value,
            wait_reason=car.brain.wait_reason or "",
            distance_before=distance_before,
            distance_after=car.distance,
            speed_before=speed_before,
            speed_after=car.speed,
            desired_speed=decision.desired_speed,
            position_after=car.position,
            movement_id=movement[2].id if movement is not None else None,
            movement_role=(movement[2].roundabout_role if movement is not None else None),
            has_priority=has_priority,
            has_claim=has_claim,
            merge_vehicle_ids=(tuple(vehicle.id for vehicle in merge_observation.vehicles)
                               if merge_observation is not None else ()),
            reservation_count=(len(merge_observation.reservations)
                               if merge_observation is not None else 0),
        ))

    def end_frame(
        self,
        *,
        simulated_time: float,
        elapsed_seconds: float,
        car_count: int,
        completed_ids: list[str],
        timings_ms: dict[str, float],
        deadlock_stall_seconds: float = 0.0,
        temporary_winner_id: str | None = None,
        hard_gridlock: bool = False,
    ) -> None:
        self._index += 1
        self.frames.append(FrameTrace(
            index=self._index,
            simulated_time=simulated_time,
            elapsed_seconds=elapsed_seconds,
            car_count=car_count,
            completed_ids=tuple(completed_ids),
            timings_ms={name: round(value, 4) for name, value in timings_ms.items()},
            cars=tuple(self._cars),
            deadlock_stall_seconds=round(deadlock_stall_seconds, 3),
            temporary_winner_id=temporary_winner_id,
            hard_gridlock=hard_gridlock,
        ))

    def as_dict(self) -> dict[str, object]:
        """Return JSON-ready data; callers decide whether and where to save it."""
        return {"frames": [asdict(frame) for frame in self.frames]}

    def latest_summary(self) -> str | None:
        """Compact UI text for the live debugger window."""
        frame = self.latest_frame
        if frame is None:
            return None
        total = frame.timings_ms.get("total", 0.0)
        decision = frame.timings_ms.get("decision", 0.0)
        deadlock = ""
        if frame.temporary_winner_id is not None:
            deadlock = f" deadlock-winner={frame.temporary_winner_id}"
        elif frame.hard_gridlock:
            deadlock = " hard-gridlock"
        elif frame.deadlock_stall_seconds > 0:
            deadlock = f" stalled={frame.deadlock_stall_seconds:.1f}s"
        return (
            f"TRACE frame={frame.index} sim={frame.simulated_time:.2f}s "
            f"cars={frame.car_count} total={total:.2f}ms decision={decision:.2f}ms"
            f"{deadlock}"
        )
