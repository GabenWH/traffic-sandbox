"""Immutable native route trees; ctypes releases the GIL during searches.

Trees share native graph ownership. Every query owns its output buffer, so trees
and graphs may be queried concurrently and never reference the live engine.
"""
import ctypes as C
from functools import lru_cache
from weakref import finalize
import numpy as np


class _Edge(C.Structure):
    _fields_=[('source',C.c_int),('destination',C.c_int),('cost',C.c_double)]


@lru_cache(maxsize=1)
def _library():
    from native_traffic import _library as traffic_library
    lib=traffic_library()
    signatures={
        'nt_routing_graph':(C.c_void_p,[C.c_int,C.POINTER(_Edge),C.c_int]),
        'nt_routing_graph_destroy':(None,[C.c_void_p]),
        'nt_routing_tree':(C.c_void_p,[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_double),C.c_int,C.POINTER(C.c_double),C.c_int]),
        'nt_routing_tree_destroy':(None,[C.c_void_p]),
        'nt_routing_path':(C.c_int,[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_double),C.c_int,
                                   C.POINTER(C.c_int),C.c_int,C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(C.c_double)]),
        'nt_routing_cost':(C.c_int,[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_double),C.c_int,C.POINTER(C.c_double)]),
    }
    for name,(result,args) in signatures.items():
        function=getattr(lib,name);function.restype,function.argtypes=result,args
    return lib


def _endpoints(rows):
    rows=tuple(rows)
    if not rows:raise ValueError('Routing needs at least one endpoint')
    return (C.c_int*len(rows))(*(r[0] for r in rows)),(C.c_double*len(rows))(*(r[1] for r in rows))


class NativeRouteGraph:
    def __init__(self,node_count,edges):
        if isinstance(node_count,bool) or not isinstance(node_count,int) or not 0<node_count<=2147483647:
            raise ValueError('Invalid routing node count')
        rows=tuple(edges);self.node_count=node_count;self.edge_count=len(rows)
        self._lib=_library()
        data=np.fromiter(rows,dtype=np.dtype([('source','i4'),('destination','i4'),('cost','f8')],align=True),count=len(rows))
        self._handle=self._lib.nt_routing_graph(node_count,data.ctypes.data_as(C.POINTER(_Edge)),len(rows))
        if not self._handle:raise ValueError(self._lib.nt_error().decode())
        self._release=finalize(self,self._lib.nt_routing_graph_destroy,self._handle)

    def tree(self,targets,*,costs=None):
        nodes,finals=_endpoints(targets)
        if costs is not None:
            costs=np.ascontiguousarray(costs,dtype=np.float64) if isinstance(costs,np.ndarray) else np.fromiter(costs,dtype=np.float64)
            if costs.ndim!=1 or len(costs)!=self.edge_count:raise ValueError('Routing weights must cover every edge')
        weights=costs.ctypes.data_as(C.POINTER(C.c_double)) if costs is not None else None
        ptr=self._lib.nt_routing_tree(self._handle,nodes,finals,len(nodes),weights,len(costs) if costs is not None else 0)
        if not ptr:raise ValueError(self._lib.nt_error().decode())
        return NativeRouteTree(self._lib,ptr,self.node_count)


class NativeRouteTree:
    def __init__(self,lib,handle,size):
        self._lib,self._handle,self._size=lib,handle,size
        self._release=finalize(self,lib.nt_routing_tree_destroy,handle)

    def cost(self,origins):
        """Read shared distances without allocating/reconstructing an edge path."""
        nodes,initials=_endpoints(origins);cost=C.c_double()
        found=self._lib.nt_routing_cost(self._handle,nodes,initials,len(nodes),C.byref(cost))
        if found<0:raise ValueError(self._lib.nt_error().decode())
        return cost.value if found else float('inf')

    def path(self,origins):
        nodes,initials=_endpoints(origins)
        edges=(C.c_int*self._size)();origin=C.c_int();target=C.c_int();cost=C.c_double()
        count=self._lib.nt_routing_path(self._handle,nodes,initials,len(nodes),edges,self._size,
                                        C.byref(origin),C.byref(target),C.byref(cost))
        if count==-2:return None
        if count<0:raise ValueError(self._lib.nt_error().decode())
        return origin.value,target.value,tuple(edges[:count]),cost.value
