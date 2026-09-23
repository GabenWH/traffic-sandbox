"""Pure geometry shared by the 3D road renderer."""

from __future__ import annotations

from math import hypot

from models import Road


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
