"""Runtime observations and reservations for intersection controls."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from math import atan2, floor, isfinite, pi, ulp

from models import LaneConnection, ControlType


class SignalAspect(StrEnum):
    """The vehicle-entry aspect currently shown to a movement group."""

    GREEN = "green"
    YELLOW = "yellow"
    ALL_RED = "all_red"


@dataclass(frozen=True)
class SignalPhase:
    """A fixed green interval followed by yellow and all-red clearance."""

    green_seconds: float
    movement_ids: frozenset[str]
    yellow_seconds: float = 3.0
    all_red_seconds: float = 1.0
    name: str = ""

    def __post_init__(self) -> None:
        if not isfinite(self.green_seconds) or self.green_seconds <= 0:
            raise ValueError("Signal green time must be finite and positive")
        if not isfinite(self.yellow_seconds) or self.yellow_seconds < 0:
            raise ValueError("Signal yellow time must be finite and nonnegative")
        if not isfinite(self.all_red_seconds) or self.all_red_seconds < 0:
            raise ValueError("Signal all-red time must be finite and nonnegative")
        if isinstance(self.movement_ids, str):
            raise ValueError("Signal movement IDs must be supplied as a collection")
        try:
            movement_ids = frozenset(self.movement_ids)
        except TypeError as error:
            raise ValueError("Signal movement IDs must be an iterable of IDs") from error
        if any(not isinstance(item, str) or not item for item in movement_ids):
            raise ValueError("Signal movement IDs must be nonempty strings")
        object.__setattr__(self, "movement_ids", movement_ids)


@dataclass(frozen=True)
class SignalPlan:
    """A cyclic sequence of fixed-time movement phases."""

    phases: tuple[SignalPhase, ...]

    def __post_init__(self) -> None:
        phases = tuple(self.phases)
        if not phases or any(not isinstance(phase, SignalPhase) for phase in phases):
            raise ValueError("A signal plan needs at least one valid phase")
        cycle_seconds = sum(
            phase.green_seconds + phase.yellow_seconds + phase.all_red_seconds
            for phase in phases
        )
        if not isfinite(cycle_seconds) or cycle_seconds <= 0:
            raise ValueError("Signal cycle time must be finite and positive")
        object.__setattr__(self, "phases", phases)

    @property
    def cycle_seconds(self) -> float:
        return sum(
            phase.green_seconds + phase.yellow_seconds + phase.all_red_seconds
            for phase in self.phases
        )


@dataclass(frozen=True)
class SignalPlanChange:
    """Request a plan, applied after the active phase finishes clearance."""

    at_seconds: float
    plan: SignalPlan

    def __post_init__(self) -> None:
        if not isfinite(self.at_seconds) or self.at_seconds < 0:
            raise ValueError("Signal plan change time must be finite and nonnegative")
        if not isinstance(self.plan, SignalPlan):
            raise ValueError("Signal plan changes need a valid plan")


@dataclass(frozen=True)
class SignalState:
    aspect: SignalAspect
    phase_index: int
    movement_ids: frozenset[str]


@dataclass(frozen=True)
class FixedTimeSignalController:
    """Cycle fixed-time plans using simulation time, with optional plan changes.

    A scheduled request starts phase zero at the next completed phase clearance.
    Vehicles physically crossing keep clearing; approaching vehicles receive no
    reservation that could outlive their light.
    """

    plan: SignalPlan
    schedule: tuple[SignalPlanChange, ...] = ()
    _effective_schedule: tuple[SignalPlanChange, ...] = field(
        default=(), init=False, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.plan, SignalPlan):
            raise ValueError("A fixed-time controller needs a valid plan")
        schedule = tuple(self.schedule)
        if any(not isinstance(item, SignalPlanChange) for item in schedule):
            raise ValueError("Signal schedule entries must be valid plan changes")
        times = [item.at_seconds for item in schedule]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("Signal plan changes must be in strictly increasing time order")
        object.__setattr__(self, "schedule", schedule)
        effective = []
        for change in schedule:
            if effective and change.at_seconds <= effective[-1].at_seconds:
                # The previous request is still pending at this clearance.
                effective[-1] = SignalPlanChange(effective[-1].at_seconds, change.plan)
                continue
            active = effective[-1].plan if effective else self.plan
            started = effective[-1].at_seconds if effective else 0.0
            boundary = _next_phase_clearance(active, started, change.at_seconds)
            effective.append(SignalPlanChange(boundary, change.plan))
        object.__setattr__(self, "_effective_schedule", tuple(effective))

    def state_at(self, elapsed_seconds: float) -> SignalState:
        """Return the active phase state at nonnegative simulation time."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Signal time must be finite and nonnegative")
        plan = self.plan
        plan_started = 0.0
        for change in self._effective_schedule:
            if _before_signal_boundary(elapsed_seconds, change.at_seconds):
                break
            plan = change.plan
            plan_started = change.at_seconds

        cycle_start = plan_started + floor((elapsed_seconds - plan_started) / plan.cycle_seconds) * plan.cycle_seconds
        boundary = cycle_start
        for index, phase in enumerate(plan.phases):
            boundary += phase.green_seconds
            if _before_signal_boundary(elapsed_seconds, boundary):
                return SignalState(SignalAspect.GREEN, index, phase.movement_ids)
            boundary += phase.yellow_seconds
            if _before_signal_boundary(elapsed_seconds, boundary):
                return SignalState(SignalAspect.YELLOW, index, phase.movement_ids)
            boundary += phase.all_red_seconds
            if _before_signal_boundary(elapsed_seconds, boundary):
                return SignalState(SignalAspect.ALL_RED, index, frozenset())
        first = plan.phases[0]
        return SignalState(SignalAspect.GREEN, 0, first.movement_ids)

    def is_green(self, movement_id: str, elapsed_seconds: float) -> bool:
        state = self.state_at(elapsed_seconds)
        return state.aspect is SignalAspect.GREEN and movement_id in state.movement_ids

    def next_boundary_after(self, elapsed_seconds: float) -> float:
        """Next aspect or effective plan event, for exact integration splits."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Signal time must be finite and nonnegative")
        plan, started, pending = self.plan, 0.0, float('inf')
        for change in self._effective_schedule:
            if _before_signal_boundary(elapsed_seconds, change.at_seconds):
                pending = change.at_seconds
                break
            plan, started = change.plan, change.at_seconds
        cycle_start = started + floor((elapsed_seconds - started) / plan.cycle_seconds) * plan.cycle_seconds
        for offset in (0, 1):
            boundary = cycle_start + offset * plan.cycle_seconds
            for phase in plan.phases:
                for duration in (phase.green_seconds, phase.yellow_seconds, phase.all_red_seconds):
                    boundary += duration
                    if _before_signal_boundary(elapsed_seconds, boundary):
                        return min(boundary, pending)
        raise ArithmeticError("No representable next signal event")


def _before_signal_boundary(elapsed: float, boundary: float) -> bool:
    # Decimal durations accumulate a few ULPs over repeated cycles. Treat the
    # same representable event consistently in aspect lookup and subdivision.
    return elapsed < boundary and boundary - elapsed > 4 * max(ulp(elapsed), ulp(boundary))


def _next_phase_clearance(plan: SignalPlan, started: float, requested: float) -> float:
    """Apply a request only at an existing end-of-clearance boundary."""
    if requested == started:
        return requested
    cycle_start = started + floor((requested - started) / plan.cycle_seconds) * plan.cycle_seconds
    if cycle_start == requested:
        return requested
    boundary = cycle_start
    for phase in plan.phases:
        boundary += phase.green_seconds + phase.yellow_seconds + phase.all_red_seconds
        if boundary >= requested:
            return boundary
    return cycle_start + plan.cycle_seconds


@dataclass(frozen=True)
class StopArrival:
    car_id: str
    connection: LaneConnection
    stopped_at: float


@dataclass
class AllWayStopCoordinator:
    """Arbitrate claims while leaving movement decisions to individual cars."""

    arrivals: dict[str, StopArrival] = field(default_factory=dict)
    claims: dict[tuple[str, str], LaneConnection] = field(default_factory=dict)
    signal_occupants: dict[tuple[str, str], LaneConnection] = field(default_factory=dict)

    def observe_signal_occupants(self, occupants) -> None:
        """Observe actual bodies, never reservations or future permissions."""
        self.signal_occupants = {(owner, connection.id): connection
                                 for owner, connection in occupants}

    def can_enter_signal(self, car_id: str, connection: LaneConnection) -> bool:
        for (owner, _), occupied in self.signal_occupants.items():
            if owner == car_id or occupied.intersection_id != connection.intersection_id:
                continue
            # Same-approach cars follow one another through green normally.
            if occupied.source_output == connection.source_output:
                continue
            if movements_conflict(connection, occupied):
                return False
        return not self._blocked_by_reservation(car_id, connection)

    def _blocked_by_reservation(self, car_id, connection):
        return any(owner != car_id and movements_conflict(connection, claimed)
                   for (owner, _), claimed in self.claims.items()
                   if claimed.intersection_id == connection.intersection_id)

    def observe_stop(
        self, car_id: str, connection: LaneConnection, stopped_at: float,
    ) -> None:
        self.arrivals.setdefault(car_id, StopArrival(car_id, connection, stopped_at))

    def observe_approach(self, car_id, connection, arrival_time):
        """Register an uncontrolled/yield arrival without requiring a stop.

        Freeze the first estimated arrival time. Recomputing it while a car
        waits would continually move that car to the back of the queue.
        """
        self.arrivals.setdefault(car_id, StopArrival(car_id, connection, arrival_time))

    def retain_arrivals(self, eligible: dict[str, LaneConnection]) -> None:
        """Drop queue followers and distant approaches without releasing claims."""
        for car_id, arrival in tuple(self.arrivals.items()):
            if eligible.get(car_id) is not arrival.connection:
                self.arrivals.pop(car_id, None)

    def _blocked_by_claim(self, car_id, connection):
        return any(
            owner != car_id and claimed.intersection_id == connection.intersection_id
            and movements_conflict(connection, claimed)
            for (owner, _), claimed in (*self.claims.items(), *self.signal_occupants.items())
        )

    def can_claim(self, car_id: str, connection: LaneConnection) -> bool:
        arrival = self.arrivals.get(car_id)
        if arrival is None or arrival.connection is not connection:
            return False
        if self._blocked_by_claim(car_id, connection):
            return False
        waiting = [item for item in self.arrivals.values()
                   if item.connection.intersection_id == connection.intersection_id]
        if connection.control.kind is ControlType.STOP:
            # Independent paths may enter together after completing their stop.
            conflicting = (item for item in waiting
                           if movements_conflict(connection, item.connection))
            return min(conflicting, key=self._priority_key).car_id == car_id
        # Build everyone's "I must yield to this driver" relationships. Looking
        # only at our own conflicts misses a four-way cycle: opposite straight
        # paths are compatible, yet each driver still waits for one on the right.
        dependencies = {}
        for item in waiting:
            dependencies[item.car_id] = [
                other.car_id for other in waiting
                if other.car_id != item.car_id
                and movements_conflict(item.connection, other.connection)
                and (other.stopped_at < item.stopped_at - 0.75
                     or (abs(other.stopped_at - item.stopped_at) <= 0.75
                         and yields_to(item, other)))
            ]
        if not dependencies[car_id]:
            return True
        if not any(not blockers for blockers in dependencies.values()):
            # Everyone is waiting for someone else. Let one stable winner go;
            # its claim still blocks conflicting traffic until its rear clears.
            return min(waiting, key=self._priority_key).car_id == car_id
        return False

    def can_approach(self, car_id: str, connection: LaneConnection) -> bool:
        """Keep rolling toward a clear junction without joining its queue."""
        return not self._blocked_by_claim(car_id, connection) and not any(
            item.car_id != car_id
            and item.connection.intersection_id == connection.intersection_id
            and movements_conflict(connection, item.connection)
            for item in self.arrivals.values()
        )

    def can_enter_merge(self, car_id, connection):
        """Only protect against another car physically using this entrance.

        A yield merge has no first-arrival queue across the entire junction.
        The driver's brain assesses through traffic. Unrelated entrances can
        operate together, and circulating cars do not wait for entering cars.
        """
        return not self._blocked_by_claim(car_id, connection)

    def claim_merge(self, car_id, connection):
        if not self.can_enter_merge(car_id, connection):
            return False
        self.claims[(car_id, connection.id)] = connection
        self.arrivals.pop(car_id, None)
        return True

    def claim(self, car_id: str, connection: LaneConnection) -> bool:
        if not self.can_claim(car_id, connection):
            return False
        self.claims[(car_id, connection.id)] = connection
        self.arrivals.pop(car_id, None)
        return True

    def claim_temporary_winner(self, car_id: str, connection: LaneConnection) -> bool:
        """Break waiting-order hesitation without overriding active traffic.

        An existing claim means another vehicle is already committed, so it is
        never displaced.  Only the queue/arrival ordering is bypassed.
        """
        if not self.can_claim_temporary_winner(car_id, connection):
            return False
        self.claims[(car_id, connection.id)] = connection
        self.arrivals.pop(car_id, None)
        return True

    def can_claim_temporary_winner(self, car_id: str, connection: LaneConnection) -> bool:
        """A soft-deadlock winner may not displace committed traffic."""
        return not self._blocked_by_claim(car_id, connection)

    def release(self, car_id: str, connection: LaneConnection | None = None) -> None:
        # A car can occupy two close junctions at once. Clearing the first
        # must not erase its permission for the second.
        for key in list(self.claims):
            if key[0] == car_id and (connection is None or self.claims[key] is connection):
                del self.claims[key]

    def forget_car(self, car_id: str) -> None:
        self.arrivals.pop(car_id, None)
        self.release(car_id)
        for key in tuple(self.signal_occupants):
            if key[0] == car_id:
                del self.signal_occupants[key]

    def has_claim(self, car_id: str, connection: LaneConnection) -> bool:
        return self.claims.get((car_id, connection.id)) is connection

    @staticmethod
    def _priority_key(arrival: StopArrival) -> tuple[float, float, str]:
        heading = arrival.connection.source_output.heading
        # Clockwise compass ordering beginning at north, then stable car ID.
        clockwise = (atan2(heading[0], -heading[1]) + 2 * pi) % (2 * pi)
        return (round(arrival.stopped_at, 6), clockwise, arrival.car_id)

    def priority_key(self, car_id: str) -> tuple[float, float, str] | None:
        """Expose the coordinator's stable order for batch claim resolution."""
        arrival = self.arrivals.get(car_id)
        return self._priority_key(arrival) if arrival is not None else None


