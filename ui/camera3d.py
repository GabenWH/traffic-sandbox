"""Camera controls and screen-ray placement math for the 3D map."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin


Point3 = tuple[float, float, float]
Point2 = tuple[float, float]


@dataclass
class OrbitCamera:
    target: Point3
    yaw: float = 45.0
    pitch: float = 50.0
    distance: float = 1400.0

    @property
    def position(self) -> Point3:
        yaw, pitch = radians(self.yaw), radians(self.pitch)
        horizontal = cos(pitch) * self.distance
        return (
            self.target[0] + cos(yaw) * horizontal,
            self.target[1] + sin(yaw) * horizontal,
            self.target[2] + sin(pitch) * self.distance,
        )

    def rotate(self, yaw_change: float, pitch_change: float) -> None:
        self.yaw = (self.yaw + yaw_change) % 360
        self.pitch = max(10.0, min(85.0, self.pitch + pitch_change))

    def zoom(self, factor: float) -> None:
        self.distance = max(60.0, min(10000.0, self.distance * factor))


def ray_to_height(origin: Point3, direction: Point3, elevation: float) -> Point2 | None:
    """Intersect a forward screen ray with a horizontal construction plane."""
    if abs(direction[2]) < 1e-9:
        return None
    progress = (elevation - origin[2]) / direction[2]
    if progress < 0:
        return None
    return (origin[0] + direction[0] * progress,
            origin[1] + direction[1] * progress)
