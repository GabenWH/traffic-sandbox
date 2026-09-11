"""Inspectable behavior decisions for cars on constructed-road routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import sqrt

from models import ManeuverType
from merge_behavior import MergeObservation, MERGE_STRATEGIES, MIN_JOINING_SPEED


STOP_DWELL_SECONDS = 0.5
COMFORTABLE_BRAKING = 18.0
TURN_SIGNAL_DISTANCE = 100.0


class SignalIntent(StrEnum):
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"


class BehaviorState(StrEnum):
    CRUISING = "cruising"
    APPROACHING_STOP = "approaching_stop"
    STOPPED = "stopped"
    WAITING_FOR_PRIORITY = "waiting_for_priority"
    ENTERING_INTERSECTION = "entering_intersection"
    CLEARING_INTERSECTION = "clearing_intersection"


@dataclass(frozen=True)
class CarObservation:
    cruise_speed: float
    speed: float
    distance_to_stop: float | None = None
    must_stop: bool = False
    must_yield: bool = False
    merge: MergeObservation | None = None
    priority_reason: str = "waiting for conflicting traffic"
    has_priority: bool = False
    lead_car_distance: float | None = None
    following_gap: float = 24.0
    inside_intersection: bool = False
    next_maneuver: ManeuverType | None = None
    distance_to_maneuver: float | None = None
    inside_maneuver: bool = False


@dataclass(frozen=True)
class CarDecision:
    desired_speed: float
    state: BehaviorState
    wait_reason: str = ""
    register_stop: bool = False
    request_claim: bool = False
    merge_entry_speed: float | None = None


@dataclass
class CarBrain:
    """Choose motion from observations without owning shared road state."""

    state: BehaviorState = BehaviorState.CRUISING
    wait_reason: str = ""
    desired_speed: float = 0.0
    stopped_elapsed: float = 0.0
    signal_intent: SignalIntent = SignalIntent.NONE
    merge_style: str = "rolling"
    phantom_target: str = ""

    def __post_init__(self):
        if self.merge_style not in MERGE_STRATEGIES:
            raise ValueError("Merge style must be rolling or cautious.")

    def following_distance(self, speed):
        """Driver preference, not a universal hardcoded gap for every car."""
        return (6.0 + 0.8*speed) if self.merge_style == "rolling" else (12.0 + 1.2*speed)

    def decide(self, observation: CarObservation, elapsed_seconds: float) -> CarDecision:
        desired = observation.cruise_speed
        state = BehaviorState.CRUISING
        reason = ""
        register_stop = False
        request_claim = False
        self.phantom_target = ""
        # The predicted joining time must use the speed we will actually ask
        # for. A queued car cannot reserve a gap as if it could cruise through.
        following_reason = ""
        if observation.lead_car_distance is not None:
            available = observation.lead_car_distance - observation.following_gap
            if available <= 0:
                desired = 0.0
                following_reason = "following queued car"
            else:
                desired = min(desired, sqrt(2.0 * COMFORTABLE_BRAKING * available))

        merge_choice = None
        if observation.merge is not None:
            merge_choice = MERGE_STRATEGIES[self.merge_style].decide(
                observation.merge, observation.speed, desired)
            desired = min(desired, merge_choice.desired_speed)
            self.phantom_target = merge_choice.phantom_target
            reason = merge_choice.reason

        # Our rear may still occupy one junction while our nose must obey the
        # next signal. Clearing the old junction does not cancel that signal.
        if observation.inside_intersection and not (observation.must_stop or observation.must_yield):
            state = BehaviorState.CLEARING_INTERSECTION
            self.stopped_elapsed = 0.0
        elif observation.must_yield and observation.distance_to_stop is not None:
            self.stopped_elapsed = 0.0
            # A queue-limited crawl is not a useful committed joining plan.
            # Approach gently until there is room for at least the slow joining
            # pace (or the road's lower cruise speed).
            merge_ready = merge_choice is None or (
                merge_choice.can_enter and merge_choice.entry_speed is not None
                and merge_choice.entry_speed >= min(MIN_JOINING_SPEED, observation.cruise_speed))
            if observation.has_priority and merge_ready:
                state = BehaviorState.ENTERING_INTERSECTION
                request_claim = True
            else:
                # A yield is permission to keep rolling when there is a gap.
                # Only brake toward the line when someone else has priority.
                desired = min(desired, sqrt(2.0 * COMFORTABLE_BRAKING
                                             * max(0.0, observation.distance_to_stop)))
                state = BehaviorState.WAITING_FOR_PRIORITY
                reason = (merge_choice.reason if merge_choice is not None and not merge_choice.can_enter
                          else observation.priority_reason)
        elif observation.must_stop and observation.distance_to_stop is not None:
            distance = max(0.0, observation.distance_to_stop)
            if distance > 0.05:
                state = BehaviorState.APPROACHING_STOP
                desired = min(desired, sqrt(2.0 * COMFORTABLE_BRAKING * distance))
                self.stopped_elapsed = 0.0
            elif observation.speed <= 0.1:
                desired = 0.0
                self.stopped_elapsed += elapsed_seconds
                register_stop = True
                if self.stopped_elapsed < STOP_DWELL_SECONDS:
                    state = BehaviorState.STOPPED
                    reason = "completing stop dwell"
                elif observation.has_priority:
                    state = BehaviorState.ENTERING_INTERSECTION
                    desired = observation.cruise_speed
                    request_claim = True
                else:
                    state = BehaviorState.WAITING_FOR_PRIORITY
                    reason = "waiting for all-way-stop priority"
            else:
                state = BehaviorState.APPROACHING_STOP
                desired = 0.0
        else:
            self.stopped_elapsed = 0.0

        if following_reason:
            reason = following_reason

        decision = CarDecision(max(0.0, desired), state, reason, register_stop, request_claim,
                               merge_choice.entry_speed if merge_choice else None)
        self.state = decision.state
        self.wait_reason = decision.wait_reason
        self.desired_speed = decision.desired_speed
        self.signal_intent = self._signal_intent(observation)
        return decision

    @staticmethod
    def _signal_intent(observation: CarObservation) -> SignalIntent:
        maneuver = observation.next_maneuver
        distance = observation.distance_to_maneuver
        if (
            maneuver is None
            or distance is None
            or (not observation.inside_maneuver and distance > TURN_SIGNAL_DISTANCE)
        ):
            return SignalIntent.NONE
        if maneuver in (ManeuverType.LEFT_TURN, ManeuverType.U_TURN):
            return SignalIntent.LEFT
        if maneuver is ManeuverType.RIGHT_TURN:
            return SignalIntent.RIGHT
        return SignalIntent.NONE