def movements_conflict(a: LaneConnection, b: LaneConnection) -> bool:
    """Would the two vehicle paths cross, join, or pass too close together?

    Comparing the paths lets opposite straight-through traffic move together.
    A shared destination is a merge, even when the drawn curves only meet at
    their last point. Eight feet covers two six-foot cars plus a small margin.
    """
    group = a._conflict_group
    if group is not None and group is b._conflict_group:
        return a._conflict_row[b._conflict_index]
    # Standalone movements and pairs spanning different network generations
    # have no shared table; preserve the original geometric calculation.
    return _calculate_movement_conflict(a, b)


def cache_movement_conflicts(connections: Sequence[LaneConnection]) -> None:
    """Compile one intersection's symmetric conflict table after road edits.

    Rows live on the movements, so replacing a network also replaces its
    cache. A fresh token prevents old routes from indexing a new table.
    """
    group = object()
    rows = [[True] * len(connections) for _ in connections]
    for i, a in enumerate(connections):
        for j in range(i + 1, len(connections)):
            conflict = _calculate_movement_conflict(a, connections[j])
            rows[i][j] = rows[j][i] = conflict
    for i, connection in enumerate(connections):
        connection._conflict_group = group
        connection._conflict_index = i
        connection._conflict_row = tuple(rows[i])


