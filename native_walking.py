"""Immutable walking graph bindings for the native traffic routing library.

Python authors geometry. Native code owns compiled adjacency, endpoint projection,
and A*. Buffers returned to Python belong to each call; no engine state is shared.
"""
import ctypes as C
from functools import lru_cache
from weakref import finalize


class _Point(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)]


class _Edge(C.Structure):
    _fields_ = [(name, C.c_int) for name in
                ('source', 'destination', 'point_start', 'point_count', 'reverse')]


class _Step(C.Structure):
    _fields_ = [('edge', C.c_int), ('start', C.c_double), ('end', C.c_double)]


@lru_cache(maxsize=1)
def _library():
    # Lazy import avoids the city/native traffic module initialization cycle.
    from native_traffic import _library as traffic_library
    lib = traffic_library()
    signatures = {
        'nt_walk_graph': (C.c_void_p, [C.POINTER(_Point), C.c_int,
                                     C.POINTER(_Edge), C.c_int, C.POINTER(_Point), C.c_int]),
        'nt_walk_destroy': (None, [C.c_void_p]),
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
            edges.append(_Edge(indices[source], indices[transition.destination], len(points),
                               len(link.points), reverse))
            points.extend(link.points)
        handle = self._lib.nt_walk_graph(
            (_Point * len(nodes))(*(_Point(*layer.positions[node]) for node in nodes)), len(nodes),
            (_Edge * len(edges))(*edges), len(edges),
            (_Point * len(points))(*(_Point(*point) for point in points)), len(points))
        if not handle:
            raise ValueError(self._lib.nt_error().decode())
        self._handle = handle
        self._release = finalize(self, self._lib.nt_walk_destroy, handle)
        self._capacity = len(nodes) + 2

    def route(self, start, destination):
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
