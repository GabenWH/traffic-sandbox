"""Runtime observations and reservations for intersection controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, pi

from models import LaneConnection


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

    def can_claim(self, car_id: str, connection: LaneConnection) -> bool:
        arrival = self.arrivals.get(car_id)
        if arrival is None or arrival.connection.intersection_id != connection.intersection_id:
            return False
        if any(
            owner != car_id and claimed.intersection_id == connection.intersection_id
            for owner, claimed in self.claims.items()
        ):
            return False
        waiting = [
            item for item in self.arrivals.values()
            if item.connection.intersection_id == connection.intersection_id
        ]
        return bool(waiting) and min(waiting, key=self._priority_key).car_id == car_id

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
