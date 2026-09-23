"""Temporary routed traffic generated between selected city junctions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import count
from math import dist, isfinite, sqrt
import random
from time import perf_counter

from city import CityMap
from car_brain import CarBrain, CarDecision, CarObservation
from intersection_controls import AllWayStopCoordinator
from merge_behavior import observe_merge, MERGE_STRATEGIES
from soft_deadlock import DeadlockCandidate, SoftDeadlockResolver, merge_space_clear
from mobility import (
    LaneTraversal,
    MobilityLink,
    MobilityNode,
    PortTraversal,
    nearest_lane_position,
    vehicle_link_points,
    vehicle_route_points,
)
from models import ManeuverType, ControlType, Intersection, Lane, LaneConnection, Point, polyline_length
from pathfinding import Path
from traffic_occupancy import TrafficOccupancyIndex
from traffic_debugger import TrafficDebugger
from units import mph_to_pixels_per_second


TEST_CAR_SPEED_MPH = 25.0
TEST_SPAWN_INTERVAL = 1.5
TEST_TRAFFIC_LIMIT = 60
TEST_CAR_ACCELERATION = 10.0
TEST_CAR_BRAKING = 24.0
TEST_CAR_FOLLOWING_GAP = 22.0
TEST_CAR_LOOKAHEAD = 128.0
_car_ids = count(1)


@dataclass(frozen=True)
class TrafficIntent:
    """One car's decision from the immutable start-of-tick traffic snapshot."""

    car: "RoutedTestCar"
    distance_before: float
    speed_before: float
    route_movement: tuple[float, float, LaneConnection] | None
    movement: tuple[float, float, LaneConnection] | None
    has_claim: bool
    is_merge: bool
    merge_observation: object | None
    priority: bool
    distance_to_stop: float | None
    lead_car: "RoutedTestCar" | None
    lead_distance: float | None
    decision: CarDecision


