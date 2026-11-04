"""Persistent parking geometry in world feet, independent of road actors."""
from dataclasses import dataclass, field
from math import cos, sin, dist, isfinite, pi

from building_footprints import contains_point, distance_to_segment, open_ring


def oriented_rectangle(center, heading, length, width):
    x, y = center
    fx, fy = heading
    return [(x + fx*f*length/2 - fy*s*width/2,
             y + fy*f*length/2 + fx*s*width/2)
            for f, s in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def bounds(polygon):
    xs, ys = zip(*polygon)
    return min(xs), min(ys), max(xs), max(ys)


def polygons_overlap(first, second):
    """Include touching edges, so clearance checks cannot miss thin crossings."""
    a, b = open_ring(first), open_ring(second)
    ax, ay, ar, ab = bounds(a)
    bx, by, br, bb = bounds(b)
    if ar < bx or br < ax or ab < by or bb < ay:
        return False
    if any(contains_point(a, p) for p in b) or any(contains_point(b, p) for p in a):
        return True
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    for p, q in zip(a, a[1:]+a[:1]):
        for r, s in zip(b, b[1:]+b[:1]):
            if cross(p,q,r)*cross(p,q,s) < 0 and cross(r,s,p)*cross(r,s,q) < 0:
                return True
    return False


@dataclass(frozen=True)
class ParkingSpace:
    id: str
    position: tuple[float, float]
    angle: float = pi/2
    length: float = 20.0
    width: float = 10.0

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('Parking space needs an ID')
        if (len(self.position) != 2 or
                not all(isfinite(n) for n in (*self.position, self.angle, self.length, self.width)) or
                self.length <= 0 or self.width <= 0):
            raise ValueError('Parking space geometry must be finite and positive')

    @property
    def heading(self):
        return cos(self.angle), sin(self.angle)

    @property
    def corners(self):
        return oriented_rectangle(self.position, self.heading, self.length, self.width)

    def fits(self, length, width):
        # One foot at each end and side remains clear of adjacent vehicles.
        return length > 0 and width > 0 and length+2 <= self.length and width+2 <= self.width


@dataclass
class ParkingLot:
    id: str
    spaces: list[ParkingSpace] = field(default_factory=list)
    surface: list[tuple[float, float]] = field(default_factory=list)
    driveway: list[tuple[float, float]] = field(default_factory=list)
    road_id: str | None = None
    inferred: bool = True

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('Parking lot needs an ID')
        if len({s.id for s in self.spaces}) != len(self.spaces):
            raise ValueError('Duplicate parking space ID')
        for i, space in enumerate(self.spaces):
            if any(polygons_overlap(space.corners, other.corners) for other in self.spaces[i+1:]):
                raise ValueError('Parking spaces overlap')
        if any(len(p) != 2 or not all(isfinite(n) for n in p) for p in self.surface+self.driveway):
            raise ValueError('Parking lot coordinates must be finite')
        if self.surface and len(self.surface) < 3:
            raise ValueError('Parking lot surface needs a polygon')
        if self.surface and any(not contains_point(self.surface, p) for s in self.spaces for p in s.corners):
            raise ValueError('Parking space is outside its lot surface')
        if self.road_id is not None and len(self.driveway) < 2:
            raise ValueError('A connected parking lot needs a driveway')

    @property
    def capacity(self):
        return len(self.spaces)

    def space(self, ident):
        return next((s for s in self.spaces if s.id == ident), None)

    @property
    def driveway_surfaces(self):
        surfaces = []
        for a,b in zip(self.driveway, self.driveway[1:]):
            length = dist(a,b)
            if length > 1e-7:
                surfaces.append(oriented_rectangle(((a[0]+b[0])/2,(a[1]+b[1])/2),
                    ((b[0]-a[0])/length,(b[1]-a[1])/length),length,10))
        return surfaces
