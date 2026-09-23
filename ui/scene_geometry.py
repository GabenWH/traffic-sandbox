"""Pure geometry shared by the 3D road renderer."""

from __future__ import annotations

from math import cos, dist, hypot, pi, sin

from models import Intersection, IntersectionKind, Road
from roundabouts import ROUNDABOUT_OUTER_BAND_WIDTH, island_radius


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


def roundabout_deck_quads(
    junction: Intersection, segments: int = 32,
) -> tuple[list[DeckQuad], list[DeckQuad], list[DeckQuad]]:
    """Return a raised asphalt apron and its central island."""
    if segments < 3:
        raise ValueError("A roundabout needs at least three segments")
    if junction.kind is not IntersectionKind.ROUNDABOUT:
        return [], [], []
    cx, cy = junction.position
    outer = junction.radius
    outer_band_radius = outer + ROUNDABOUT_OUTER_BAND_WIDTH
    island_outer_radius = island_radius(junction)
    connected_heights = [junction.elevation]
    for road in junction.connected_roads:
        endpoint = 0 if dist(road.centerline[0], junction.position) <= dist(
            road.centerline[-1], junction.position
        ) else -1
        connected_heights.append(road.elevations[endpoint])
    # Lift the continuous apron above connected road decks and their markings,
    # so their surfaces do not show through the roundabout.
    road_height = max(connected_heights) + 0.25
    island_height = road_height + 1.5
    road: list[DeckQuad] = []
    outer_band: list[DeckQuad] = []
    island: list[DeckQuad] = []
    for i in range(segments):
        a, b = 2 * pi * i / segments, 2 * pi * (i + 1) / segments
        def point(radius: float, angle: float, z: float) -> Point3:
            return (cx + radius * cos(angle), cy + radius * sin(angle), z)
        road.append((point(0, a, road_height), point(outer, a, road_height),
                     point(outer, b, road_height), point(0, b, road_height)))
        outer_band.append((point(outer, a, road_height), point(outer_band_radius, a, road_height),
                           point(outer_band_radius, b, road_height), point(outer, b, road_height)))
        island.append((point(0, a, island_height), point(island_outer_radius, a, island_height),
                       point(island_outer_radius, b, island_height), point(0, b, island_height)))
    return road, outer_band, island
