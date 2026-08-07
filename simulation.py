"""Headless traffic rules, spawning, merge behavior, and statistics."""

from __future__ import annotations

import random
from math import dist

from config import LANE_HEIGHT, MERGE_END, MERGE_START, PIXELS_PER_MILE, POST_MERGE_END, ROAD_TOP
from models import Car, FollowingTarget, Lane, SpeedLimit, cubic_bezier_points


class TrafficSimulation:
    """Own the road network and advance all cars without UI dependencies."""

    colors = ("#e74c3c", "#3498db", "#f1c40f", "#2ecc71", "#9b59b6", "#ecf0f1")
    default_speed_limit_mph = 55.0

    def __init__(self) -> None:
        self.max_cars = 12
        self.simulation_time = 0.0
        self.exit_times: list[float] = []
        self.cars: list[Car] = []
        self.speed_limits: list[SpeedLimit] = []
        self.history: list[tuple[float, float, float]] = []
        self.events: list[tuple[float, str]] = []
        self._next_sample_time = 0.0
        upper_y = ROAD_TOP + LANE_HEIGHT / 2
        lower_y = upper_y + LANE_HEIGHT
        closing_points = [(-70, lower_y), (MERGE_START, lower_y)]
        closing_points.extend(cubic_bezier_points(
            (MERGE_START, lower_y), (MERGE_START + 150, lower_y),
            (MERGE_END - 180, upper_y), (MERGE_END, upper_y),
        ))
        self.lanes = [
            Lane("through", [(-70, upper_y), (MERGE_START, upper_y), (MERGE_END, upper_y)],
                 (MERGE_END, upper_y), next_lane="post_merge"),
            Lane("closing", closing_points, (MERGE_END, upper_y), next_lane="post_merge"),
            Lane("post_merge", [(MERGE_END, upper_y), (POST_MERGE_END, upper_y)],
                 (POST_MERGE_END, upper_y)),
        ]
        self.entry_lanes = self.lanes[:2]
        self.spawn_timer = 0.0

    def add_car(self, start_random: bool = False) -> Car:
        lane = random.choice(self.entry_lanes)
        preference = random.uniform(-5.0, 10.0)
        speed = self.mph_to_pixels_per_second(self.default_speed_limit_mph + preference)
        car = Car(
            lane, *lane.points[0], speed, speed, random.choice(self.colors),
            speed_preference_mph=preference,
        )
        if start_random:
            self.advance_car(car, random.uniform(0, 1000))
        self.cars.append(car)
        return car

    @staticmethod
    def mph_to_pixels_per_second(speed_mph: float) -> float:
        return speed_mph * PIXELS_PER_MILE / 3600

    def add_speed_limit(self, speed: float, lane: Lane, x: float, y: float) -> SpeedLimit:
        """Post a limit that applies to cars after they pass this point."""
        speed_limit = SpeedLimit(speed, lane, x, y)
        self.speed_limits.append(speed_limit)
        self.record_event(f"{lane.name} limit {speed:.0f} mph")
        return speed_limit

    def remove_speed_limit(self, speed_limit: SpeedLimit) -> None:
        self.speed_limits.remove(speed_limit)
        self.record_event(f"removed {speed_limit.speed:.0f} mph limit")

    def record_event(self, description: str) -> None:
        self.events.append((self.simulation_time, description))

    def speed_limit_for(self, car: Car) -> float:
        """Return the most recent sign the car has passed in its current lane."""
        applicable = [
            sign for sign in self.speed_limits
            if sign.lane is car.lane and sign.x <= car.x
        ]
        if not applicable:
            return self.default_speed_limit_mph
        return max(applicable, key=lambda sign: sign.x).speed

    def desired_speed_for(self, car: Car) -> float:
        """Apply an individual preference around the current posted limit."""
        return self.mph_to_pixels_per_second(
            max(15.0, self.speed_limit_for(car) + car.speed_preference_mph)
        )

    def advance_car(self, car: Car, distance: float) -> bool:
        while distance > 0 and car.next_point < len(car.lane.points):
            target = car.lane.points[car.next_point]
            segment = dist((car.x, car.y), target)
            if distance < segment:
                ratio = distance / segment
                car.x += (target[0] - car.x) * ratio
                car.y += (target[1] - car.y) * ratio
                return True
            car.x, car.y = target
            distance -= segment
            car.next_point += 1
        return True if car.next_point < len(car.lane.points) else self.transfer_at_exit(car, distance)

    def transfer_at_exit(self, car: Car, remaining_distance: float) -> bool:
        if car.lane.next_lane is None:
            return False
        target_lane = next(lane for lane in self.lanes if lane.name == car.lane.next_lane)
        target_index = target_lane.nearest_point_index(car.lane.exit)
        car.lane = target_lane
        car.x, car.y = target_lane.points[target_index]
        car.next_point = target_index + 1
        return self.advance_car(car, remaining_distance)

    def update_merge_realness(self, car: Car) -> None:
        if car.lane.name == "post_merge":
            car.merge_realness = 1.0
            return
        progress = max(0.0, min(1.0, (car.x - MERGE_START) / (MERGE_END - MERGE_START)))
        car.merge_realness = progress * progress * (3.0 - 2.0 * progress)

    def phantom_strength(self, car: Car, other: Car) -> float:
        if car.lane is other.lane:
            return 1.0
        input_lanes = {"through", "closing"}
        car_is_input = car.lane.name in input_lanes
        other_is_input = other.lane.name in input_lanes
        if not car_is_input and not other_is_input:
            return 0.0
        if car_is_input and other_is_input:
            return max(car.merge_realness, other.merge_realness)
        return (car if car_is_input else other).merge_realness

    def following_gap_for(self, car: Car) -> float:
        if car.lane.name == "post_merge":
            return car.lane.following_gap
        post_merge = next(lane for lane in self.lanes if lane.name == "post_merge")
        return car.lane.following_gap * (1 - car.merge_realness) + post_merge.following_gap * car.merge_realness

    def cars_ahead_of(self, car: Car) -> list[FollowingTarget]:
        targets = []
        for other in self.cars:
            if other is car or other.x <= car.x:
                continue
            strength = self.phantom_strength(car, other)
            if strength > 0:
                targets.append(FollowingTarget(other, strength, car.lane is not other.lane))
        return targets

    def following_acceleration(self, car: Car, targets: list[FollowingTarget]) -> float:
        accelerations = [1.8 * (self.desired_speed_for(car) - car.speed)]
        for target in targets:
            strength = target.strength
            gap = target.car.x - target.car.length * strength - car.x
            response = 0.8 * (gap - self.following_gap_for(car) * strength)
            response += 1.2 * (target.car.speed - car.speed)
            accelerations.append(response * strength)
        return min(accelerations)

    def movement_distance(self, car: Car, dt: float, targets: list[FollowingTarget]) -> float:
        car.acceleration = max(-150.0, min(90.0, car.acceleration))
        car.speed = max(0.0, car.speed + car.acceleration * dt)
        movement = car.speed * dt
        for target in targets:
            strength = target.strength
            safe_gap = max(0.0, target.car.x - target.car.length * strength - 12 * strength - car.x)
            movement = min(movement, movement * (1 - strength) + safe_gap * strength)
        if dt > 0:
            car.speed = movement / dt
        return movement

    def update(self, dt: float) -> list[Car]:
        self.simulation_time += dt
        self.spawn_timer += dt
        if self.spawn_timer > random.uniform(0.75, 1.6) and len(self.cars) < self.max_cars:
            self.add_car()
            self.spawn_timer = 0.0
        for car in self.cars:
            self.update_merge_realness(car)
        exited = []
        for car in sorted(self.cars, key=lambda vehicle: vehicle.x, reverse=True):
            targets = self.cars_ahead_of(car)
            car.acceleration = self.following_acceleration(car, targets)
            if not self.advance_car(car, self.movement_distance(car, dt, targets)):
                exited.append(car)
        for car in exited:
            self.cars.remove(car)
            self.exit_times.append(self.simulation_time)
        if self.simulation_time >= self._next_sample_time:
            self.history.append((self.simulation_time, self.average_speed_mph(), self.exits_per_minute()))
            self._next_sample_time = self.simulation_time + 1.0
        return exited

    def exits_per_minute(self) -> float:
        self.exit_times = [time for time in self.exit_times if time > self.simulation_time - 60]
        return float(len(self.exit_times))

    def average_speed_mph(self) -> float:
        if not self.cars:
            return 0.0
        return sum(car.speed for car in self.cars) / len(self.cars) * 3600 / PIXELS_PER_MILE

    def merge_debug_lines(self) -> list[str]:
        lines = [f"MERGE DEBUG   span: {MERGE_START}–{MERGE_END}"]
        for lane in self.lanes:
            queue = [car for car in self.cars if car.lane is lane and MERGE_START - 100 <= car.x <= MERGE_END + 100]
            lines.append(f"{lane.name}: {len(queue)} nearby car(s)")
            for car in sorted(queue, key=lambda vehicle: vehicle.x, reverse=True):
                lines.append(
                    f"  {lane.name[:8].upper():8} x={car.x:6.1f} speed={car.speed:5.1f}"
                    f" gap={self.following_gap_for(car):5.1f} solid={car.merge_realness:4.2f}"
                )
        return lines
