"""Traffic data objects and geometry helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import dist


Point = tuple[float, float]

@dataclass
class Lane:
    """An ordered centre-line for traffic, ending at an exit point."""

    name: str
    points: list[Point]
    exit: Point
    following_gap: float = 85.0
    next_lane: str | None = None

    def nearest_point_index(self, position: Point) -> int:
        return min(range(len(self.points)), key=lambda index: dist(position, self.points[index]))

    def distance_to(self, position: Point) -> float:
        """Return the shortest distance from a point to this lane centre-line."""
        closest = float("inf")
        for start, end in zip(self.points, self.points[1:]):
            segment_x, segment_y = end[0] - start[0], end[1] - start[1]
            segment_length_squared = segment_x ** 2 + segment_y ** 2
            if segment_length_squared == 0:
                closest = min(closest, dist(position, start))
                continue
            progress = (
                (position[0] - start[0]) * segment_x
                + (position[1] - start[1]) * segment_y
            ) / segment_length_squared
            progress = max(0.0, min(1.0, progress))
            nearest = (start[0] + progress * segment_x, start[1] + progress * segment_y)
            closest = min(closest, dist(position, nearest))
        return closest


@dataclass
class SpeedLimit:
    """A posted speed limit that applies from its position onward in one lane."""

    speed: float  # miles per hour
    lane: Lane
    x: float
    y: float

@dataclass
class Road:
    x: float
    y: float
    lanes: list[Lane]

@dataclass
class Car:
    lane: Lane
    x: float
    y: float
    speed: float
    cruise_speed: float
    color: str
    acceleration: float = 0.0
    next_point: int = 1
    length: int = 14
    width: int = 6
    item: int | None = None
    detail_items: list[int] = field(default_factory=list)
    merge_realness: float = 0.0
    speed_preference_mph: float = 0.0


@dataclass(frozen=True)
class FollowingTarget:
    """A real leader or a gradually-solidifying leader from another lane."""

    car: Car
    strength: float
    is_phantom: bool = False


def cubic_bezier_points(
    start: Point, control_one: Point, control_two: Point, end: Point, steps: int = 18
) -> list[Point]:
    """Return points on a cubic Bézier curve, excluding the starting point."""
    points = []
    for index in range(1, steps + 1):
        t = index / steps
        inverse_t = 1 - t
        x = (
            inverse_t ** 3 * start[0]
            + 3 * inverse_t ** 2 * t * control_one[0]
            + 3 * inverse_t * t ** 2 * control_two[0]
            + t ** 3 * end[0]
        )
        y = (
            inverse_t ** 3 * start[1]
            + 3 * inverse_t ** 2 * t * control_one[1]
            + 3 * inverse_t * t ** 2 * control_two[1]
            + t ** 3 * end[1]
        )
        points.append((x, y))
    return points
