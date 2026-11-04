"""Bounded background routing; only the simulation owner materializes paths.

The worker's inputs are immutable graph/endpoint/cost snapshots. Its only native
handle is a routing graph, never the traffic engine or live parking state.
"""
from collections import Counter,OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from math import dist
import os
import sys
import threading

from mobility import (VEHICLE_LAYER,LaneTraversal,MobilityLink,lane_end_node,lane_start_node)
from models import polyline_length,slice_polyline
from native_routing import NativeRouteGraph
from pathfinding import Path
from route_learning import TravelLearning

PENDING=object()


def link_key(link):
    value=link.value
    if link.kind=='lane':return 'lane:'+getattr(value,'lane',value).id
    if link.kind=='road_port':return 'port:'+value.port.id+':'+value.lane.id
    return link.kind+':'+value.id


def link_points(link):
    from mobility import vehicle_link_points
    return tuple(vehicle_link_points(link))


def _lower_priority():
    if sys.platform.startswith('linux'):
        try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),10)
        except (OSError,AttributeError):pass


@lru_cache(maxsize=1)
def _executor():return ThreadPoolExecutor(max_workers=1,thread_name_prefix='commute-routing',initializer=_lower_priority)


@dataclass(frozen=True)
class _End:
    lane: str
    edge: int
    start: int
    end: int
    distance: float
    length: float


@dataclass(frozen=True)
class _Plan:
    origin: int
    target: int
    edges: tuple
    cost: float
    direct: bool=False
    built: bool=False


class VehicleGraphSnapshot:
    def __init__(self,city,speed_mph):
        layer=city.mobility.layers[VEHICLE_LAYER];nodes=tuple(layer.graph.nodes)
        self.revision=city.mobility_revision;self.nodes=nodes;self.ids={n:i for i,n in enumerate(nodes)}
        self.rows=tuple((source,t) for source in nodes for t in layer.graph.transitions_from(source))
        self.keys=tuple(link_key(t.edge) for _,t in self.rows)
        self.by_key={key:i for i,key in enumerate(self.keys)}
        self.lanes={};self.lane_edges={};self.geometry={};costs=[];edges=[]
        for i,(source,t) in enumerate(self.rows):
            link=t.edge;value=link.value
            lane=getattr(value,'lane',value) if link.kind in ('lane','road_port') else None
            mph=min(speed_mph,getattr(lane,'speed_limit_mph',None) or speed_mph)
            cost=t.cost/(mph*22/15);costs.append(cost)
            edges.append((self.ids[source],self.ids[t.destination],cost))
            if link.kind=='lane':
                self.lanes[lane.id]=lane;self.lane_edges[lane.id]=i;self.geometry[lane.id]=tuple(lane.points)
        self.defaults=tuple(costs);self.native=NativeRouteGraph(max(1,len(nodes)),edges)

    def endpoints(self,positions):
        result=[]
        for p in positions:
            lane=p.lane.id
            if lane not in self.lanes or self.lanes[lane] is not p.lane:raise ValueError('Route endpoint uses a stale lane')
            result.append(_End(lane,self.lane_edges[lane],self.ids[lane_start_node(p.lane)],
                                self.ids[lane_end_node(p.lane)],p.distance,polyline_length(self.geometry[lane])))
        return tuple(result)

    @staticmethod
    def partial(endpoint,length,weights):
        return weights[endpoint.edge]*length/max(endpoint.length,1e-9)

    def restore(self,habit,origins,targets,weights):
        try:
            oi=next(i for i,e in enumerate(origins) if e.lane==habit['origin'])
            ti=next(i for i,e in enumerate(targets) if e.lane==habit['target'])
            a,b=origins[oi],targets[ti]
            if habit['direct']:
                if a.lane!=b.lane or b.distance<a.distance:return None
                return _Plan(oi,ti,(),self.partial(a,b.distance-a.distance,weights),True)
            indices=tuple(self.by_key[key] for key in habit['edges']);node=a.end
            for index in indices:
                source,t=self.rows[index]
                if self.ids[source]!=node:return None
                node=self.ids[t.destination]
            if node!=b.start:return None
            cost=self.partial(a,a.length-a.distance,weights)+sum(weights[i] for i in indices)+self.partial(b,b.distance,weights)
            return _Plan(oi,ti,indices,cost)
        except (KeyError,StopIteration,TypeError):return None

    def materialize(self,plan,origins,targets):
        a,b=origins[plan.origin],targets[plan.target]
        start=('vehicle_query_start',a.lane,a.distance);end=('vehicle_query_destination',b.lane,b.distance)
        def piece(endpoint,low,high):
            return MobilityLink('lane',LaneTraversal(self.lanes[endpoint.lane],tuple(slice_polyline(self.geometry[endpoint.lane],low,high))))
        if plan.direct:return Path((start,end),(piece(a,a.distance,b.distance),),plan.cost)
        nodes=[start,self.nodes[a.end]];links=[piece(a,a.distance,a.length)]
        for index in plan.edges:
            _,t=self.rows[index];nodes.append(t.destination);links.append(t.edge)
        nodes.append(end);links.append(piece(b,0,b.distance))
        return Path(tuple(nodes),tuple(links),plan.cost)


