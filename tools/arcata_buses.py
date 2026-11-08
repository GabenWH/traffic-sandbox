"""Synthetic benchmark bus service on connected existing road/building access."""
from math import atan2, dist
from transit import Bus, BusLine, BusStop


def _connected_sites(runtime):
    """Choose the component with the most round-trip-accessible building sites."""
    from collections import defaultdict
    from mobility import lane_start_node, lane_end_node
    graph = runtime.city.mobility.layers['vehicles'].graph
    adjacency = {node:[t.destination for t in graph.transitions_from(node)] for node in graph.nodes}
    reverse = defaultdict(list)
    for node,targets in adjacency.items():
        for target in targets:
            reverse[target].append(node)
    seen,order = set(),[]
    for root in adjacency:
        stack = [(root,False)]
        while stack:
            node,finished = stack.pop()
            if finished:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node,True))
                stack.extend((target,False) for target in adjacency.get(node,()) if target not in seen)
    component = {}
    for root in reversed(order):
        if root in component:
            continue
        stack = [root];component[root] = root
        while stack:
            for target in reverse[stack.pop()]:
                if target not in component:
                    component[target] = root;stack.append(target)
    groups = defaultdict(list)
    for sid,site in runtime.sites.items():
        position = site.get('road_position')
        if position is None:
            continue
        start,end = lane_start_node(position.lane),lane_end_node(position.lane)
        if start in component and component[start] == component.get(end):
            groups[component[start]].append(sid)
    return sorted(max(groups.values(),key=len,default=[]),key=str)


def add_benchmark_buses(runtime, progress=None):
    find_route = runtime.transit.traffic._native_backend(runtime.city).find_route
    candidates = _connected_sites(runtime)
    if len(candidates) < 10:
        raise ValueError('Benchmark buses require ten accessible sites')
    points = {sid:runtime.sites[sid]['walk_point'] for sid in candidates}
    center = tuple(sum(p[i] for p in points.values())/len(points) for i in (0,1))
    hub = min(candidates, key=lambda sid:dist(points[sid], center))
    selected = [hub]
    rejected = set()
    while len(selected) < 10:
        remaining = [sid for sid in candidates if sid not in selected and sid not in rejected]
        if not remaining:
            raise ValueError('Insufficient connected stops for benchmark bus service')
        sid = max(remaining, key=lambda sid:min(dist(points[sid],points[other]) for other in selected))
        source = runtime.sites[hub]['road_position']
        target = runtime.sites[sid]['road_position']
        if (target.point == source.point or find_route(source,target) is None
                or find_route(target,source) is None):
            rejected.add(sid)
            continue
        selected.append(sid)
        if progress:
            progress(dict(stage="bus_stop_selected", count=len(selected), site=sid))
    outer = sorted(selected[1:], key=lambda sid:atan2(points[sid][1]-points[hub][1],
                                                    points[sid][0]-points[hub][0]))
    stop_ids = {}
    for index,sid in enumerate(selected):
        stop_id = f'benchmark-stop-{index}'
        runtime.transit.add_stop(BusStop(stop_id,runtime.sites[sid]['road_position'],points[sid]))
        stop_ids[sid] = stop_id
    for index in range(3):
        sites = [hub]+outer[index*3:index*3+3]
        line_id = f'benchmark-line-{index}'
        runtime.transit.add_line(BusLine(line_id,tuple(stop_ids[sid] for sid in sites),headway_seconds=300), route_finder=find_route)
        for number in range(4):
            bus = Bus(f'{line_id}-bus-{number}',line_id,capacity=60,fuel_liters=1000,
                      service_at=runtime.time,service_until=runtime.time+86400)
            runtime.transit.add_bus(bus)
            runtime.initial_fuel += bus.fuel_liters
    runtime._access_times.clear()
    return dict(synthetic=True,lines=3,buses=12,stops=10,capacity_per_bus=60,
                headway_seconds=300,stop_sites=selected,
                note='Benchmark assumption; not real Arcata transit routes or schedules')
