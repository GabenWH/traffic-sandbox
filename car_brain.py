"""Inspectable behavior decisions for cars on constructed-road routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import sqrt

from models import ManeuverType


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


@dataclass
class CarBrain:
    """Choose motion from observations without owning shared road state."""

    state: BehaviorState = BehaviorState.CRUISING
    wait_reason: str = ""
    desired_speed: float = 0.0
    stopped_elapsed: float = 0.0
    signal_intent: SignalIntent = SignalIntent.NONE

    def decide(self, observation: CarObservation, elapsed_seconds: float) -> CarDecision:
        desired = observation.cruise_speed
        state = BehaviorState.CRUISING
        reason = ""
        register_stop = False
        request_claim = False

        if observation.inside_intersection:
            state = BehaviorState.CLEARING_INTERSECTION
            self.stopped_elapsed = 0.0
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

        if observation.lead_car_distance is not None:
            available = observation.lead_car_distance - observation.following_gap
            if available <= 0:
                desired = 0.0
                reason = "following queued car"
            else:
                desired = min(desired, sqrt(2.0 * COMFORTABLE_BRAKING * available))

        decision = CarDecision(max(0.0, desired), state, reason, register_stop, request_claim)
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