def _calculate_movement_conflict(a: LaneConnection, b: LaneConnection) -> bool:
    if a.intersection_id != b.intersection_id:
        return False
    if a.source_output == b.source_output or a.destination_input == b.destination_input:
        return True
    return _paths_conflict(tuple(a.path), tuple(b.path))


@lru_cache(maxsize=4096)
def _paths_conflict(a_path, b_path):
    # Geometry stays fixed between road edits. Do the segment math once per
    # pair of paths, not once per pair of cars on every animation frame.
    from models import distance_to_polyline

    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])

    for p, q in zip(a_path, a_path[1:]):
        for r, s in zip(b_path, b_path[1:]):
            # Proper crossings can lie between sampled points, so check the
            # line segments as well as their endpoint distances.
            if cross(p, q, r)*cross(p, q, s) < 0 and cross(r, s, p)*cross(r, s, q) < 0:
                return True
            if min(distance_to_polyline([r, s], p), distance_to_polyline([r, s], q),
                   distance_to_polyline([p, q], r), distance_to_polyline([p, q], s)) < 8:
                return True
    return False


def yields_to(a: StopArrival, b: StopArrival) -> bool:
    """Choose between conflicting, nearly simultaneous uncontrolled arrivals."""
    from models import ManeuverType
    ah, bh = a.connection.source_output.heading, b.connection.source_output.heading
    opposed = ah[0]*bh[0] + ah[1]*bh[1] < -0.7
    a_left = a.connection.maneuver.kind in (ManeuverType.LEFT_TURN, ManeuverType.U_TURN)
    b_left = b.connection.maneuver.kind in (ManeuverType.LEFT_TURN, ManeuverType.U_TURN)
    if opposed and a_left != b_left:
        return a_left
    ap, bp = a.connection.source_output.position, b.connection.source_output.position
    # With screen Y pointing down, a positive cross product means "on my right".
    return ah[0]*(bp[1]-ap[1]) - ah[1]*(bp[0]-ap[0]) > 0.01
