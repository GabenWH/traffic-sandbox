"""Pure geometry shared by the 3D road renderer."""

from __future__ import annotations

from math import atan2, ceil, cos, dist, hypot, pi, sin, sqrt

from models import Intersection, IntersectionKind, Road
from roundabouts import ROUNDABOUT_OUTER_BAND_WIDTH, island_radius


Point3 = tuple[float, float, float]
DeckQuad = tuple[Point3, Point3, Point3, Point3]
_TAU = 2 * pi
_BAND_SAMPLE_SPACING = 1.0
_BAND_CUTOUT_MARGIN = 0.15


def _append_wrapped_interval(
    intervals: list[tuple[float, float]], start: float, end: float,
) -> None:
    """Append an angular interval, splitting it where it wraps around 0."""
    width = end - start
    if width >= _TAU:
        intervals.append((0.0, _TAU))
        return
    start %= _TAU
    end = start + width
    if end <= _TAU:
        intervals.append((start, end))
    else:
        intervals.extend(((start, _TAU), (0.0, end - _TAU)))


def _roundabout_road_intervals(
    junction: Intersection, inner_radius: float, outer_radius: float,
) -> list[tuple[float, float]]:
    """Return angular spans where connected road decks cross the outer band."""
    intervals: list[tuple[float, float]] = []
    cx, cy = junction.position
    for road in junction.connected_roads:
        half_width = road.width / 2
        if half_width <= 0:
            continue
        for start, end in zip(road.centerline, road.centerline[1:]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = hypot(dx, dy)
            if length == 0:
                continue
            normal_x = -dy / length * half_width
            normal_y = dx / length * half_width
            steps = max(1, ceil(length / _BAND_SAMPLE_SPACING))
            for step in range(steps + 1):
                fraction = step / steps
                x = start[0] + dx * fraction
                y = start[1] + dy * fraction
                center_radius = hypot(x - cx, y - cy)
                if (
                    center_radius + half_width < inner_radius - _BAND_CUTOUT_MARGIN
                    or center_radius - half_width > outer_radius + _BAND_CUTOUT_MARGIN
                ):
                    continue

                left = (x + normal_x, y + normal_y)
                right = (x - normal_x, y - normal_y)
                cross_section = ((x, y), left, right)
                if not any(
                    inner_radius - _BAND_CUTOUT_MARGIN
                    <= hypot(point[0] - cx, point[1] - cy)
                    <= outer_radius + _BAND_CUTOUT_MARGIN
                    for point in cross_section
                ):
                    continue

                center_angle = atan2(y - cy, x - cx)
                offsets = [
                    (atan2(point[1] - cy, point[0] - cx) - center_angle + pi)
                    % _TAU - pi
                    for point in cross_section
                ]
                angular_padding = (
                    _BAND_SAMPLE_SPACING / 2 + _BAND_CUTOUT_MARGIN
                ) / max(center_radius, 1.0)
                _append_wrapped_interval(
                    intervals,
                    center_angle + min(offsets) - angular_padding,
                    center_angle + max(offsets) + angular_padding,
                )

    if not intervals:
        return []
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1e-9:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _visible_band_intervals(
    blocked: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Return the angular spans left visible after cutting road approaches."""
    if not blocked:
        return [(0.0, _TAU)]
    visible: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in blocked:
        if start > cursor + 1e-9:
            visible.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < _TAU - 1e-9:
        visible.append((cursor, _TAU))
    return visible


def _allocate_band_segments(
    intervals: list[tuple[float, float]], segments: int,
) -> list[int]:
    """Distribute band quads across its remaining angular spans."""
    if not intervals:
        return []
    target = max(segments, len(intervals))
    total_angle = sum(end - start for start, end in intervals)
    exact = [target * (end - start) / total_angle for start, end in intervals]
    counts = [max(1, int(count)) for count in exact]
    while sum(counts) < target:
        index = max(
            range(len(counts)),
            key=lambda item: exact[item] - counts[item],
        )
        counts[index] += 1
    return counts


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return the counter-clockwise convex hull of the supplied points."""
    ordered = sorted(set(points))
    if len(ordered) < 3:
        return []

    def turn(
        origin: tuple[float, float], first: tuple[float, float],
        second: tuple[float, float],
    ) -> float:
        return (
            (first[0] - origin[0]) * (second[1] - origin[1])
            - (first[1] - origin[1]) * (second[0] - origin[0])
        )

    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    return hull if len(hull) >= 3 else []


def _road_cross_section_at_radius(
    road: Road, junction: Intersection,
) -> list[tuple[float, float]]:
    """Find a connected road's side edges at the intersection radius."""
    if len(road.centerline) < 2 or road.width <= 0:
        return []
    points = road.centerline
    if dist(points[-1], junction.position) < dist(points[0], junction.position):
        points = list(reversed(points))
    cx, cy = junction.position
    radius = junction.radius
    half_width = road.width / 2

    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            continue
        offset_x, offset_y = start[0] - cx, start[1] - cy
        b = 2 * (offset_x * dx + offset_y * dy)
        c = offset_x * offset_x + offset_y * offset_y - radius * radius
        discriminant = b * b - 4 * length_squared * c
        if discriminant < 0:
            continue
        root = sqrt(discriminant)
        for fraction in sorted(((-b - root) / (2 * length_squared),
                                (-b + root) / (2 * length_squared))):
            if not 0 <= fraction <= 1:
                continue
            x, y = start[0] + dx * fraction, start[1] + dy * fraction
            length = sqrt(length_squared)
            normal_x, normal_y = -dy / length, dx / length
            return [
                (x - normal_x * half_width, y - normal_y * half_width),
                (x + normal_x * half_width, y + normal_y * half_width),
            ]

    # A short or customized road may not reach the nominal intersection radius.
    start, end = points[-2:]
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    if length == 0:
        return []
    normal_x, normal_y = -dy / length, dx / length
    return [
        (end[0] - normal_x * half_width, end[1] - normal_y * half_width),
        (end[0] + normal_x * half_width, end[1] + normal_y * half_width),
    ]


def _standard_intersection_polygon(
    junction: Intersection,
) -> list[tuple[float, float]]:
    boundary = [
        point
        for road in junction.connected_roads
        for point in _road_cross_section_at_radius(road, junction)
    ]
    return _convex_hull(boundary)


def _circle_intersections(
    start: tuple[float, float], end: tuple[float, float],
    center: tuple[float, float], radius: float,
) -> list[float]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    offset_x, offset_y = start[0] - center[0], start[1] - center[1]
    a = dx * dx + dy * dy
    if a == 0:
        return []
    b = 2 * (offset_x * dx + offset_y * dy)
    c = offset_x * offset_x + offset_y * offset_y - radius * radius
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return []
    root = sqrt(discriminant)
    return sorted({
        max(0.0, min(1.0, fraction))
        for fraction in ((-b - root) / (2 * a), (-b + root) / (2 * a))
        if -1e-9 <= fraction <= 1 + 1e-9
    })


def _polygon_intersections(
    start: tuple[float, float], end: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> list[float]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    fractions: list[float] = []
    for first, second in zip(polygon, (*polygon[1:], polygon[0])):
        edge_x, edge_y = second[0] - first[0], second[1] - first[1]
        denominator = dx * edge_y - dy * edge_x
        if abs(denominator) < 1e-12:
            continue
        offset_x, offset_y = first[0] - start[0], first[1] - start[1]
        fraction = (offset_x * edge_y - offset_y * edge_x) / denominator
        edge_fraction = (offset_x * dy - offset_y * dx) / denominator
        if -1e-9 <= fraction <= 1 + 1e-9 and -1e-9 <= edge_fraction <= 1 + 1e-9:
            fractions.append(max(0.0, min(1.0, fraction)))
    return fractions


def _point_in_polygon(
    point: tuple[float, float], polygon: list[tuple[float, float]],
) -> bool:
    x, y = point
    inside = False
    for first, second in zip(polygon, (*polygon[1:], polygon[0])):
        cross = (
            (second[0] - first[0]) * (y - first[1])
            - (second[1] - first[1]) * (x - first[0])
        )
        if (
            abs(cross) < 1e-8
            and min(first[0], second[0]) - 1e-8 <= x <= max(first[0], second[0]) + 1e-8
            and min(first[1], second[1]) - 1e-8 <= y <= max(first[1], second[1]) + 1e-8
        ):
            return True
        if (first[1] > y) != (second[1] > y):
            boundary_x = first[0] + (y - first[1]) * (
                second[0] - first[0]
            ) / (second[1] - first[1])
            if x < boundary_x:
                inside = not inside
    return inside


def road_divider_runs(
    road: Road, intersections: list[Intersection],
) -> list[list[Point3]]:
    """Split a road center divider around its connected intersection shapes."""
    if len(road.centerline) < 2:
        return []
    circles: list[tuple[tuple[float, float], float]] = []
    polygons: list[list[tuple[float, float]]] = []
    for junction in intersections:
        if not any(connected is road for connected in junction.connected_roads):
            continue
        if junction.kind is IntersectionKind.ROUNDABOUT:
            circles.append((
                junction.position,
                junction.radius + ROUNDABOUT_OUTER_BAND_WIDTH,
            ))
        elif junction.kind is IntersectionKind.CUL_DE_SAC:
            circles.append((junction.position, junction.radius))
        elif polygon := _standard_intersection_polygon(junction):
            polygons.append(polygon)

    if not circles and not polygons:
        return [[
            (point[0], point[1], height)
            for point, height in zip(road.centerline, road.elevations)
        ]]

    visible_edges: list[tuple[Point3, Point3]] = []
    for index, (start, end) in enumerate(zip(road.centerline, road.centerline[1:])):
        dx, dy = end[0] - start[0], end[1] - start[1]
        cuts = [0.0, 1.0]
        for center, radius in circles:
            cuts.extend(_circle_intersections(start, end, center, radius))
        for polygon in polygons:
            cuts.extend(_polygon_intersections(start, end, polygon))
        ordered_cuts: list[float] = []
        for fraction in sorted(cuts):
            if not ordered_cuts or fraction - ordered_cuts[-1] > 1e-9:
                ordered_cuts.append(fraction)

        start_height, end_height = road.elevations[index:index + 2]
        for first, second in zip(ordered_cuts, ordered_cuts[1:]):
            if second - first <= 1e-9:
                continue
            middle = (first + second) / 2
            sample = (start[0] + dx * middle, start[1] + dy * middle)
            inside_circle = any(
                dist(sample, center) <= radius + 1e-9
                for center, radius in circles
            )
            inside_polygon = any(
                _point_in_polygon(sample, polygon) for polygon in polygons
            )
            if inside_circle or inside_polygon:
                continue

            visible_edges.append((
                (
                    start[0] + dx * first,
                    start[1] + dy * first,
                    start_height + (end_height - start_height) * first,
                ),
                (
                    start[0] + dx * second,
                    start[1] + dy * second,
                    start_height + (end_height - start_height) * second,
                ),
            ))

    runs: list[list[Point3]] = []
    for start, end in visible_edges:
        if runs and all(abs(runs[-1][-1][axis] - start[axis]) <= 1e-7 for axis in range(3)):
            runs[-1].append(end)
        else:
            runs.append([start, end])
    return runs


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
    # Keep the apron just below connected road ends; the outer sand band is
    # cut away wherever those road decks cross it.
    road_height = max(connected_heights) - 0.02
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
        island.append((point(0, a, island_height), point(island_outer_radius, a, island_height),
                       point(island_outer_radius, b, island_height), point(0, b, island_height)))

    visible_band = _visible_band_intervals(
        _roundabout_road_intervals(junction, outer, outer_band_radius),
    )
    for (start, end), count in zip(
        visible_band, _allocate_band_segments(visible_band, segments),
    ):
        for index in range(count):
            a = start + (end - start) * index / count
            b = start + (end - start) * (index + 1) / count
            outer_band.append((
                point(outer, a, road_height),
                point(outer_band_radius, a, road_height),
                point(outer_band_radius, b, road_height),
                point(outer, b, road_height),
            ))
    return road, outer_band, island
