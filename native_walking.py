"""Immutable walking graph bindings for the native traffic routing library.

Python authors geometry. Native code owns endpoint projection and shared reverse
trees. Buffers returned to Python belong to each call; no engine state is shared.
"""
import ctypes as C
from functools import lru_cache
from weakref import finalize
import numpy as np
from collections import OrderedDict
from math import dist, isfinite
from threading import RLock

from models import polyline_length
from native_routing import NativeRouteGraph


class _Point(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)]


class _Edge(C.Structure):
    _fields_ = [(name, C.c_int) for name in
                ('source', 'destination', 'point_start', 'point_count', 'reverse')]


class _Step(C.Structure):
    _fields_ = [('edge', C.c_int), ('start', C.c_double), ('end', C.c_double)]


class _Projection(C.Structure):
    _fields_ = [('lane', C.c_int), ('distance', C.c_double), ('point', _Point)]


@lru_cache(maxsize=1)
def _library():
    # Lazy import avoids the city/native traffic module initialization cycle.
    from native_traffic import _library as traffic_library
    lib = traffic_library()
    signatures = {
        'nt_walk_graph': (C.c_void_p, [C.POINTER(_Point), C.c_int,
                                     C.POINTER(_Edge), C.c_int, C.POINTER(_Point), C.c_int]),
        'nt_walk_destroy': (None, [C.c_void_p]),
        'nt_walk_project': (C.c_int, [C.c_void_p, _Point, C.POINTER(_Projection)]),
        'nt_walk_query': (C.c_int, [C.c_void_p, _Point, _Point,
                                  C.POINTER(_Point), C.POINTER(_Step), C.c_int]),
    }
    for name, (result, args) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, args
    return lib


class NativeWalkingGraph:
    def __init__(self, layer):
        self._lib = _library()
        nodes = list(layer.graph.nodes)
        indices = {node: i for i, node in enumerate(nodes)}
        rows = [(source, transition) for source in nodes
                for transition in layer.graph.transitions_from(source)]
        lanes = {(source, transition.destination): i for i, (source, transition) in enumerate(rows)
                 if transition.edge.kind == 'lane'}
        points, edges = [], []
        self.links = tuple(transition.edge for _, transition in rows)
        for source, transition in rows:
            link = transition.edge
            reverse = lanes[(transition.destination, source)] if link.kind == 'lane' else -1
            edges.append((indices[source], indices[transition.destination], len(points),
                          len(link.points), reverse))
            points.extend(link.points)
        node_buffer=np.asarray([layer.positions[node] for node in nodes],dtype=np.float64).reshape(-1,2)
        edge_buffer=np.asarray(edges,dtype=np.int32).reshape(-1,5)
        point_buffer=np.asarray(points,dtype=np.float64).reshape(-1,2)
        handle = self._lib.nt_walk_graph(
            node_buffer.ctypes.data_as(C.POINTER(_Point)), len(nodes),
            edge_buffer.ctypes.data_as(C.POINTER(_Edge)), len(edges),
            point_buffer.ctypes.data_as(C.POINTER(_Point)), len(points))
        if not handle:
            raise ValueError(self._lib.nt_error().decode())
        self._handle = handle
        self._release = finalize(self, self._lib.nt_walk_destroy, handle)
        self._capacity = len(nodes) + 2
        self._edges = edge_buffer[:, :2].copy()
        self._reverse = edge_buffer[:, 4].copy()
        self._lengths = np.fromiter((polyline_length(link.points) for link in self.links),
                                    dtype=np.float64, count=len(self.links))
        self._routing = NativeRouteGraph(len(nodes),
            ((int(a), int(b), float(cost)) for (a,b),cost in zip(self._edges,self._lengths)))
        for data in (self._edges,self._reverse,self._lengths):data.flags.writeable=False
        self._projections, self._trees = OrderedDict(), OrderedDict()
        self._cache_lock = RLock()
        self.projection_limit = 8192
        # Native trees use 16 bytes/node; cap retained trees at 64 MiB as well.
        self.tree_limit = max(1,min(256,64*1024*1024//max(1,16*len(nodes))))

    def _project(self, point):
        output = _Projection()
        if self._lib.nt_walk_project(self._handle,_Point(*point),C.byref(output)) < 0:
            raise ValueError(self._lib.nt_error().decode())
        return output.lane, min(float(self._lengths[output.lane]), max(0.,output.distance)), (output.point.x,output.point.y)

    def _endpoint(self, point):
        key = tuple(point)
        if len(key)!=2 or not all(isfinite(value) for value in key):
            raise ValueError('Walking endpoints must be finite 2D points')
        with self._cache_lock:
            if key not in self._projections:
                self._projections[key] = self._project(key)
            self._projections.move_to_end(key)
            result = self._projections[key]
            while len(self._projections)>self.projection_limit:self._projections.popitem(last=False)
            return result

    def _tree(self, endpoint):
        lane, offset, _ = endpoint
        key = lane, offset
        with self._cache_lock:
            if key not in self._trees:
                source,target = map(int,self._edges[lane])
                self._trees[key] = self._routing.tree(((source,offset),(target,float(self._lengths[lane])-offset)))
            self._trees.move_to_end(key)
            tree = self._trees[key]
            while len(self._trees)>self.tree_limit:self._trees.popitem(last=False)
            return tree

    def _query(self, start, destination, *, geometry):
        a,b = self._endpoint(start),self._endpoint(destination)
        lane,offset,_ = a
        length = float(self._lengths[lane])
        source,target = map(int,self._edges[lane])
        origins = ((target,length-offset),(source,offset))
        tree = self._tree(b)
        direct = abs(b[1]-offset) if lane==b[0] else float('inf')
        access = dist(start,a[2])+dist(b[2],destination)
        if not geometry:
            cost = min(direct,tree.cost(origins))
            if not isfinite(cost):raise ValueError('No walking route')
            return access+cost
        path = tree.path(origins)
        if isfinite(direct) and (path is None or direct<=path[3]):
            steps = ((lane,offset,b[1]),) if b[1]>=offset else ((int(self._reverse[lane]),length-offset,length-b[1]),)
        elif path is None:
            raise ValueError('No walking route')
        else:
            origin,root,edges,_ = path
            first = (lane,offset,length) if origin==0 else (int(self._reverse[lane]),length-offset,length)
            last = (b[0],0.,b[1]) if root==0 else (int(self._reverse[b[0]]),0.,float(self._lengths[b[0]])-b[1])
            steps = (first, *((edge,0.,float(self._lengths[edge])) for edge in edges), last)
        return ((a[2],b[2]), tuple((self.links[edge],begin,end) for edge,begin,end in steps))

    def cost(self, start, destination):
        return self._query(start,destination,geometry=False)

    def route(self, start, destination):
        return self._query(start,destination,geometry=True)

    def astar_route(self, start, destination):
        """Retained reference query for parity checks against shared trees."""
        projections = (_Point * 2)()
        steps = (_Step * self._capacity)()
        count = self._lib.nt_walk_query(self._handle, _Point(*start), _Point(*destination),
                                        projections, steps, self._capacity)
        if count < 0:
            raise ValueError(self._lib.nt_error().decode())
        if not count:
            raise ValueError('No walking route')
        return (tuple((point.x, point.y) for point in projections),
                tuple((self.links[step.edge], step.start, step.end) for step in steps[:count]))