@dataclass
class RoutedTestCar:
    """Compact progress state for a car following one immutable route polyline."""

    source_id: str
    destination_id: str
    route: Path[MobilityNode, MobilityLink]
    points: tuple[Point, ...]
    speed: float
    color: str
    distance: float = 0.0
    position: Point = field(init=False)
    heading: Point = field(init=False)
    total_length: float = field(init=False)
    item: int | None = None
    rendered: bool = False
    render_style: str | None = None
    length: float = 14.0
    width: float = 6.0
    id: str = field(default_factory=lambda: f"test-car-{next(_car_ids)}")
    brain: CarBrain = field(default_factory=CarBrain)
    controlled_movements: tuple[tuple[float, float, LaneConnection], ...] = field(
        init=False, repr=False,
    )
    route_segments: tuple[tuple[float, float, tuple[object, ...], float], ...] = field(
        init=False, repr=False,
    )
    _claimed_movement: LaneConnection | None = field(default=None, init=False, repr=False)
    cruise_speed_bound: float = field(default=TEST_CAR_SPEED_MPH*22/15, init=False)
    _merge_entry_speed: float | None = field(default=None, init=False, repr=False)
    signal_items: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.total_length = polyline_length(list(self.points))
        if len(self.points) < 2 or self.total_length <= 0:
            raise ValueError("A routed test car needs a non-degenerate path")
        if not isfinite(self.speed) or self.speed <= 0:
            raise ValueError("A routed test car needs a positive speed")
        self.controlled_movements = _controlled_movement_ranges(self.route)
        self.route_segments = _route_occupancy_segments(self.route)
        self.position, self.heading = _position_and_heading(self.points, 0.0)

    def advance(self, elapsed_seconds: float) -> bool:
        """Advance the car and return whether it still lies on its route."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        self.distance = min(self.total_length, self.distance + self.speed * elapsed_seconds)
        # Substeps can accumulate a few trillionths of a foot of rounding error.
        if self.total_length - self.distance < 1e-8:
            self.distance = self.total_length
        self.position, self.heading = _position_and_heading(self.points, self.distance)
        return self.distance < self.total_length

    @property
    def claimed_movement(self) -> LaneConnection | None:
        return self._claimed_movement

    def occupancy_position(self) -> tuple[tuple[object, ...], float] | None:
        """Return canonical mobility-link key and longitudinal position."""
        for start, end, key, offset in self.route_segments:
            if self.distance < end or end == self.total_length:
                return key, offset + max(0.0, min(end - start, self.distance - start))
        return None


@dataclass
class TestTrafficSimulation:
    """Spawn routed cars between junctions explicitly enabled by the user."""

    spawn_interval: float = TEST_SPAWN_INTERVAL
    max_cars: int = TEST_TRAFFIC_LIMIT
    speed_mph: float = TEST_CAR_SPEED_MPH
    rng: random.Random = field(default_factory=random.Random, repr=False)
    active_junction_ids: list[str] = field(default_factory=list)
    cars: list[RoutedTestCar] = field(default_factory=list)
    _spawn_elapsed: dict[str, float] = field(default_factory=dict, repr=False)
    stop_coordinator: AllWayStopCoordinator = field(
        default_factory=AllWayStopCoordinator, repr=False,
    )
    elapsed_time: float = 0.0
    _spawned_count: int = field(default=0, init=False, repr=False)
    occupancy: TrafficOccupancyIndex = field(
        default_factory=TrafficOccupancyIndex, repr=False,
    )
    # Optional recorder.  It observes completed decisions; it never feeds a
    # decision back into the traffic model.
    debugger: TrafficDebugger | None = field(default=None, repr=False)
    deadlock_resolver: SoftDeadlockResolver = field(
        default_factory=SoftDeadlockResolver, repr=False,
    )
    update_mode: str = "legacy"

    colors = ("#ff5b72", "#37e6ff", "#f7d154", "#7fea8c", "#c98cff")

    def __post_init__(self) -> None:
        if not isfinite(self.spawn_interval) or self.spawn_interval <= 0:
            raise ValueError("Test-traffic spawn interval must be positive")
        if self.max_cars < 1:
            raise ValueError("Test traffic must allow at least one car")
        if not isfinite(self.speed_mph) or self.speed_mph <= 0:
            raise ValueError("Test-traffic speed must be positive")
        self._validate_update_mode()
        if len({car.id for car in self.cars}) != len(self.cars):
            raise ValueError("Preloaded traffic cars must have unique IDs")
        self._spawned_count = len(self.cars)

    def _validate_update_mode(self) -> None:
        if self.update_mode not in ("legacy", "data_first"):
            raise ValueError("Traffic update mode must be legacy or data_first")

    def toggle_junction(self, junction: Intersection) -> bool:
        """Toggle a junction as a combined source/sink; return its new state."""
        if junction.id in self.active_junction_ids:
            self.active_junction_ids.remove(junction.id)
            self._spawn_elapsed.pop(junction.id, None)
            return False
        self.active_junction_ids.append(junction.id)
        self._spawn_elapsed[junction.id] = 0.0
        return True

    def is_active(self, junction: Intersection) -> bool:
        return junction.id in self.active_junction_ids

    def active_junctions(self, city_map: CityMap) -> list[Intersection]:
        by_id = {junction.id: junction for junction in city_map.intersections}
        return [by_id[item] for item in self.active_junction_ids if item in by_id]

    def spawn_car(
        self,
        city_map: CityMap,
        source: Intersection,
        destination: Intersection,
    ) -> RoutedTestCar | None:
        """Spawn one car when a directed route exists between two junctions."""
        if source is destination or len(self.cars) >= self.max_cars:
            return None
        route = city_map.find_vehicle_route_between(source, destination)
        if route is None:
            return None
        points = vehicle_route_points(route)
        if len(points) < 2 or polyline_length(list(points)) <= 0:
            return None
        existing_ids = {car.id for car in self.cars}
        next_spawn_id = self._spawned_count + 1
        while f"test-car-{next_spawn_id:06d}" in existing_ids:
            next_spawn_id += 1
        car = RoutedTestCar(
            source_id=source.id,
            destination_id=destination.id,
            route=route,
            points=points,
            speed=mph_to_pixels_per_second(self.speed_mph),
            color=self.rng.choice(self.colors),
            # Simulation-local, zero-padded IDs make every stable tie-break
            # reproducible and preserve spawn order across digit boundaries.
            id=f"test-car-{next_spawn_id:06d}",
        )
        self.occupancy.rebuild(self.cars)
        spawn_gap = self.occupancy.lead_gap(car, TEST_CAR_FOLLOWING_GAP + car.length)
        if spawn_gap is not None and spawn_gap < TEST_CAR_FOLLOWING_GAP:
            return None
        # Mix driver decisions on the same road. No global road mode decides
        # that every driver must use the same merging behavior.
        self._spawned_count = next_spawn_id
        car.brain.merge_style = "cautious" if self._spawned_count % 5 == 0 else "rolling"
        self.cars.append(car)
        return car

    def update(self, city_map: CityMap, elapsed_seconds: float) -> list[RoutedTestCar]:
        """Spawn and advance test cars, returning cars that reached a sink."""
        self._validate_update_mode()
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        # Keep observations frequent even when the UI fast-forwards or a test
        # advances several seconds at once. Otherwise a car can skip a whole
        # entrance between two decisions.
        if elapsed_seconds > 0.05 + 1e-9:
            completed = []
            remaining = elapsed_seconds
            while remaining > 1e-9:
                step = min(0.05, remaining)
                completed.extend(self.update(city_map, step))
                remaining -= step
            return completed
        frame_started = perf_counter() if self.debugger is not None else 0.0
        if self.debugger is not None:
            self.debugger.begin_frame()
        self.elapsed_time += elapsed_seconds
        current_ids = {junction.id for junction in city_map.intersections}
        self.active_junction_ids = [
            item for item in self.active_junction_ids if item in current_ids
        ]
        self._spawn_elapsed = {
            item: self._spawn_elapsed.get(item, 0.0)
            for item in self.active_junction_ids
        }

        junctions = self.active_junctions(city_map)
        if len(junctions) >= 2:
            for source in junctions:
                self._spawn_elapsed[source.id] += elapsed_seconds
                if self._spawn_elapsed[source.id] < self.spawn_interval:
                    continue
                self._spawn_elapsed[source.id] %= self.spawn_interval
                destinations = [item for item in junctions if item is not source]
                self.rng.shuffle(destinations)
                for destination in destinations:
                    if self.spawn_car(city_map, source, destination) is not None:
                        break
        spawned_at = perf_counter() if self.debugger is not None else 0.0

        if self.update_mode == "data_first":
            return self._update_data_first(
                elapsed_seconds,
                frame_started=frame_started,
                spawned_at=spawned_at,
            )

        self.occupancy.rebuild(self.cars)
        # Observe EVERY approach before granting ANY entry. The order of cars
        # in the Python list must not decide who gets right of way.
        for car in self.cars:
            # A queued circulating car may accelerate back to its road speed.
            # Its current speed alone is not a safe prediction of future travel.
            car.cruise_speed_bound = _route_cruise_speed(car, self.speed_mph)
        deadlock_candidates = []
        for car in self.cars:
            is_waiting = (
                car.speed <= 0.1
                and car.brain.state.value
                in ("waiting_for_priority", "entering_intersection")
            )
            if car.id != self.deadlock_resolver.winner_id and not is_waiting:
                continue
            movement = _next_controlled_movement(car, self.stop_coordinator)
            if movement is None:
                continue
            deadlock_candidates.append(DeadlockCandidate(
                car.id,
                car.brain.wait_reason != "following queued car"
                and _temporary_winner_path_clear(
                    car, movement, self.cars, self.occupancy,
                    self.stop_coordinator,
                ),
                movement_id=movement[2].id,
            ))
        deadlock_candidates = tuple(deadlock_candidates)
        temporary_winner = self.deadlock_resolver.choose_winner(deadlock_candidates)
        for car in self.cars:
            movement = _next_controlled_movement(car, self.stop_coordinator)
            if (movement is not None and movement[2].merge_target is not None
                    and car.distance + car.length/2 < movement[0]
                    and self.stop_coordinator.has_claim(car.id, movement[2])):
                # A reservation made while approaching is not a permanent
                # ticket. Recheck the gap if we have not physically entered yet.
                self.stop_coordinator.release(car.id, movement[2])
                car._claimed_movement = None
            if movement is None or self.stop_coordinator.has_claim(car.id, movement[2]):
                continue
            distance = max(0.0, movement[0] - car.length / 2 - car.distance)
            if movement[2].control.kind is ControlType.STOP:
                if distance <= 0.05 and car.speed <= 0.1:
                    self.stop_coordinator.observe_stop(car.id, movement[2], self.elapsed_time)
            elif movement[2].merge_target is None and distance <= TEST_CAR_LOOKAHEAD:
                self.stop_coordinator.observe_approach(
                    car.id, movement[2], self.elapsed_time + distance / max(car.speed, 1.0))
        observed_at = perf_counter() if self.debugger is not None else 0.0
        # This is the number that was actually considered this frame.  A car
        # finishing later in the frame is still present in its trace record.
        frame_car_count = len(self.cars)
        completed: list[RoutedTestCar] = []
        temporary_winner_entered = False
        decision_seconds = 0.0
        resolution_seconds = 0.0
        for car in list(self.cars):
            distance_before = car.distance
            speed_before = car.speed
            route_movement = _next_route_movement(car)
            movement = _next_controlled_movement(car, self.stop_coordinator)
            has_claim = (
                movement is not None
                and self.stop_coordinator.has_claim(car.id, movement[2])
            )
            inside = any(
                self.stop_coordinator.has_claim(car.id, connection)
                and start <= car.distance + car.length/2
                and car.distance - car.length/2 < end
                for start, end, connection in car.controlled_movements)
            distance_to_stop = (
                max(0.0, movement[0] - car.length / 2 - car.distance)
                if movement is not None and not has_claim
                else None
            )
            if movement is not None and movement[2].control.kind is ControlType.STOP and distance_to_stop is not None and distance_to_stop <= 0.05 and car.speed <= 0.1:
                self.stop_coordinator.observe_stop(car.id, movement[2], self.elapsed_time)
            is_merge = movement is not None and movement[2].merge_target is not None
            merge_observation = observe_merge(car, movement, self.cars) if is_merge else None
            priority = movement is not None and (
                self.stop_coordinator.can_enter_merge(car.id, movement[2]) if is_merge
                else self.stop_coordinator.can_claim(car.id, movement[2]))
            priority_reason = "waiting for intersection priority"
            if movement is not None and not has_claim and not is_merge:
                # Reserve enough space for our whole car beyond the movement.
                # Stopping across the exit would block everyone else's path.
                exit_gap = self.occupancy.gap_from(car, movement[1], TEST_CAR_LOOKAHEAD)
                if exit_gap is not None and exit_gap < TEST_CAR_FOLLOWING_GAP + car.length / 2:
                    priority = False
                    priority_reason = "waiting for room beyond the junction"
                # A short link is not a waiting area: our rear would still
                # block this junction if we had to stop at the next yield.
                # Look through consecutive short links before entering. This
                # is a prediction, not a permanent reservation of the circle;
                # the real yield is checked again as the nose approaches it.
                chain_end = movement[1]
                for following in car.controlled_movements:
                    if following[0] < movement[1]:
                        continue
                    if following[0] - chain_end >= car.length + 4.0:
                        break
                    if following[2].merge_target is not None:
                        opening = MERGE_STRATEGIES[car.brain.merge_style].decide(
                            observe_merge(car, following, self.cars), car.speed,
                            _route_cruise_speed(car, self.speed_mph))
                        if (not opening.can_enter or not self.stop_coordinator.can_enter_merge(
                                car.id, following[2])):
                            priority = False
                            priority_reason = "waiting before short link for the next yield"
                            break
                    chain_end = following[1]
            lead_distance = self.occupancy.lead_gap(car, TEST_CAR_LOOKAHEAD)
            cruise_speed = _route_cruise_speed(car, self.speed_mph)
            # While approaching, phantom following chooses a pace. Once we
            # enter, keep the speed plan that was checked when granting entry.
            # Ordinary following can still brake for a real vehicle ahead.
            for active in car.controlled_movements:
                if (active[2].merge_target is not None
                        and self.stop_coordinator.has_claim(car.id, active[2])
                        and car.distance + car.length/2 >= active[0]
                        and car.distance - car.length/2 < active[1]):
                    # Execute the plan checked at approval. Changing phantom
                    # targets mid-entry must not accelerate beyond that plan.
                    if car._merge_entry_speed is not None:
                        cruise_speed = min(cruise_speed, car._merge_entry_speed)
            decision_started = perf_counter() if self.debugger is not None else 0.0
            decision = car.brain.decide(
                CarObservation(
                    cruise_speed=cruise_speed,
                    speed=car.speed,
                    distance_to_stop=distance_to_stop,
                    must_stop=movement is not None and not has_claim and movement[2].control.kind is ControlType.STOP,
                    must_yield=movement is not None and not has_claim and movement[2].control.kind is not ControlType.STOP,
                    priority_reason=priority_reason,
                    merge=merge_observation,
                    has_priority=priority,
                    lead_car_distance=lead_distance,
                    following_gap=car.brain.following_distance(car.speed),
                    inside_intersection=inside,
                    next_maneuver=_signaled_maneuver(car, route_movement),
                    distance_to_maneuver=(
                        max(0.0, route_movement[0] - car.distance)
                        if route_movement is not None else None
                    ),
                    inside_maneuver=(
                        route_movement is not None
                        and route_movement[0] <= car.distance < route_movement[1]
                    ),
                    temporary_winner=car.id == temporary_winner,
                    temporary_winner_blocked=(
                        car.id == self.deadlock_resolver.winner_id
                        and temporary_winner is None
                    ),
                ),
                elapsed_seconds,
            )
            if self.debugger is not None:
                decision_seconds += perf_counter() - decision_started
            resolution_started = perf_counter() if self.debugger is not None else 0.0
            if decision.register_stop and movement is not None:
                self.stop_coordinator.observe_stop(car.id, movement[2], self.elapsed_time)
            if (decision.request_claim and movement is not None
                    and (distance_to_stop or 0) <= max(10.0, car.speed * 0.6)):
                # Claim only near entry; a car far up the road should not reserve
                # an empty junction for several seconds while it approaches.
                if car.id == temporary_winner:
                    has_claim = self.stop_coordinator.claim_temporary_winner(
                        car.id, movement[2])
                else:
                    has_claim = (self.stop_coordinator.claim_merge(car.id, movement[2]) if is_merge
                                 else self.stop_coordinator.claim(car.id, movement[2]))
                if has_claim:
                    car._claimed_movement = movement[2]
                    if is_merge:
                        car._merge_entry_speed = decision.merge_entry_speed
                        # Begin the checked plan in this same update; do not
                        # spend one tick executing the old approach target.
                        decision = replace(decision, desired_speed=decision.merge_entry_speed)

            speed_delta = decision.desired_speed - car.speed
            limit = (TEST_CAR_ACCELERATION if speed_delta > 0 else TEST_CAR_BRAKING) * elapsed_seconds
            car.speed += max(-limit, min(limit, speed_delta))
            travel = car.speed * elapsed_seconds
            if lead_distance is not None:
                travel = min(
                    travel,
                    # Physical overlap guard. Comfortable following distance is
                    # chosen by CarBrain and should not become another stop wall.
                    max(0.0, lead_distance - 4.0),
                )
                if travel == 0.0:
                    car.speed = 0.0
            if movement is not None and not has_claim:
                stop_distance = movement[0] - car.length / 2
                travel = min(travel, max(0.0, stop_distance - car.distance))
                if travel == 0.0:
                    car.speed = 0.0
            alive = car.advance(travel / car.speed if car.speed > 0 else 0.0)
            if (car.id == temporary_winner and has_claim and movement is not None
                    and car.distance + car.length/2 >= movement[0]):
                temporary_winner_entered = True
            # Keep every junction occupied until our REAR clears it, even
            # while our FRONT is already obeying the next yield or stop.
            for _, end, connection in car.controlled_movements:
                if car.distance - car.length / 2 >= end:
                    self.stop_coordinator.release(car.id, connection)
            remaining_claims = [connection for _, _, connection in car.controlled_movements
                                if self.stop_coordinator.has_claim(car.id, connection)]
            car._claimed_movement = remaining_claims[-1] if remaining_claims else None
            # Refresh occupancy so a later car in this same tick sees the
            # space just taken by a merge. At this prototype's 60-car limit a
            # simple rebuild is clearer than maintaining incremental bins.
            self.occupancy.rebuild(self.cars)
            if not alive:
                completed.append(car)
                self.stop_coordinator.forget_car(car.id)
            if self.debugger is not None:
                self.debugger.record_car(
                    car,
                    distance_before=distance_before,
                    speed_before=speed_before,
                    decision=decision,
                    movement=movement,
                    has_priority=priority,
                    # Report the resolved claim, rather than the fact that
                    # existed before this car asked for one this frame.
                    has_claim=(movement is not None and self.stop_coordinator.has_claim(
                        car.id, movement[2])),
                    merge_observation=merge_observation,
                )
                resolution_seconds += perf_counter() - resolution_started
        for car in completed:
            self.cars.remove(car)
        stopped_count = sum(car.speed <= 0.1 for car in self.cars)
        traffic_is_flowing = bool(self.cars) and stopped_count < 0.8 * len(self.cars)
        self.deadlock_resolver.observe_frame(
            elapsed_seconds,
            # A few cars creeping inches inside a forty-car standstill are not
            # meaningful throughput. Keep the winner committed until its nose
            # enters the conflict; otherwise its first cautious movement would
            # cancel the very intent meant to break the hesitation cycle.
            made_progress=traffic_is_flowing or bool(completed),
            candidate_ids=tuple(candidate.car_id for candidate in deadlock_candidates),
            winner_resolved=(
                temporary_winner_entered
                or any(car.id == self.deadlock_resolver.winner_id for car in completed)
            ),
        )
        if self.debugger is not None:
            finished_at = perf_counter()
            self.debugger.end_frame(
                simulated_time=self.elapsed_time,
                elapsed_seconds=elapsed_seconds,
                car_count=frame_car_count,
                completed_ids=[car.id for car in completed],
                timings_ms={
                    "spawn": (spawned_at - frame_started) * 1000,
                    "observe": (observed_at - spawned_at) * 1000,
                    # Intent is just CarBrain.  Resolution is the claim,
                    # acceleration clamp, movement, and occupancy refresh that
                    # converts that intent into this frame's final position.
                    "decision": decision_seconds * 1000,
                    "resolution": resolution_seconds * 1000,
                    "total": (finished_at - frame_started) * 1000,
                },
                deadlock_stall_seconds=self.deadlock_resolver.stall_seconds,
                temporary_winner_id=(
                    temporary_winner or self.deadlock_resolver.winner_id
                ),
                hard_gridlock=self.deadlock_resolver.hard_gridlock,
            )
        return completed

    def _update_data_first(
        self,
        elapsed_seconds: float,
        *,
        frame_started: float,
        spawned_at: float,
    ) -> list[RoutedTestCar]:
        """Advance one frame as snapshot -> intents -> resolve -> batch apply."""
        occupancy_started = perf_counter() if self.debugger is not None else 0.0
        self.occupancy.rebuild(self.cars)
        snapshot_at = perf_counter() if self.debugger is not None else 0.0
        cars = tuple(sorted(self.cars, key=lambda car: car.id))

        for car in cars:
            car.cruise_speed_bound = _route_cruise_speed(car, self.speed_mph)

        deadlock_candidates = []
        for car in cars:
            is_waiting = (
                car.speed <= 0.1
                and car.brain.state.value
                in ("waiting_for_priority", "entering_intersection")
            )
            if car.id != self.deadlock_resolver.winner_id and not is_waiting:
                continue
            movement = _next_controlled_movement(car, self.stop_coordinator)
            if movement is None:
                continue
            deadlock_candidates.append(DeadlockCandidate(
                car.id,
                car.brain.wait_reason != "following queued car"
                and _temporary_winner_path_clear(
                    car, movement, cars, self.occupancy,
                    self.stop_coordinator,
                ),
                movement_id=movement[2].id,
            ))
        deadlock_candidates = tuple(deadlock_candidates)
        temporary_winner = self.deadlock_resolver.choose_winner(deadlock_candidates)

        # Update shared arrival facts before asking any brain for a decision.
        for car in cars:
            movement = _next_controlled_movement(car, self.stop_coordinator)
            if (movement is not None and movement[2].merge_target is not None
                    and car.distance + car.length / 2 < movement[0]
                    and self.stop_coordinator.has_claim(car.id, movement[2])):
                self.stop_coordinator.release(car.id, movement[2])
                car._claimed_movement = None
            if movement is None or self.stop_coordinator.has_claim(car.id, movement[2]):
                continue
            distance = max(0.0, movement[0] - car.length / 2 - car.distance)
            if movement[2].control.kind is ControlType.STOP:
                if distance <= 0.05 and car.speed <= 0.1:
                    self.stop_coordinator.observe_stop(
                        car.id, movement[2], self.elapsed_time,
                    )
            elif movement[2].merge_target is None and distance <= TEST_CAR_LOOKAHEAD:
                self.stop_coordinator.observe_approach(
                    car.id,
                    movement[2],
                    self.elapsed_time + distance / max(car.speed, 1.0),
                )

        observed_at = perf_counter() if self.debugger is not None else 0.0
        frame_car_count = len(cars)
        intents: list[TrafficIntent] = []
        for car in cars:
            route_movement = _next_route_movement(car)
            movement = _next_controlled_movement(car, self.stop_coordinator)
            has_claim = (
                movement is not None
                and self.stop_coordinator.has_claim(car.id, movement[2])
            )
            inside = any(
                self.stop_coordinator.has_claim(car.id, connection)
                and start <= car.distance + car.length / 2
                and car.distance - car.length / 2 < end
                for start, end, connection in car.controlled_movements
            )
            distance_to_stop = (
                max(0.0, movement[0] - car.length / 2 - car.distance)
                if movement is not None and not has_claim
                else None
            )
            is_merge = movement is not None and movement[2].merge_target is not None
            merge_observation = observe_merge(car, movement, cars) if is_merge else None
            priority = movement is not None and (
                self.stop_coordinator.can_enter_merge(car.id, movement[2])
                if is_merge
                else self.stop_coordinator.can_claim(car.id, movement[2])
            )
            priority_reason = "waiting for intersection priority"
            if movement is not None and not has_claim and not is_merge:
                exit_gap = self.occupancy.gap_from(
                    car, movement[1], TEST_CAR_LOOKAHEAD,
                )
                if (exit_gap is not None
                        and exit_gap < TEST_CAR_FOLLOWING_GAP + car.length / 2):
                    priority = False
                    priority_reason = "waiting for room beyond the junction"
                chain_end = movement[1]
                for following in car.controlled_movements:
                    if following[0] < movement[1]:
                        continue
                    if following[0] - chain_end >= car.length + 4.0:
                        break
                    if following[2].merge_target is not None:
                        opening = MERGE_STRATEGIES[car.brain.merge_style].decide(
                            observe_merge(car, following, cars),
                            car.speed,
                            _route_cruise_speed(car, self.speed_mph),
                        )
                        if (not opening.can_enter
                                or not self.stop_coordinator.can_enter_merge(
                                    car.id, following[2],
                                )):
                            priority = False
                            priority_reason = (
                                "waiting before short link for the next yield"
                            )
                            break
                    chain_end = following[1]
            lead = self.occupancy.lead_car_gap(car, TEST_CAR_LOOKAHEAD)
            lead_car = lead[0] if lead is not None else None
            lead_distance = lead[1] if lead is not None else None
            cruise_speed = _route_cruise_speed(car, self.speed_mph)
            for active in car.controlled_movements:
                if (active[2].merge_target is not None
                        and self.stop_coordinator.has_claim(car.id, active[2])
                        and car.distance + car.length / 2 >= active[0]
                        and car.distance - car.length / 2 < active[1]
                        and car._merge_entry_speed is not None):
                    cruise_speed = min(cruise_speed, car._merge_entry_speed)
            decision = car.brain.decide(
                CarObservation(
                    cruise_speed=cruise_speed,
                    speed=car.speed,
                    distance_to_stop=distance_to_stop,
                    must_stop=(
                        movement is not None and not has_claim
                        and movement[2].control.kind is ControlType.STOP
                    ),
                    must_yield=(
                        movement is not None and not has_claim
                        and movement[2].control.kind is not ControlType.STOP
                    ),
                    priority_reason=priority_reason,
                    merge=merge_observation,
                    has_priority=priority,
                    lead_car_distance=lead_distance,
                    following_gap=car.brain.following_distance(car.speed),
                    inside_intersection=inside,
                    next_maneuver=_signaled_maneuver(car, route_movement),
                    distance_to_maneuver=(
                        max(0.0, route_movement[0] - car.distance)
                        if route_movement is not None else None
                    ),
                    inside_maneuver=(
                        route_movement is not None
                        and route_movement[0] <= car.distance < route_movement[1]
                    ),
                    temporary_winner=car.id == temporary_winner,
                    temporary_winner_blocked=(
                        car.id == self.deadlock_resolver.winner_id
                        and temporary_winner is None
                    ),
                ),
                elapsed_seconds,
            )
            intents.append(TrafficIntent(
                car=car,
                distance_before=car.distance,
                speed_before=car.speed,
                route_movement=route_movement,
                movement=movement,
                has_claim=has_claim,
                is_merge=is_merge,
                merge_observation=merge_observation,
                priority=priority,
                distance_to_stop=distance_to_stop,
                lead_car=lead_car,
                lead_distance=lead_distance,
                decision=decision,
            ))
        intents_at = perf_counter() if self.debugger is not None else 0.0

        # Resolve every request against the same collected intent set. Stable
        # priority order makes arbitration independent of the mutable car list.
        for intent in intents:
            if intent.decision.register_stop and intent.movement is not None:
                self.stop_coordinator.observe_stop(
                    intent.car.id, intent.movement[2], self.elapsed_time,
                )

        def claim_order(intent: TrafficIntent) -> tuple[object, ...]:
            if intent.car.id == temporary_winner:
                return (0, 0.0, 0.0, intent.car.id)
            priority_key = self.stop_coordinator.priority_key(intent.car.id)
            if priority_key is not None:
                return (1, *priority_key)
            return (2, 0.0, 0.0, intent.car.id)

        by_id = {intent.car.id: intent for intent in intents}
        for intent in sorted(intents, key=claim_order):
            movement = intent.movement
            decision = intent.decision
            has_claim = intent.has_claim
            if (decision.request_claim and movement is not None
                    and (intent.distance_to_stop or 0.0)
                    <= max(10.0, intent.speed_before * 0.6)):
                if intent.car.id == temporary_winner:
                    has_claim = self.stop_coordinator.claim_temporary_winner(
                        intent.car.id, movement[2],
                    )
                elif intent.is_merge:
                    has_claim = self.stop_coordinator.claim_merge(
                        intent.car.id, movement[2],
                    )
                else:
                    has_claim = self.stop_coordinator.claim(
                        intent.car.id, movement[2],
                    )
                if has_claim:
                    intent.car._claimed_movement = movement[2]
                    if intent.is_merge:
                        intent.car._merge_entry_speed = decision.merge_entry_speed
                        decision = replace(
                            decision,
                            desired_speed=decision.merge_entry_speed,
                        )
            by_id[intent.car.id] = replace(
                intent, has_claim=has_claim, decision=decision,
            )
        resolved = [by_id[intent.car.id] for intent in intents]
        resolved_at = perf_counter() if self.debugger is not None else 0.0

        next_speeds: dict[str, float] = {}
        planned_travel: dict[str, float] = {}
        for intent in resolved:
            car = intent.car
            decision = intent.decision
            speed_delta = decision.desired_speed - car.speed
            limit = (
                TEST_CAR_ACCELERATION if speed_delta > 0 else TEST_CAR_BRAKING
            ) * elapsed_seconds
            next_speed = car.speed + max(-limit, min(limit, speed_delta))
            travel = next_speed * elapsed_seconds
            if intent.movement is not None and not intent.has_claim:
                stop_distance = intent.movement[0] - car.length / 2
                travel = min(
                    travel,
                    max(0.0, stop_distance - intent.distance_before),
                )
            next_speeds[car.id] = next_speed
            planned_travel[car.id] = travel

        # A follower may use space its leader creates in this same accepted
        # batch. Relaxing the dependency chain preserves four feet of final
        # clearance without reintroducing car-list update order.
        for _ in range(len(resolved)):
            changed = False
            for intent in resolved:
                if intent.lead_car is None or intent.lead_distance is None:
                    continue
                leader_travel = planned_travel.get(intent.lead_car.id, 0.0)
                safe_travel = max(0.0, intent.lead_distance + leader_travel - 4.0)
                if planned_travel[intent.car.id] > safe_travel:
                    planned_travel[intent.car.id] = safe_travel
                    changed = True
            if not changed:
                break

        completed: list[RoutedTestCar] = []
        temporary_winner_entered = False
        for intent in resolved:
            car = intent.car
            travel = planned_travel[car.id]
            car.speed = next_speeds[car.id] if travel > 0.0 else 0.0
            alive = car.advance(travel / car.speed if car.speed > 0 else 0.0)
            if (car.id == temporary_winner and intent.has_claim
                    and intent.movement is not None
                    and car.distance + car.length / 2 >= intent.movement[0]):
                temporary_winner_entered = True
            if not alive:
                completed.append(car)
        applied_at = perf_counter() if self.debugger is not None else 0.0

        # Claims and occupancy change only after the full position batch lands.
        for intent in resolved:
            car = intent.car
            for _, end, connection in car.controlled_movements:
                if car.distance - car.length / 2 >= end:
                    self.stop_coordinator.release(car.id, connection)
            remaining_claims = [
                connection for _, _, connection in car.controlled_movements
                if self.stop_coordinator.has_claim(car.id, connection)
            ]
            car._claimed_movement = remaining_claims[-1] if remaining_claims else None
        for car in completed:
            self.stop_coordinator.forget_car(car.id)
            self.cars.remove(car)
        self.occupancy.rebuild(self.cars)
        occupancy_at = perf_counter() if self.debugger is not None else 0.0

        stopped_count = sum(car.speed <= 0.1 for car in self.cars)
        traffic_is_flowing = bool(self.cars) and stopped_count < 0.8 * len(self.cars)
        self.deadlock_resolver.observe_frame(
            elapsed_seconds,
            made_progress=traffic_is_flowing or bool(completed),
            candidate_ids=tuple(candidate.car_id for candidate in deadlock_candidates),
            winner_resolved=(
                temporary_winner_entered
                or any(car.id == self.deadlock_resolver.winner_id for car in completed)
            ),
        )
        if self.debugger is not None:
            for intent in resolved:
                self.debugger.record_car(
                    intent.car,
                    distance_before=intent.distance_before,
                    speed_before=intent.speed_before,
                    decision=intent.decision,
                    movement=intent.movement,
                    has_priority=intent.priority,
                    has_claim=(
                        intent.movement is not None
                        and self.stop_coordinator.has_claim(
                            intent.car.id, intent.movement[2],
                        )
                    ),
                    merge_observation=intent.merge_observation,
                )
            finished_at = perf_counter()
            self.debugger.end_frame(
                simulated_time=self.elapsed_time,
                elapsed_seconds=elapsed_seconds,
                car_count=frame_car_count,
                completed_ids=[car.id for car in completed],
                timings_ms={
                    "spawn": (spawned_at - frame_started) * 1000,
                    "snapshot": (snapshot_at - occupancy_started) * 1000,
                    "observe": (observed_at - snapshot_at) * 1000,
                    "intent": (intents_at - observed_at) * 1000,
                    "resolve": (resolved_at - intents_at) * 1000,
                    "apply": (applied_at - resolved_at) * 1000,
                    "occupancy": (occupancy_at - applied_at) * 1000,
                    "total": (finished_at - frame_started) * 1000,
                },
                deadlock_stall_seconds=self.deadlock_resolver.stall_seconds,
                temporary_winner_id=(
                    temporary_winner or self.deadlock_resolver.winner_id
                ),
                hard_gridlock=self.deadlock_resolver.hard_gridlock,
            )
        return completed

    def clear_cars(self) -> list[RoutedTestCar]:
        removed = list(self.cars)
        for car in removed:
            self.stop_coordinator.forget_car(car.id)
            car._claimed_movement = None
        self.cars.clear()
        self.deadlock_resolver.reset()
        return removed

    def clear(self) -> list[RoutedTestCar]:
        removed = self.clear_cars()
        self.active_junction_ids.clear()
        self._spawn_elapsed.clear()
        return removed


def _position_and_heading(points: tuple[Point, ...], distance_along: float) -> tuple[Point, Point]:
    remaining = max(0.0, float(distance_along))
    last_heading = (1.0, 0.0)
    for start, end in zip(points, points[1:]):
        length = dist(start, end)
        if length == 0:
            continue
        heading = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
        last_heading = heading
        if remaining <= length:
            fraction = remaining / length
            return (
                (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                ),
                heading,
            )
        remaining -= length
    return points[-1], last_heading


def _controlled_movement_ranges(
    route: Path[MobilityNode, MobilityLink],
) -> tuple[tuple[float, float, LaneConnection], ...]:
    distance_along = 0.0
    result: list[tuple[float, float, LaneConnection]] = []
    for link in route.edges:
        points = vehicle_link_points(link)
        length = polyline_length(list(points)) if len(points) >= 2 else 0.0
        if link.kind == "lane_connection" and isinstance(link.value, LaneConnection):
            result.append((distance_along + link.value.control_offset, distance_along + length, link.value))
        distance_along += length
    return tuple(result)


def _route_occupancy_segments(
    route: Path[MobilityNode, MobilityLink],
) -> tuple[tuple[float, float, tuple[object, ...], float], ...]:
    distance_along = 0.0
    result: list[tuple[float, float, tuple[object, ...], float]] = []
    for link in route.edges:
        points = vehicle_link_points(link)
        length = polyline_length(list(points)) if len(points) >= 2 else 0.0
        if length <= 0:
            continue
        key: tuple[object, ...]
        offset = 0.0
        if link.kind == "lane" and isinstance(link.value, Lane):
            key = ("lane", link.value.id)
        elif link.kind == "lane" and isinstance(link.value, LaneTraversal):
            key = ("lane", link.value.lane.id)
            offset = nearest_lane_position(link.value.lane, link.value.points[0])[0].distance
        elif link.kind == "road_port" and isinstance(link.value, PortTraversal):
            key = ("road_port", link.value.port.id, link.value.lane.id)
        elif link.kind == "lane_connection" and isinstance(link.value, LaneConnection):
            key = ("lane_connection", link.value.id)
        else:
            distance_along += length
            continue
        result.append((distance_along, distance_along + length, key, offset))
        distance_along += length
    return tuple(result)


def _next_controlled_movement(
    car: RoutedTestCar, coordinator: AllWayStopCoordinator,
) -> tuple[float, float, LaneConnection] | None:
    """Find the next entrance to obey, separately from junction occupancy.

    Once the nose enters with permission, look ahead to the next stop/yield.
    The previous claim stays alive until the rear clears that junction.
    """
    return next(
        (
            movement for movement in car.controlled_movements
            if car.distance - car.length / 2 < movement[1]
            and not (coordinator.has_claim(car.id, movement[2])
                     and car.distance + car.length / 2 >= movement[0])
            and movement[2].roundabout_role != "exit"
            and movement[2].maneuver.kind is not ManeuverType.U_TURN
        ),
        None,
    )


def _next_route_movement(
    car: RoutedTestCar,
) -> tuple[float, float, LaneConnection] | None:
    return next(
        (movement for movement in car.controlled_movements if car.distance < movement[1]),
        None,
    )


def _route_cruise_speed(car, speed_mph):
    """Brake before the tight circle, and keep a modest speed until the exit."""
    cruise = mph_to_pixels_per_second(speed_mph)
    curve_speed = mph_to_pixels_per_second(min(speed_mph, 12.0))
    for start, end, movement in car.controlled_movements:
        if movement.roundabout_role and car.distance - car.length/2 < end:
            distance = max(0.0, start - car.distance - car.length/2)
            # Once on the ring, the next movement is its exit. Stay slow across
            # the intervening shared arcs rather than accelerating toward it.
            if movement.roundabout_role == "exit":
                distance = 0.0
            return min(cruise, sqrt(curve_speed**2 + 2*TEST_CAR_BRAKING*distance))
    return cruise


def _signaled_maneuver(car, movement):
    """Wait until the final ring section before signaling the chosen exit."""
    if movement is None:
        return None
    start, end, connection = movement
    if connection.roundabout_role == "exit":
        previous = [segment for segment in car.route_segments
                    if segment[1] <= start + 1e-8 and segment[2][0] == "lane"]
        if previous and car.distance < previous[-1][0]:
            return None
    return connection.maneuver.kind


def _temporary_winner_path_clear(car, movement, cars, occupancy, coordinator):
    """Check physical space without re-applying conservative social gaps.

    A temporary winner may break a right-of-way tie, but it may not drive into
    a bumper, a committed movement, or an occupied merge point.  Four feet is
    the same small physical margin used by the final same-route travel guard.
    """
    if movement is None or not coordinator.can_claim_temporary_winner(
            car.id, movement[2]):
        return False
    lead_gap = occupancy.lead_gap(car, TEST_CAR_LOOKAHEAD)
    if lead_gap is not None and lead_gap < 4.0:
        return False
    exit_gap = occupancy.gap_from(car, movement[1], TEST_CAR_LOOKAHEAD)
    if exit_gap is not None and exit_gap < 4.0:
        return False
    if movement[2].merge_target is not None:
        observation = observe_merge(car, movement, cars)
        if observation is None or not merge_space_clear(
                car.length, observation.vehicles, observation.reservations):
            return False

    # Preserve the existing chain-signal rule.  A clear first intersection is
    # not a safe escape when the car cannot fit before the next yield.  Check
    # each close following movement with physical (not comfort) clearances.
    chain_end = movement[1]
    for following in car.controlled_movements:
        if following[0] < movement[1]:
            continue
        if following[0] - chain_end >= car.length + 4.0:
            break
        if not coordinator.can_claim_temporary_winner(car.id, following[2]):
            return False
        following_exit = occupancy.gap_from(car, following[1], TEST_CAR_LOOKAHEAD)
        if following_exit is not None and following_exit < 4.0:
            return False
        if following[2].merge_target is not None:
            observation = observe_merge(car, following, cars)
            if observation is None or not merge_space_clear(
                    car.length, observation.vehicles, observation.reservations):
                return False
        chain_end = following[1]
    return True
