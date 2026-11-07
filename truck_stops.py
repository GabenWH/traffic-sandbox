"""Physical loading stops shared by fleet state and native lane occupancy."""
from dataclasses import dataclass, field
from math import dist, isfinite

from mobility import LaneTraversal, lane_position_at_distance, nearest_lane_position
from models import Lane, polyline_length
from traffic_route_state import RouteGeometry


def route_end_position(route):
    """Return the actual terminal lane position, never a site's nearest lane."""
    if not route.edges:
        return None
    edge = route.edges[-1]
    if edge.kind != 'lane':
        return None
    if isinstance(edge.value, LaneTraversal):
        lane, point = edge.value.lane, edge.value.points[-1]
    elif isinstance(edge.value, Lane):
        lane, point = edge.value, edge.value.points[-1]
    else:
        return None
    position, separation = nearest_lane_position(lane, point)
    return position if separation < 1e-6 else None


def loading_position(position, length):
    """Choose a nearby straight run, leaving four feet beyond both body ends.

    A stop can move at most one truck length plus eight feet along this lane.
    Every direction change bounds a run; collinear vertices do not. Returning
    None keeps loading out of tight bends rather than relocating it far away.
    """
    if not isfinite(length) or length <= 0:
        raise ValueError('Truck length must be positive and finite')
    margin = length / 2 + 4
    runs = []
    start = travelled = 0.0
    heading = None
    for a, b in zip(position.lane.points, position.lane.points[1:]):
        segment_length = dist(a, b)
        if not segment_length:
            continue
        direction = ((b[0]-a[0])/segment_length, (b[1]-a[1])/segment_length)
        if heading is None:
            heading = direction
        elif dist(direction, heading) > 1e-9:
            runs.append((start, travelled))
            start, heading = travelled, direction
        travelled += segment_length
    if heading is not None:
        runs.append((start, travelled))
    candidates = []
    for start, end in runs:
        low, high = start + margin, end - margin
        if high < low:
            continue
        candidate = max(low, min(high, position.distance))
        displacement = abs(candidate-position.distance)
        if displacement <= length + 8 + 1e-8:
            candidates.append((displacement, candidate))
    nearest = min(candidates, default=None)
    return None if nearest is None else lane_position_at_distance(position.lane, nearest[1])


@dataclass(frozen=True)
class LaneObstacle:
    """An immutable parked body; only explicit changes rebuild its lane entry."""
    id: str
    lane_position: object
    length: float
    width: float
    heading: tuple | None = None
    position: tuple = field(init=False)
    distance: float = field(init=False)
    total_length: float = field(init=False)
    route_segments: tuple = field(init=False)
    speed: float = field(default=0, init=False)

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('A lane obstacle needs a vehicle ID')
        if any(not isfinite(size) or size <= 0 for size in (self.length, self.width)):
            raise ValueError('Lane obstacle dimensions must be positive and finite')
        lane = self.lane_position.lane
        points = tuple(lane.points)
        total = polyline_length(points)
        if len(points) < 2 or total <= 0:
            raise ValueError('A lane obstacle needs a non-degenerate lane')
        position, heading = RouteGeometry().position_and_heading(points, self.lane_position.distance)
        if dist(position, self.lane_position.point) > 1e-6:
            raise ValueError('Lane obstacle point does not match its lane distance')
        if self.heading is not None:
            try:
                supplied = tuple(float(value) for value in self.heading)
            except (TypeError, ValueError):
                raise ValueError('Lane obstacle heading must follow its lane') from None
            if len(supplied) != 2 or not all(isfinite(value) for value in supplied):
                raise ValueError('Lane obstacle heading must follow its lane')
            # At an exact polyline corner, arrival and departure use the two
            # adjacent tangents. Retain the saved body orientation on restore.
            travelled = 0.0
            tangents = []
            for a, b in zip(points, points[1:]):
                length = dist(a, b)
                if length and travelled - 1e-6 <= self.lane_position.distance <= travelled + length + 1e-6:
                    tangents.append(((b[0]-a[0])/length, (b[1]-a[1])/length))
                travelled += length
            if not any(dist(supplied, tangent) < 1e-6 for tangent in tangents):
                raise ValueError('Lane obstacle heading must follow its lane')
            heading = supplied
        for name, value in (('position', position), ('heading', heading),
                ('distance', self.lane_position.distance), ('total_length', total),
                ('route_segments', ((0.0, total, ('lane', lane.id), 0.0),))):
            object.__setattr__(self, name, value)

    def occupancy_position(self):
        return ('lane', self.lane_position.lane.id), self.distance
