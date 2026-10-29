"""Compile walking routes from road-owned pedestrian lanes.

Junction links remain geometric assumptions rather than validated crossings.
Query endpoints are temporary: no road is split for a building.
"""
from dataclasses import dataclass
from math import dist

from mobility import MobilityLayer, nearest_lane_position
from models import PedestrianLane, polyline_length, slice_polyline
from pathfinding import DirectedGraph


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


def _node(lane, end):
    return ('pedestrian_lane', lane.id, end)


def _part(points, start, end):
    if start <= end:
        return tuple(slice_polyline(points, start, end))
    return tuple(reversed(slice_polyline(points, end, start)))


class PedestrianNetwork:
    def __init__(self, roads, intersections):
        self.layer = MobilityLayer()
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
                self.layer.graph.add_edge(b, a, length, WalkLink('lane', tuple(reversed(points))))
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
                                                  WalkLink('junction', (start,finish)))

    def route(self, start_point, destination_point):
        if not self.lanes:
            raise ValueError('No pedestrian lanes')
        start, _ = min((nearest_lane_position(lane, start_point) for lane in self.lanes), key=lambda value: value[1])
        end, _ = min((nearest_lane_position(lane, destination_point) for lane in self.lanes), key=lambda value: value[1])
        graph = DirectedGraph()
        graph.extend(self.layer.graph)
        source, target = ('pedestrian_query', 'start'), ('pedestrian_query', 'end')
        positions = dict(self.layer.positions)
        positions[source], positions[target] = start.point, end.point
        for end_name, distance in (('start',0),('end',polyline_length(start.lane.points))):
            points = _part(start.lane.points, start.distance, distance)
            graph.add_edge(source, _node(start.lane,end_name), abs(start.distance-distance), WalkLink('lane',points))
        for end_name, distance in (('start',0),('end',polyline_length(end.lane.points))):
            points = _part(end.lane.points, distance, end.distance)
            graph.add_edge(_node(end.lane,end_name), target, abs(end.distance-distance), WalkLink('lane',points))
        if start.lane.id == end.lane.id:
            graph.add_edge(source, target, abs(start.distance-end.distance),
                           WalkLink('lane',_part(start.lane.points,start.distance,end.distance)))
        path = graph.find_path(source, target, lambda node: dist(positions[node], end.point))
        if path is None:
            raise ValueError('No walking route')
        links = (WalkLink('access', (tuple(start_point), start.point)), *path.edges,
                 WalkLink('access', (end.point, tuple(destination_point))))
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
