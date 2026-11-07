"""Compile walking routes from road-owned pedestrian lanes.

Junction links remain geometric assumptions rather than validated crossings.
Query endpoints are temporary: no road is split for a building.
"""
from dataclasses import dataclass
from math import dist

from mobility import MobilityLayer
from models import polyline_length, slice_polyline
from threading import Lock

from native_walking import NativeWalkingGraph
from numpy_storage import packed_points,PackedPoints
import numpy as np
from collections.abc import Sequence


@dataclass(frozen=True)
class WalkLink:
    kind: str
    points: tuple


@dataclass(frozen=True)
class WalkingRoute:
    points: tuple
    links: tuple
    length: float
    first_crossing_fraction: float

    def __post_init__(self):
        object.__setattr__(self,'points',packed_points(self.points))
        if not isinstance(self.links,PackedWalkLinks):object.__setattr__(self,'links',PackedWalkLinks(self.links))


class PackedWalkLinks(Sequence):
    """Ragged walking-link coordinates share one numeric point allocation."""
    __slots__=('kinds','kind_codes','offsets','points')
    def __init__(self,links):
        links=tuple(links);self.kinds=tuple(dict.fromkeys(link.kind for link in links))
        codes={name:i for i,name in enumerate(self.kinds)}
        self.kind_codes=np.fromiter((codes[link.kind] for link in links),dtype=np.int16,count=len(links))
        sizes=np.fromiter((len(link.points) for link in links),dtype=np.int32,count=len(links))
        self.offsets=np.empty(len(links)+1,dtype=np.int64);self.offsets[0]=0
        np.cumsum(sizes,out=self.offsets[1:])
        self.points=np.empty((int(self.offsets[-1]),2),dtype=np.float64)
        for i,link in enumerate(links):self.points[self.offsets[i]:self.offsets[i+1]]=np.asarray(link.points).reshape(-1,2)
        for data in (self.kind_codes,self.offsets,self.points):data.flags.writeable=False
    def __len__(self):return len(self.kind_codes)
    def __eq__(self,other):
        if isinstance(other,PackedWalkLinks):
            return (self.kinds==other.kinds and np.array_equal(self.kind_codes,other.kind_codes)
                    and np.array_equal(self.offsets,other.offsets) and np.array_equal(self.points,other.points))
        try:return tuple(self)==tuple(other)
        except TypeError:return False
    def __hash__(self):return hash(tuple(self))
    def __getitem__(self,index):
        if isinstance(index,slice):return tuple(self[i] for i in range(*index.indices(len(self))))
        if index<0:index+=len(self)
        if not 0<=index<len(self):raise IndexError(index)
        return WalkLink(self.kinds[int(self.kind_codes[index])],PackedPoints._view(self.points[self.offsets[index]:self.offsets[index+1]]))


def _node(lane, end):
    return ('pedestrian_lane', lane.id, end)


def _part(points, start, end):
    if start <= end:
        return tuple(slice_polyline(points, start, end))
    return tuple(reversed(slice_polyline(points, end, start)))


class PedestrianNetwork:
    def __init__(self, roads, intersections):
        self.layer = MobilityLayer()
        self._native = None
        self._compile_lock = Lock()
        self.lanes = []
        by_road = {}
        for road in roads:
            by_road[road.id] = road.pedestrian_lanes
            for lane in road.pedestrian_lanes:
                points = lane.points
                self.lanes.append(lane)
                a, b = _node(lane, 'start'), _node(lane, 'end')
                self.layer.positions[a], self.layer.positions[b] = points[0], points[-1]
                length = polyline_length(points)
                self.layer.graph.add_edge(a, b, length, WalkLink('lane', points))
                self.layer.graph.add_edge(b, a, length, WalkLink('lane', points[::-1]))
        for junction in intersections:
            endpoints = []
            for road in junction.connected_roads:
                if road.id not in by_road:
                    continue
                end = 'start' if dist(road.centerline[0], junction.position) <= dist(road.centerline[-1], junction.position) else 'end'
                for lane in by_road[road.id]:
                    node = _node(lane, end)
                    endpoints.append((node, self.layer.positions[node]))
            # Connect existing road ends only, never a node per building.
            for source, start in endpoints:
                for destination, finish in endpoints:
                    if source != destination:
                        self.layer.graph.add_edge(source, destination, dist(start,finish),
                                                  WalkLink('junction', packed_points((start,finish))))
        self.layer.pack()

    def prepare(self):
        if not self.lanes:
            raise ValueError('No pedestrian lanes')
        # Build once per world revision, not once per origin/destination pair.
        with self._compile_lock:
            if self._native is None:
                self._native = NativeWalkingGraph(self.layer)
            return self._native

    def cost(self, start_point, destination_point):
        return self.prepare().cost(start_point,destination_point)

    def route(self, start_point, destination_point):
        native = self.prepare()
        (start, end), steps = native.route(start_point, destination_point)
        links = (WalkLink('access', (tuple(start_point), start)),
                 *(WalkLink(link.kind, _part(link.points, begin, finish))
                   for link, begin, finish in steps),
                 WalkLink('access', (end, tuple(destination_point))))
        points = []
        first_crossing = None
        distance = 0.0
        for link in links:
            for point in link.points:
                if points and dist(points[-1], point) < 1e-8:
                    continue
                if points:
                    step = dist(points[-1], point)
                    if first_crossing is None and link.kind == 'junction' and step > 1:
                        # Stop at the near edge before entering the connector.
                        first_crossing = distance
                    distance += step
                points.append(point)
        if len(points) < 2 or distance <= 0:
            raise ValueError('Walking route has zero length')
        crossing_fraction = -1.0 if first_crossing is None else first_crossing / distance
        return WalkingRoute(tuple(points), links, distance, crossing_fraction)
