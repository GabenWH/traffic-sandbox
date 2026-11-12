"""Projection-independent construction preview descriptions.

All editor projections consume these world-space primitives.  No world mutation
is permitted while building a preview.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

Point2 = tuple[float, float]
Projection = Literal["2d", "3d"]


@dataclass(frozen=True)
class ConstructionPreview:
    kind: Literal["road", "building"]
    vertices: tuple[Point2, ...]
    elevation: tuple[float, ...]
    width: float
    template_id: str

    def __post_init__(self) -> None:
        if not self.template_id or self.width <= 0 or not isfinite(self.width):
            raise ValueError("Invalid construction preview dimensions or template")
        if len(self.vertices) != len(self.elevation):
            raise ValueError("Preview vertex/elevation counts differ")
        if any(not all(isfinite(c) for c in p) for p in self.vertices):
            raise ValueError("Non-finite preview vertex")
        if any(not isfinite(z) for z in self.elevation):
            raise ValueError("Non-finite preview elevation")

    def for_projection(self, projection: Projection) -> "ConstructionPreview":
        if projection not in ("2d", "3d"):
            raise ValueError(f"Unsupported projection: {projection}")
        return self


def road_preview(template_id: str, points: list[Point2],
                 elevations: list[float], pointer: Point2 | None,
                 pointer_elevation: float, lane_width: float,
                 forward_lanes: int, reverse_lanes: int) -> ConstructionPreview:
    if min(forward_lanes, reverse_lanes) < 0 or forward_lanes + reverse_lanes < 1:
        raise ValueError("Road preview requires positive total lane count")
    if len(points) != len(elevations):
        raise ValueError("Road vertices and elevations must correspond")
    vertices = list(points)
    heights = list(elevations)
    if pointer is not None and (not vertices or pointer != vertices[-1]):
        vertices.append(pointer)
        heights.append(pointer_elevation)
    return ConstructionPreview("road", tuple(vertices), tuple(heights),
                               lane_width * (forward_lanes + reverse_lanes), template_id)


def building_preview(template_id: str, center: Point2, width: float,
                     depth: float, elevation: float = 0.0) -> ConstructionPreview:
    if depth <= 0 or not isfinite(depth):
        raise ValueError("Building depth must be positive and finite")
    x, y = center
    corners = ((x-width/2, y-depth/2), (x+width/2, y-depth/2),
               (x+width/2, y+depth/2), (x-width/2, y+depth/2))
    return ConstructionPreview("building", corners, (elevation,) * 4,
                               width, template_id)
