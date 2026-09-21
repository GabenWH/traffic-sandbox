"""Small, deterministic escape hatch for right-of-way hesitation.

This module does not move cars.  It watches progress facts and selects at most
one already-waiting lead car whose path has been checked by the simulator.  The
traffic loop turns that selection into a cautious intent; normal occupancy and
claim checks remain responsible for physical safety.
"""

from __future__ import annotations

from dataclasses import dataclass, field


SOFT_DEADLOCK_SECONDS = 5.0


@dataclass(frozen=True)
class DeadlockCandidate:
    """A stopped lead car and whether it has real space to make progress."""

    car_id: str
    path_clear: bool
    movement_id: str = ""


@dataclass
class SoftDeadlockResolver:
    """Choose one temporary winner after the whole traffic state stalls."""

    stall_threshold: float = SOFT_DEADLOCK_SECONDS
    stall_seconds: float = 0.0
    winner_id: str | None = None
    winner_movement_id: str | None = None
    hard_gridlock: bool = False
    _waiting_seconds: dict[str, float] = field(default_factory=dict, repr=False)

    def observe_frame(
        self,
        elapsed_seconds: float,
        *,
        made_progress: bool,
        candidate_ids: tuple[str, ...],
        winner_resolved: bool = False,
    ) -> None:
        """Remember only simulation facts; never mutate vehicle state here."""
        current = set(candidate_ids)
        self._waiting_seconds = {
            car_id: seconds + elapsed_seconds
            for car_id, seconds in self._waiting_seconds.items()
            if car_id in current
        }
        for car_id in current:
            self._waiting_seconds.setdefault(car_id, elapsed_seconds)

        if winner_resolved or (made_progress and self.winner_id is None):
            self.stall_seconds = 0.0
            self.winner_id = None
            self.winner_movement_id = None
            self.hard_gridlock = False
            return
        self.stall_seconds += elapsed_seconds

    def choose_winner(self, candidates: tuple[DeadlockCandidate, ...]) -> str | None:
        """Return the longest-waiting safe candidate after a sustained stall."""
        if self.stall_seconds + 1e-9 < self.stall_threshold:
            self.winner_id = None
            self.winner_movement_id = None
            self.hard_gridlock = False
            return None

        by_movement = {
            (candidate.car_id, candidate.movement_id): candidate
            for candidate in candidates
        }
        winner_key = (self.winner_id, self.winner_movement_id)
        if self.winner_id is not None and winner_key in by_movement:
            # Once selected, ownership stays with this car/movement.  If new
            # traffic blocks its probe, pause it instead of granting a second
            # override while the first one's claim may still exist.
            winner = by_movement[winner_key]
            self.hard_gridlock = not winner.path_clear
            return self.winner_id if winner.path_clear else None

        if self.winner_id is not None:
            # The old grant ended or the car reached another junction.  Leave
            # one neutral frame before considering a new override so a claim
            # from the previous movement cannot overlap its replacement.
            self.stall_seconds = 0.0
            self.winner_id = None
            self.winner_movement_id = None
            self.hard_gridlock = False
            return None

        eligible = [candidate for candidate in candidates if candidate.path_clear]
        self.hard_gridlock = bool(candidates) and not eligible
        if not eligible:
            self.winner_id = None
            self.winner_movement_id = None
            return None

        eligible.sort(key=lambda item: (-self._waiting_seconds.get(item.car_id, 0.0),
                                        item.car_id))
        self.winner_id = eligible[0].car_id
        self.winner_movement_id = eligible[0].movement_id
        return self.winner_id

    def reset(self) -> None:
        self.stall_seconds = 0.0
        self.winner_id = None
        self.winner_movement_id = None
        self.hard_gridlock = False
        self._waiting_seconds.clear()


def merge_space_clear(car_length: float, vehicles: tuple, reservations: tuple) -> bool:
    """Allow negotiation only with stopped traffic and open physical space."""
    if reservations:
        return False
    for other in vehicles:
        # A moving through vehicle has genuine priority.  The temporary winner
        # exists to settle mutual hesitation between stopped drivers, not to
        # turn a yield into a forced merge in front of live traffic.
        if max(other.speed, getattr(other, "cruise_speed", 0.0)) > 0.1:
            return False
        if abs(other.position) < (car_length + other.length) / 2 + 4.0:
            return False
    return True
