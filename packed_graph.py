"""Compiled CSR graph columns with the existing routing/editor interface."""
from collections.abc import MutableMapping
import numpy as np
from pathfinding import DirectedGraph,Transition


class PackedGraph:
    def __init__(self,graph):
        self._nodes=graph.nodes;self.ids={node:i for i,node in enumerate(self._nodes)}
        rows=[t for node in self._nodes for t in graph.transitions_from(node)]
        sizes=[len(graph.transitions_from(node)) for node in self._nodes]
        self.offsets=np.empty(len(sizes)+1,dtype=np.int64);self.offsets[0]=0
        np.cumsum(sizes,out=self.offsets[1:])
        self.targets=np.fromiter((self.ids[t.destination] for t in rows),dtype=np.int32,count=len(rows))
        self.costs=np.fromiter((t.cost for t in rows),dtype=np.float64,count=len(rows))
        self.edges=tuple(t.edge for t in rows)
        for data in (self.offsets,self.targets,self.costs):data.flags.writeable=False
        self._builder=None

    @property
    def nodes(self):return self._nodes if self._builder is None else self._builder.nodes

    def transitions_from(self,node):
        if self._builder is not None:return self._builder.transitions_from(node)
        index=self.ids.get(node)
        if index is None:return ()
        return tuple(Transition(self._nodes[int(self.targets[i])],float(self.costs[i]),self.edges[i])
                     for i in range(int(self.offsets[index]),int(self.offsets[index+1])))

    def find_path(self,*args,**kwargs):return DirectedGraph.find_path(self,*args,**kwargs)

    def _thaw(self):
        if self._builder is None:
            builder=DirectedGraph()
            for node in self._nodes:
                builder.add_node(node)
                for t in self.transitions_from(node):builder.add_edge(node,t.destination,t.cost,t.edge)
            self._builder=builder
        return self._builder

    # Authored graph changes retain their old semantics. The next world rebuild
    # compacts the replacement graph again; active native snapshots stay immutable.
    @property
    def _adjacency(self):return self._thaw()._adjacency
    def add_node(self,*args,**kwargs):return self._thaw().add_node(*args,**kwargs)
    def add_edge(self,*args,**kwargs):return self._thaw().add_edge(*args,**kwargs)
    def extend(self,*args,**kwargs):return self._thaw().extend(*args,**kwargs)


class PackedPositions(MutableMapping):
    def __init__(self,positions):
        self.nodes=tuple(positions);self.ids={node:i for i,node in enumerate(self.nodes)}
        self.points=np.asarray(list(positions.values()),dtype=np.float64).reshape(-1,2)
        self.points.flags.writeable=False
        self._builder=None
    def __len__(self):return len(self.nodes) if self._builder is None else len(self._builder)
    def __iter__(self):return iter(self.nodes if self._builder is None else self._builder)
    def __getitem__(self,key):
        if self._builder is not None:return self._builder[key]
        p=self.points[self.ids[key]];return float(p[0]),float(p[1])
    def _thaw(self):
        if self._builder is None:self._builder={key:self[key] for key in self.nodes}
        return self._builder
    def __setitem__(self,key,value):self._thaw()[key]=value
    def __delitem__(self,key):del self._thaw()[key]
