"""Pure geometry shared by the 3D road renderer."""

from __future__ import annotations

from math import cos, hypot, pi, sin

from models import Intersection, IntersectionKind, Road


Point3 = tuple[float, float, float]
DeckQuad = tuple[Point3, Point3, Point3, Point3]


def road_deck_quads(road: Road) -> list[DeckQuad]:
    """Return a road-width deck quad for each nonzero centerline segment."""
    quads: list[DeckQuad] = []
    half_width = road.width / 2
    for index, (start, end) in enumerate(zip(road.centerline, road.centerline[1:])):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = hypot(dx, dy)
        if length == 0:
            continue
        normal_x, normal_y = -dy / length, dx / length
        offset_x, offset_y = normal_x * half_width, normal_y * half_width
        start_height, end_height = road.elevations[index:index + 2]
        quads.append((
            (start[0] - offset_x, start[1] - offset_y, start_height),
            (start[0] + offset_x, start[1] + offset_y, start_height),
            (end[0] + offset_x, end[1] + offset_y, end_height),
            (end[0] - offset_x, end[1] - offset_y, end_height),
        ))
    return quads


def roundabout_deck_quads(junction: Intersection, segments: int = 32) -> tuple[list[DeckQuad], list[DeckQuad]]:
    """Return an asphalt annulus and a slightly raised central island."""
    if segments < 3:
        raise ValueError("A roundabout needs at least three segments")
    if junction.kind is not IntersectionKind.ROUNDABOUT:
        return [], []
    cx, cy = junction.position
    outer, inner, island_radius = junction.radius, junction.radius * 0.65, junction.radius * 0.43
    road: list[DeckQuad] = []
    island: list[DeckQuad] = []
    for i in range(segments):
        a, b = 2 * pi * i / segments, 2 * pi * (i + 1) / segments
        def point(radius: float, angle: float, z: float) -> Point3:
            return (cx + radius * cos(angle), cy + radius * sin(angle), z)
        road.append((point(inner, a, junction.elevation), point(outer, a, junction.elevation),
                     point(outer, b, junction.elevation), point(inner, b, junction.elevation)))
        island.append((point(0, a, junction.elevation + 1.5), point(island_radius, a, junction.elevation + 1.5),
                       point(island_radius, b, junction.elevation + 1.5), point(0, b, junction.elevation + 1.5)))
    return road, island
