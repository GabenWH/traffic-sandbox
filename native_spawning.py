"""Map compilation and output mirrors for the full native traffic simulation.

All spawn choices, routing, clearance and driving occur in the C++ library.
Python transfers immutable map facts and explicit mutations and presents output.
"""
import ctypes as C
from math import isfinite
from time import perf_counter
from types import SimpleNamespace

from native_traffic import NativeTrafficEngine, _Connection, _Point, _Spawn, _Section, _Movement, CONTROL


class Relation(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('first', 'second', 'flags')]


class Edge(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('source', 'destination', 'point_start', 'point_count',
                                           'key', 'kind', 'connection', 'incoming')] + [
        (name, C.c_double) for name in ('cost', 'offset', 'control_offset', 'length')]


class Endpoint(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)] + [
        (name, C.c_int) for name in ('out_start', 'out_count', 'in_start', 'in_count')]


class Generated(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('handle', 'route', 'source', 'destination', 'color')] + [('number', C.c_int64)]


class Bookkeeping(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('handle', 'connection', 'kind')] + [('value', C.c_double)]


class Clock(C.Structure):
    _fields_ = [(name, C.c_double) for name in ('time', 'stall', 'threshold')] + [
        (name, C.c_int) for name in ('winner', 'movement', 'hard')]


class Trace(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('handle', 'connection', 'priority', 'claimed', 'first_vehicle',
                                           'vehicle_count', 'reservations')] + [
        (name, C.c_double) for name in ('distance', 'speed')]


def bind(lib):
    pointer = C.c_void_p
    signatures = {
        'nt_network_sparse': (C.c_int, [pointer, C.POINTER(_Connection), C.c_int, C.POINTER(Relation), C.c_int]),
        'nt_graph': (C.c_int, [pointer, C.POINTER(_Point), C.c_int, C.POINTER(Edge), C.c_int,
                             C.POINTER(_Point), C.c_int, C.POINTER(Endpoint), C.c_int, C.POINTER(C.c_int), C.c_int]),
        'nt_rng_set': (C.c_int, [pointer, C.POINTER(C.c_uint32), C.c_int]),
        'nt_rng_get': (C.c_int, [pointer, C.POINTER(C.c_uint32), C.c_int]),
        'nt_choice': (C.c_int, [pointer, C.c_int]),
        'nt_sources': (C.c_int, [pointer, C.POINTER(C.c_int), C.POINTER(C.c_double), C.c_int,
                                C.c_double, C.c_int, C.c_int64, C.c_int]),
        'nt_source_times': (C.c_int, [pointer, C.POINTER(C.c_double), C.c_int]),
        'nt_spawn_count': (C.c_int64, [pointer]),
        'nt_generate': (C.c_int, [pointer, C.c_double]),
        'nt_generate_one': (C.c_int, [pointer, C.c_int, C.c_int]),
        'nt_generated': (C.POINTER(Generated), [pointer, C.POINTER(C.c_int)]),
        'nt_find_route': (C.c_int, [pointer, C.c_int, C.c_int]),
        'nt_find_position_route': (C.c_int, [pointer, C.c_int, C.c_int, C.c_double, _Point,
                                          C.c_int, C.c_int, C.c_double, _Point]),
        'nt_route_edges': (C.POINTER(C.c_int), [pointer, C.c_int, C.POINTER(C.c_int)]),
        'nt_route_sections': (C.POINTER(_Section), [pointer, C.c_int, C.POINTER(C.c_int)]),
        'nt_route_movements': (C.POINTER(_Movement), [pointer, C.c_int, C.POINTER(C.c_int)]),
        'nt_route_cost': (C.c_double, [pointer, C.c_int]),
        'nt_admit': (C.c_int, [pointer, C.POINTER(_Spawn), C.c_char_p]),
        'nt_bookkeeping': (C.POINTER(Bookkeeping), [pointer, C.POINTER(C.c_int), C.POINTER(Clock)]),
        'nt_trace_enable': (C.c_int, [pointer, C.c_int]),
        'nt_trace': (C.POINTER(Trace), [pointer, C.POINTER(C.c_int)]),
        'nt_trace_vehicles': (C.POINTER(C.c_int), [pointer, C.POINTER(C.c_int)]),
    }
    for name, (result, args) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, args


