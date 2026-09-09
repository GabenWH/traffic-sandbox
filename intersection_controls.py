"""Runtime observations and reservations for intersection controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, pi
from functools import lru_cache

from models import LaneConnection, ControlType


@dataclass(frozen=True)
class StopArrival:
    car_id: str
    connection: LaneConnection
    stopped_at: float


@dataclass
class AllWayStopCoordinator:
    """Arbitrate claims while leaving movement decisions to individual cars."""

    arrivals: dict[str, StopArrival] = field(default_factory=dict)
    claims: dict[str, LaneConnection] = field(default_factory=dict)

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

    def _blocked_by_claim(self, car_id, connection):
        return any(
            owner != car_id and claimed.intersection_id == connection.intersection_id
            and (connection.control.kind is ControlType.STOP
                 or claimed.control.kind is ControlType.STOP
                 or movements_conflict(connection, claimed))
            for owner, claimed in self.claims.items()
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
            # Preserve the original, deliberately conservative all-way stop.
            return min(waiting, key=self._priority_key).car_id == car_id
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
        self.claims[car_id] = connection
        self.arrivals.pop(car_id, None)
        return True

    def claim(self, car_id: str, connection: LaneConnection) -> bool:
        if not self.can_claim(car_id, connection):
            return False
        self.claims[car_id] = connection
        self.arrivals.pop(car_id, None)
        return True

    def release(self, car_id: str) -> None:
        self.claims.pop(car_id, None)

    def forget_car(self, car_id: str) -> None:
        self.arrivals.pop(car_id, None)
        self.claims.pop(car_id, None)

    def has_claim(self, car_id: str, connection: LaneConnection) -> bool:
        return self.claims.get(car_id) is connection

    @staticmethod
    def _priority_key(arrival: StopArrival) -> tuple[float, float, str]:
        heading = arrival.connection.source_output.heading
        # Clockwise compass ordering beginning at north, then stable car ID.
        clockwise = (atan2(heading[0], -heading[1]) + 2 * pi) % (2 * pi)
        return (round(arrival.stopped_at, 6), clockwise, arrival.car_id)


def movements_conflict(a: LaneConnection, b: LaneConnection) -> bool:
    """Would the two vehicle paths cross, join, or pass too close together?

    Comparing the paths lets opposite straight-through traffic move together.
    A shared destination is a merge, even when the drawn curves only meet at
    their last point. Eight feet covers two six-foot cars plus a small margin.
    """
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
