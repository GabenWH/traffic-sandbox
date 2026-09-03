"""Temporary routed traffic generated between selected city junctions."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from math import dist, isfinite
import random

from city import CityMap
from car_brain import CarBrain, CarObservation
from intersection_controls import AllWayStopCoordinator
from mobility import (
    LaneTraversal,
    MobilityLink,
    MobilityNode,
    PortTraversal,
    nearest_lane_position,
    vehicle_link_points,
    vehicle_route_points,
)
from models import ControlType, Intersection, Lane, LaneConnection, Point, polyline_length
from pathfinding import Path
from traffic_occupancy import TrafficOccupancyIndex
from units import mph_to_pixels_per_second


TEST_CAR_SPEED_MPH = 25.0
TEST_SPAWN_INTERVAL = 1.5
TEST_TRAFFIC_LIMIT = 60
TEST_CAR_ACCELERATION = 10.0
TEST_CAR_BRAKING = 24.0
TEST_CAR_FOLLOWING_GAP = 22.0
TEST_CAR_LOOKAHEAD = 128.0
_car_ids = count(1)


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
    occupancy: TrafficOccupancyIndex = field(
        default_factory=TrafficOccupancyIndex, repr=False,
    )

    colors = ("#ff5b72", "#37e6ff", "#f7d154", "#7fea8c", "#c98cff")

    def __post_init__(self) -> None:
        if not isfinite(self.spawn_interval) or self.spawn_interval <= 0:
            raise ValueError("Test-traffic spawn interval must be positive")
        if self.max_cars < 1:
            raise ValueError("Test traffic must allow at least one car")
        if not isfinite(self.speed_mph) or self.speed_mph <= 0:
            raise ValueError("Test-traffic speed must be positive")

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
        car = RoutedTestCar(
            source_id=source.id,
            destination_id=destination.id,
            route=route,
            points=points,
            speed=mph_to_pixels_per_second(self.speed_mph),
            color=self.rng.choice(self.colors),
        )
        self.occupancy.rebuild(self.cars)
        spawn_gap = self.occupancy.lead_gap(car, TEST_CAR_FOLLOWING_GAP + car.length)
        if spawn_gap is not None and spawn_gap < TEST_CAR_FOLLOWING_GAP:
            return None
        self.cars.append(car)
        return car

    def update(self, city_map: CityMap, elapsed_seconds: float) -> list[RoutedTestCar]:
        """Spawn and advance test cars, returning cars that reached a sink."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
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

        self.occupancy.rebuild(self.cars)
        completed: list[RoutedTestCar] = []
        for car in list(self.cars):
            route_movement = _next_route_movement(car)
            movement = _next_controlled_movement(car)
            has_claim = (
                movement is not None
                and self.stop_coordinator.has_claim(car.id, movement[2])
            )
            inside = (
                movement is not None
                and has_claim
                and movement[0] <= car.distance < movement[1]
            )
            distance_to_stop = (
                max(0.0, movement[0] - car.length / 2 - car.distance)
                if movement is not None and not has_claim
                else None
            )
            if movement is not None and distance_to_stop is not None and distance_to_stop <= 0.05 and car.speed <= 0.1:
                self.stop_coordinator.observe_stop(car.id, movement[2], self.elapsed_time)
            priority = (
                movement is not None
                and self.stop_coordinator.can_claim(car.id, movement[2])
            )
            lead_distance = self.occupancy.lead_gap(car, TEST_CAR_LOOKAHEAD)
            decision = car.brain.decide(
                CarObservation(
                    cruise_speed=mph_to_pixels_per_second(self.speed_mph),
                    speed=car.speed,
                    distance_to_stop=distance_to_stop,
                    must_stop=movement is not None and not has_claim,
                    has_priority=priority,
                    lead_car_distance=lead_distance,
                    following_gap=TEST_CAR_FOLLOWING_GAP,
                    inside_intersection=inside,
                    next_maneuver=(
                        route_movement[2].maneuver.kind
                        if route_movement is not None else None
                    ),
                    distance_to_maneuver=(
                        max(0.0, route_movement[0] - car.distance)
                        if route_movement is not None else None
                    ),
                    inside_maneuver=(
                        route_movement is not None
                        and route_movement[0] <= car.distance < route_movement[1]
                    ),
                ),
                elapsed_seconds,
            )
            if decision.register_stop and movement is not None:
                self.stop_coordinator.observe_stop(car.id, movement[2], self.elapsed_time)
            if decision.request_claim and movement is not None:
                has_claim = self.stop_coordinator.claim(car.id, movement[2])
                if has_claim:
                    car._claimed_movement = movement[2]

            speed_delta = decision.desired_speed - car.speed
            limit = (TEST_CAR_ACCELERATION if speed_delta > 0 else TEST_CAR_BRAKING) * elapsed_seconds
            car.speed += max(-limit, min(limit, speed_delta))
            travel = car.speed * elapsed_seconds
            if lead_distance is not None:
                travel = min(
                    travel,
                    max(0.0, lead_distance - TEST_CAR_FOLLOWING_GAP),
                )
                if travel == 0.0:
                    car.speed = 0.0
            if movement is not None and not has_claim:
                stop_distance = movement[0] - car.length / 2
                travel = min(travel, max(0.0, stop_distance - car.distance))
                if travel == 0.0:
                    car.speed = 0.0
            alive = car.advance(travel / car.speed if car.speed > 0 else 0.0)
            if movement is not None and has_claim and car.distance >= movement[1]:
                self.stop_coordinator.release(car.id)
                car._claimed_movement = None
            if not alive:
                completed.append(car)
                self.stop_coordinator.forget_car(car.id)
        for car in completed:
            self.cars.remove(car)
        return completed

    def clear_cars(self) -> list[RoutedTestCar]:
        removed = list(self.cars)
        for car in removed:
            self.stop_coordinator.forget_car(car.id)
            car._claimed_movement = None
        self.cars.clear()
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
            result.append((distance_along, distance_along + length, link.value))
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
    car: RoutedTestCar,
) -> tuple[float, float, LaneConnection] | None:
    return next(
        (
            movement for movement in car.controlled_movements
            if car.distance < movement[1]
            and movement[2].control.kind is ControlType.STOP
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