class NativeRoadSimulation:
    def __init__(self, simulation, city=None):
        self.sim = simulation
        self.engine = NativeTrafficEngine.from_simulation(simulation)
        self.city = None
        self.junctions = []
        self.endpoint_ids = {}
        self.paths = {}
        self.external_routes = {}
        self.source_ids = []
        self.controls = {}
        self.publishing = False
        try:
            if city is not None:
                self.bind_city(city)
        except BaseException:
            self.engine.close()
            raise

    def bind_city(self, city):
        if self.city is city:
            return
        from mobility import vehicle_link_points, road_input_node, road_output_node
        from models import polyline_length
        e = self.engine
        layer = city.mobility.layers['vehicles']
        graph = layer.graph
        self.nodes = graph.nodes
        ids = {node: i for i, node in enumerate(self.nodes)}
        self.graph_edges = [(node, transition) for node in self.nodes
                            for transition in graph.transitions_from(node)]
        self.lane_edges = {id(t.edge.value): i for i, (_, t) in enumerate(self.graph_edges) if t.edge.kind == 'lane'}
        e.prepare_connections(t.edge.value for _, t in self.graph_edges if t.edge.kind == 'lane_connection')
        points, edges = [], []
        for source, transition in self.graph_edges:
            link = transition.edge
            value = link.value
            geometry = vehicle_link_points(link)
            first = len(points)
            points.extend(_Point(*p) for p in geometry)
            connection, incoming, offset, control_offset = -1, -1, 0.0, 0.0
            if link.kind == 'lane':
                key, kind = ('lane', value.id), 1
            elif link.kind == 'road_port':
                key, kind = ('road_port', value.port.id, value.lane.id), 2
            elif link.kind == 'lane_connection':
                key, kind = ('lane_connection', value.id), 3
                connection = e._connection_ids[id(value)]
                incoming = e._key(('road_output', value.source_output.id))
                control_offset = value.control_offset
            else:
                key, kind = None, 0
            edges.append(Edge(ids[source], ids[transition.destination], first, len(geometry),
                              -1 if key is None else e._key(key), kind, connection, incoming,
                              transition.cost, offset, control_offset, polyline_length(geometry)))
        self.junctions = tuple(city.intersections)
        self.endpoint_ids = {id(j): i for i, j in enumerate(self.junctions)}
        ports, endpoints = [], []
        for junction in self.junctions:
            outgoing = [ids[road_input_node(p)] for p in junction.outgoing_ports() if road_input_node(p) in ids]
            incoming = [ids[road_output_node(p)] for p in junction.incoming_ports() if road_output_node(p) in ids]
            first_out = len(ports)
            ports.extend(outgoing)
            first_in = len(ports)
            ports.extend(incoming)
            endpoints.append(Endpoint(*junction.position, first_out, len(outgoing), first_in, len(incoming)))
        positions = [_Point(*layer.positions[node]) for node in self.nodes]
        e._call('nt_graph', (_Point * len(positions))(*positions), len(positions),
                (Edge * len(edges))(*edges), len(edges), (_Point * len(points))(*points), len(points),
                (Endpoint * len(endpoints))(*endpoints), len(endpoints), (C.c_int * len(ports))(*ports), len(ports))
        self.city = city
        self.paths.clear()

    def configure(self):
        sim, e = self.sim, self.engine
        sim._publish_occupancy_changes()
        state = sim.rng.getstate()
        if state[0] != 3 or len(state[1]) != 625 or any(not 0 <= word <= 0xffffffff for word in state[1]):
            raise ValueError('Native traffic requires a valid Python Random version-3 state')
        self.gaussian = state[2]
        e._call('nt_rng_set', (C.c_uint32 * 625)(*state[1]), 625)
        junctions = sim._active_junctions_snapshot(self.city) if self.city is not None else ()
        self.source_ids = [junction.id for junction in junctions]
        sources = [self.endpoint_ids[id(j)] for j in junctions]
        clocks = [sim._spawn_elapsed[j.id] for j in junctions]
        if not isinstance(sim.max_cars, int) or not 1 <= sim.max_cars <= 2147483647:
            raise ValueError('Native traffic cap must be a positive 32-bit integer')
        e._call('nt_sources', (C.c_int * len(sources))(*sources), (C.c_double * len(clocks))(*clocks),
                len(sources), sim.spawn_interval, sim.max_cars, sim._spawned_count, e._next_handle)
        e.set_speed(sim.speed_mph)
        e._call('nt_trace_enable', int(sim.debugger is not None))
        for connection in e._connections:
            control = CONTROL.get(connection.control.kind, 0)
            if self.controls.get(id(connection)) != control:
                e.set_control(connection, connection.control.kind)
                self.controls[id(connection)] = control

    def publish_random(self):
        e, sim = self.engine, self.sim
        words = (C.c_uint32 * 625)()
        e._call('nt_rng_get', words, 625)
        sim.rng.setstate((3, tuple(words), self.gaussian))
        clocks = (C.c_double * len(self.source_ids))()
        e._call('nt_source_times', clocks, len(clocks))
        sim._spawn_elapsed.update(zip(self.source_ids, clocks))
        sim._spawned_count = e._lib.nt_spawn_count(e._ptr)

    def path(self, route, source, destination, extras=None):
        if route not in self.paths:
            from mobility import MobilityLink
            from pathfinding import Path
            count = C.c_int()
            pointer = self.engine._lib.nt_route_edges(self.engine._ptr, route, C.byref(count))
            if count.value < 0:
                raise ValueError(self.engine._lib.nt_error().decode())
            selected = [self.graph_edges[pointer[i]] if pointer[i] < len(self.graph_edges)
                        else extras[pointer[i]] for i in range(count.value)]
            start = ('vehicle_query_start', id(source))
            end = ('vehicle_query_destination', id(destination))
            from mobility import LanePosition
            nodes, edges = [start], []
            if not isinstance(source, LanePosition):
                edges.append(MobilityLink('route_endpoint', source))
                if selected:
                    nodes.append(selected[0][0])
            for _, transition in selected:
                nodes.append(transition.destination)
                edges.append(transition.edge)
            if not isinstance(destination, LanePosition):
                edges.append(MobilityLink('route_endpoint', destination))
                nodes.append(end)
            if not selected and source is destination:
                nodes, edges = [start, end], [MobilityLink('route_endpoint', source)]
            self.paths[route] = Path(tuple(nodes), tuple(edges), self.engine._lib.nt_route_cost(self.engine._ptr, route))
        return self.paths[route]

    def find_route(self, source, destination):
        from mobility import LanePosition, LaneTraversal, MobilityLink, lane_start_node, lane_end_node
        from models import polyline_length, slice_polyline
        def endpoint(value):
            if isinstance(value, LanePosition):
                if id(value.lane) not in self.lane_edges:
                    raise ValueError('Vehicle route positions must use lanes in this city')
                return -1, self.lane_edges[id(value.lane)], value.distance, _Point(*value.point)
            if id(value) not in self.endpoint_ids:
                raise ValueError('Vehicle route junctions must belong to this city')
            return self.endpoint_ids[id(value)], -1, 0, _Point(*value.position)
        route = self.engine._call('nt_find_position_route', *endpoint(source), *endpoint(destination)) - 1
        if route < 0:
            return None
        extras = {}
        def piece(lane, low, high, first, last):
            points = tuple(slice_polyline(lane.points, low, high))
            extras[len(self.graph_edges) + len(extras)] = (
                first, SimpleNamespace(destination=last, edge=MobilityLink('lane', LaneTraversal(lane, points))))
        if isinstance(source, LanePosition):
            piece(source.lane, source.distance, polyline_length(source.lane.points),
                  ('vehicle_query_start', id(source)), lane_end_node(source.lane))
        if isinstance(destination, LanePosition):
            piece(destination.lane, 0, destination.distance, lane_start_node(destination.lane),
                  ('vehicle_query_destination', id(destination)))
        if isinstance(source, LanePosition) and isinstance(destination, LanePosition) and source.lane is destination.lane and destination.distance >= source.distance:
            piece(source.lane, source.distance, destination.distance,
                  ('vehicle_query_start', id(source)), ('vehicle_query_destination', id(destination)))
        return self.path(route, source, destination, extras)

    def append(self, car, handle):
        sim, e = self.sim, self.engine
        with sim._roster_revision.mutate():
            sim._cars.append(car)
        car._on_occupancy_change = sim._mark_occupancy_changed
        sim.occupancy.publish_changes([car])
        e._ids[handle], e._handles[car.id] = car.id, handle
        e._next_handle = max(e._next_handle, handle + 1)

    def receive_generated(self):
        from traffic_testbed import RoutedRoadVehicle
        from mobility import vehicle_route_points
        e, sim = self.engine, self.sim
        count = C.c_int()
        pointer = e._lib.nt_generated(e._ptr, C.byref(count))
        if count.value < 0:
            raise ValueError(e._lib.nt_error().decode())
        records = [(r.handle, r.route, r.source, r.destination, r.color, r.number)
                   for r in (pointer[i] for i in range(count.value))]
        result = []
        for handle, route_id, source, destination, color, number in records:
            source, destination = self.junctions[source], self.junctions[destination]
            route = self.path(route_id, source, destination)
            car = RoutedRoadVehicle(source.id, destination.id, route, vehicle_route_points(route),
                                    sim.speed_mph * 22 / 15, sim.colors[color],
                                    source_type='test_traffic', id=f'test-car-{number:06d}')
            car.brain.merge_style = 'cautious' if number % 5 == 0 else 'rolling'
            self.append(car, handle)
            result.append(car)
        return result

    def spawn_car(self, source, destination):
        if source is destination:
            return None
        try:
            indices = self.endpoint_ids[id(source)], self.endpoint_ids[id(destination)]
        except KeyError:
            raise ValueError('Vehicle route junctions must belong to this city') from None
        self.configure()
        self.engine._call('nt_generate_one', *indices)
        self.publish_random()
        result = self.receive_generated()
        return result[0] if result else None

    def admit_route(self, route, *, vehicle_id, source_id, destination_id, appearance=None,
                    source_type='external', length=14.0, width=6.0, speed_cap_mph=None, color=None):
        from mobility import vehicle_route_points
        from models import polyline_length
        from traffic_testbed import RoutedRoadVehicle, _controlled_movement_ranges, _route_occupancy_segments
        from traffic_route_state import RouteState
        from vehicle import VehicleAppearance
        sim, e = self.sim, self.engine
        if vehicle_id in e._handles:
            return None
        points = vehicle_route_points(route)
        if len(points) < 2 or polyline_length(points) <= 0:
            return None
        retained = self.external_routes.get(id(route))
        if retained is None:
            proxy = SimpleNamespace(points=points, controlled_movements=_controlled_movement_ranges(route),
                                    route_segments=_route_occupancy_segments(route), _route_cache=RouteState())
            native_route = e.register_route(proxy)
            self.external_routes[id(route)] = (route, native_route)
        else:
            native_route = retained[1]
        self.configure()
        if not color:
            color = sim.colors[e._call('nt_choice', len(sim.colors))]
        self.publish_random()
        speed = min(sim.speed_mph, speed_cap_mph if speed_cap_mph is not None else sim.speed_mph) * 22 / 15
        if not isfinite(speed) or speed <= 0:
            raise ValueError('A road vehicle needs a positive speed')
        handle = e._next_handle
        spawn = _Spawn(handle, native_route, 0, 0, 0, int(source_type == 'test_traffic'),
                       0, speed, length, width, -1 if speed_cap_mph is None else speed_cap_mph, 0, 0, -1)
        if not e._call('nt_admit', C.byref(spawn), vehicle_id.encode()):
            return None
        car = RoutedRoadVehicle(source_id, destination_id, route, points, speed, color,
                                appearance=appearance if appearance is not None else VehicleAppearance(),
                                source_type=source_type, speed_cap_mph=speed_cap_mph,
                                length=length, width=width, id=vehicle_id)
        self.append(car, handle)
        return car

    def publish_bookkeeping(self):
        from intersection_controls import StopArrival
        sim, e = self.sim, self.engine
        count, clock = C.c_int(), Clock()
        pointer = e._lib.nt_bookkeeping(e._ptr, C.byref(count), C.byref(clock))
        if count.value < 0:
            raise ValueError(e._lib.nt_error().decode())
        coordinator = sim.stop_coordinator
        coordinator.arrivals.clear()
        coordinator.claims.clear()
        coordinator._claims_by_car.clear()
        resolver = sim.deadlock_resolver
        resolver._waiting_seconds.clear()
        for i in range(count.value):
            row = pointer[i]
            vehicle_id = e._ids[row.handle]
            if row.kind == 0:
                coordinator._store_claim(vehicle_id, e._connections[row.connection])
            elif row.kind == 1:
                coordinator.arrivals[vehicle_id] = StopArrival(vehicle_id, e._connections[row.connection], row.value)
            else:
                resolver._waiting_seconds[vehicle_id] = row.value
        resolver.stall_seconds, resolver.stall_threshold = clock.stall, clock.threshold
        resolver.winner_id = None if clock.winner < 0 else e._ids[clock.winner]
        resolver.winner_movement_id = None if clock.movement < 0 else e._connections[clock.movement].id
        resolver.hard_gridlock = bool(clock.hard)

    def publish_debugger(self, completed, timings, dt):
        sim, e = self.sim, self.engine
        count, vehicle_count = C.c_int(), C.c_int()
        rows = e._lib.nt_trace(e._ptr, C.byref(count))
        vehicles = e._lib.nt_trace_vehicles(e._ptr, C.byref(vehicle_count))
        if count.value < 0 or vehicle_count.value < 0:
            raise ValueError(e._lib.nt_error().decode())
        by_id = {car.id: car for car in (*sim.cars, *completed)}
        for i in range(count.value):
            row = rows[i]
            car = by_id[e._ids[row.handle]]
            movement = None if row.connection < 0 else (0, 0, e._connections[row.connection])
            observed = None
            if movement is not None and movement[2].merge_target is not None:
                observed = SimpleNamespace(vehicles=tuple(SimpleNamespace(id=e._ids[vehicles[j]]) for j in
                                                         range(row.first_vehicle, row.first_vehicle+row.vehicle_count)),
                                           reservations=range(row.reservations))
            sim.debugger.record_car(car, distance_before=row.distance, speed_before=row.speed,
                                    decision=SimpleNamespace(desired_speed=car.brain.desired_speed),
                                    movement=movement, has_priority=bool(row.priority), has_claim=bool(row.claimed),
                                    merge_observation=observed)
        resolver = sim.deadlock_resolver
        sim.debugger.end_frame(simulated_time=sim.elapsed_time, elapsed_seconds=dt, car_count=count.value,
                               completed_ids=[c.id for c in completed], timings_ms=timings,
                               deadlock_stall_seconds=resolver.stall_seconds, temporary_winner_id=resolver.winner_id,
                               hard_gridlock=resolver.hard_gridlock)

    def update(self, dt):
        sim, e = self.sim, self.engine
        started = perf_counter()
        if sim.debugger is not None:
            sim.debugger.begin_frame()
        self.configure()
        configured = perf_counter()
        e._call('nt_generate', dt)
        generated = perf_counter()
        self.publish_random()
        admitted = self.receive_generated()
        mirrored = perf_counter()
        sim.elapsed_time += dt
        e.step(dt)
        moved = perf_counter()
        self.publishing = True
        try:
            completed = e.sync(sim.cars)
            self.publish_bookkeeping()
            for car in sim.cars:
                sim._mark_occupancy_changed(car)
            if completed:
                removed = {id(car) for car in completed}
                with sim._roster_revision.mutate():
                    sim._cars[:] = [car for car in sim.cars if id(car) not in removed]
                for car in completed:
                    e._handles.pop(car.id, None)
            sim._publish_occupancy_changes(removed=completed)
        finally:
            self.publishing = False
        finished = perf_counter()
        timings = {'native_configuration': (configured-started)*1000, 'native_spawning': (generated-configured)*1000,
                   'spawn_views': (mirrored-generated)*1000, 'native_movement': (moved-mirrored)*1000,
                   'output_sync': (finished-moved)*1000, 'total': (finished-started)*1000}
        sim.profiler.record_tick(system='test_traffic', simulated_time=sim.elapsed_time, elapsed_seconds=dt,
                                 entity_counts={'cars': len(sim.cars), 'spawned': len(admitted), 'completed': len(completed)},
                                 timings_ms=timings)
        if sim.debugger is not None:
            self.publish_debugger(completed, timings, dt)
        return completed

    def close(self):
        self.engine.close()