def _search(snapshot,origins,targets,weights,cache):
    # Cache is worker-owned. A graph replacement gets a separate cache object.
    roots=tuple((b.start,snapshot.partial(b,b.distance,weights)) for b in targets)
    key=(id(snapshot),id(weights),roots)
    built=key not in cache
    if built:
        cache[key]=(snapshot.native.tree(roots,costs=weights),weights)
        if len(cache)>256:cache.popitem(last=False)
    else:cache.move_to_end(key)
    tree=cache[key][0]
    found=tree.path([(a.end,snapshot.partial(a,a.length-a.distance,weights)) for a in origins])
    best=_Plan(*found,built=built) if found is not None else None
    for oi,a in enumerate(origins):
        for ti,b in enumerate(targets):
            if a.lane==b.lane and b.distance>=a.distance:
                cost=snapshot.partial(a,b.distance-a.distance,weights)
                if best is None or cost<=best.cost:best=_Plan(oi,ti,(),cost,True,built)
    return best,built


class BackgroundRoutes:
    def __init__(self,city,*,speed_mph=25.,executor=None,max_pending=128,submissions_per_update=4,learning=None):
        if max_pending<1 or submissions_per_update<1:raise ValueError('Routing bounds must be positive')
        self.city=city;self.speed_mph=speed_mph;self.executor=executor
        self.max_pending=max_pending;self.submissions_per_update=submissions_per_update
        self.learning=learning or TravelLearning();self._snapshot=VehicleGraphSnapshot(city,speed_mph)
        self._requests={};self._results=OrderedDict();self._ready=OrderedDict();self._cache=OrderedDict();self._weights={}
        self._budget=submissions_per_update;self._budget_epoch=None;self._counts=Counter();self.closed=False

    def sync(self):
        if self.closed:raise RuntimeError('Routing service is closed')
        if self._snapshot.revision==self.city.mobility_revision:return
        for future in self._requests.values():future.cancel()
        self._counts['routing_stale_results']+=len(self._requests)
        self._requests.clear();self._results.clear();self._ready.clear();self._weights.clear();self._cache=OrderedDict()
        self._snapshot=VehicleGraphSnapshot(self.city,self.speed_mph)

    def begin_update(self,day,*,epoch=None):
        self.sync()
        if epoch is None or epoch!=self._budget_epoch:
            self._budget=self.submissions_per_update;self._budget_epoch=epoch
        # Finish prior-day observations once, not once per commuter.
        if day!=self.learning.model_day:self.learning.costs_for(day)
        ready=[]
        for key,future in list(self._requests.items()):
            if future.done():
                result=future.result();self._results[key]=result;del self._requests[key]
                self._counts['routing_queries_completed']+=1;self._counts['routing_trees_built']+=result[1]
                ready.append(key[0])
        while len(self._results)>4096:self._results.popitem(last=False)
        return ready

    def get_route(self,vehicle,source,destination,origins,targets,*,day=0,blocking=False):
        self.sync();snapshot=self._snapshot
        if not origins or not targets:return None
        origins=snapshot.endpoints(origins);targets=snapshot.endpoints(targets)
        signature=lambda rows:tuple((e.lane,e.distance) for e in rows)
        key=(vehicle,source,destination,signature(origins),signature(targets),day,snapshot.revision)
        if key in self._ready:
            self._ready.move_to_end(key);return self._ready[key]
        if day not in self._weights:
            learned=self.learning.costs_for(day)
            self._weights[day]=tuple(max(cost,learned.get(link,cost)) for link,cost in zip(snapshot.keys,snapshot.defaults))
            if len(self._weights)>2:del self._weights[min(self._weights)]
        weights=self._weights[day]
        if key not in self._requests and key not in self._results:
            # Drop terminal completed futures only when their caller collects them;
            # this keeps results and the request bound deterministic.
            if len(self._requests)>=self.max_pending or (not blocking and self._budget<=0):return PENDING
            self._budget-=1
            self._requests[key]=(self.executor or _executor()).submit(_search,snapshot,origins,targets,weights,self._cache)
            self._counts['routing_queries_submitted']+=1
        if key in self._results:plan,built=self._results.pop(key)
        else:
            future=self._requests[key]
            if not blocking and not future.done():return PENDING
            plan,built=future.result();del self._requests[key]
            self._counts['routing_queries_completed']+=1;self._counts['routing_trees_built']+=built
        route=None
        if plan is not None:
            habit_key=(vehicle,source,destination);habit=self.learning.habits.get(habit_key)
            familiar=snapshot.restore(habit,origins,targets,weights) if habit else None
            if familiar is not None and (habit['day']==day or not self.learning.should_switch(vehicle,familiar.cost,plan.cost)):
                plan=familiar
            elif familiar is not None:self._counts['routing_learned_switches']+=1
            self.learning.habits[habit_key]=dict(day=day,origin=origins[plan.origin].lane,target=targets[plan.target].lane,
                                                edges=[snapshot.keys[i] for i in plan.edges],direct=plan.direct)
            route=snapshot.materialize(plan,origins,targets)
        self._ready[key]=route
        if len(self._ready)>4096:self._ready.popitem(last=False)
        return route

    def close(self):
        for future in self._requests.values():future.cancel()
        self._requests.clear();self._results.clear();self._ready.clear();self.closed=True

    def report(self):
        return dict(routing_pending=len(self._requests),routing_results_ready=len(self._results),**{name:self._counts[name] for name in
                    ('routing_queries_submitted','routing_queries_completed','routing_trees_built','routing_stale_results','routing_learned_switches')})
