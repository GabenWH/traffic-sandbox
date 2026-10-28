"""Persistent C++ traffic driver. Python never supplies per-tick observations.

The small ctypes ABI keeps compiler dependencies out of Python packaging. Topology
and routes cross the boundary at admission; step() runs without Python callbacks.
vehicle_views() is a borrowed native buffer, valid until the next engine operation.
Use snapshot() for an owned, ID-keyed copy or sync() for existing UI vehicles.
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import os
import subprocess
import sys
import tempfile

from car_brain import BehaviorState, SignalIntent
from intersection_controls import movements_conflict, yields_to, StopArrival, SignalAspect
from models import ControlType, ManeuverType
from traffic_testbed import _route_state

STATES = tuple(BehaviorState)
SIGNALS = tuple(SignalIntent)
CONTROL = {ControlType.STOP: 1, ControlType.SIGNAL: 2}
MANEUVER = {ManeuverType.LEFT_TURN: 1, ManeuverType.RIGHT_TURN: 2, ManeuverType.U_TURN: 3}
ROLES = {'entry': 1, 'circulate': 2, 'exit': 3}


class _Connection(C.Structure):
    _fields_ = [(x, C.c_int) for x in ('intersection', 'control', 'maneuver', 'role', 'target')] + [
        (x, C.c_double) for x in ('hx', 'hy', 'px', 'py')]


class _Point(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)]


class NativePedestrianState(C.Structure):
    _fields_ = [('id', C.c_int), ('lane', C.c_int), ('waiting', C.c_int),
                ('distance', C.c_double), ('x', C.c_double), ('y', C.c_double)]


class _Section(C.Structure):
    _fields_ = [(x, C.c_double) for x in ('start', 'end', 'offset')] + [('key', C.c_int)]


class _Movement(C.Structure):
    _fields_ = [(x, C.c_double) for x in ('start', 'end', 'signal_start')] + [
        (x, C.c_int) for x in ('connection', 'incoming')]


class _Spawn(C.Structure):
    _fields_ = [(x, C.c_int) for x in ('handle', 'route', 'style', 'state', 'signal', 'generated')] + [
        (x, C.c_double) for x in ('distance', 'speed', 'length', 'width', 'cap', 'dwell', 'desired', 'entry')]


class _Profile(C.Structure):
    _fields_ = [('ticks', C.c_uint64), ('vehicle_visits', C.c_uint64)] + [
        (name, C.c_double) for name in (
            'preparation_ms', 'control_ms', 'decision_ms', 'arbitration_ms', 'movement_ms',
        )]


class _SharedVehicle(C.Structure):
    _fields_ = [('motion', C.POINTER(_Spawn)), ('position', C.POINTER(_Point)),
                ('heading', C.POINTER(_Point)), ('claim', C.POINTER(C.c_int)), ('yellow_movement', C.POINTER(C.c_int)), ('yellow_go', C.POINTER(C.c_bool))]


class NativeVehicleView(C.Structure):
    _fields_ = [(x, C.c_int) for x in ('handle', 'state', 'signal', 'claim', 'alive')] + [
        (x, C.c_double) for x in ('distance', 'speed', 'x', 'y', 'hx', 'hy', 'desired', 'dwell', 'entry')] + [
        ('reason', C.c_char_p), ('phantom', C.c_char_p), ('yellow_movement', C.c_int), ('yellow_go', C.c_int)]


@dataclass(frozen=True)
class NativeVehicleState:
    distance: float
    speed: float
    position: tuple[float, float]
    heading: tuple[float, float]
    state: str
    signal: str
    reason: str
    desired_speed: float
    stopped_elapsed: float
    claim: str | None
    alive: bool
    phantom: str


@lru_cache(maxsize=1)
def _library():
    root = Path(__file__).resolve().parent
    sources = [root / 'native/traffic/engine.cpp', *sorted((root / 'native/traffic').glob('*.h'))]
    compiler = os.environ.get('CXX', 'c++')
    digest = sha256(b''.join(p.read_bytes() for p in sources) + compiler.encode() + sys.platform.encode()).hexdigest()[:20]
    directory = root / 'build' / 'native-traffic'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ('engine-' + digest + ('.dylib' if sys.platform == 'darwin' else '.so'))
    if not target.exists():
        fd, name = tempfile.mkstemp(prefix='engine-', suffix='.so', dir=directory)
        os.close(fd)
        try:
            subprocess.run([compiler, '-std=c++17', '-O3', '-fPIC', '-shared', '-Wall', '-Wextra', '-Werror',
                            str(sources[0]), '-o', name], check=True, capture_output=True, text=True)
            os.replace(name, target)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Native traffic compilation failed:\n' + exc.stderr) from exc
        finally:
            Path(name).unlink(missing_ok=True)
    lib = C.CDLL(str(target))
    signatures = {
        'nt_abi': (C.c_int, []), 'nt_error': (C.c_char_p, []),
        'nt_create': (C.c_void_p, [C.c_double]), 'nt_destroy': (None, [C.c_void_p]),
        'nt_network': (C.c_int, [C.c_void_p, C.POINTER(_Connection), C.c_int, C.POINTER(C.c_ubyte), C.POINTER(C.c_ubyte)]),
        'nt_route': (C.c_int, [C.c_void_p, C.POINTER(_Point), C.c_int, C.POINTER(_Section), C.c_int, C.POINTER(_Movement), C.c_int]),
        'nt_connection_key': (C.c_int, [C.c_void_p, C.c_int, C.c_int]),
        'nt_spawn': (C.c_int, [C.c_void_p, C.POINTER(_Spawn), C.c_char_p, C.c_char_p, C.c_char_p]),
        'nt_yellow': (C.c_int, [C.c_void_p, C.c_int, C.c_int, C.c_int]),
        'nt_place': (C.c_int, [C.c_void_p, C.c_int, C.c_double]),
        'nt_resize': (C.c_int, [C.c_void_p, C.c_int, C.c_double, C.c_double]),
        'nt_remove': (C.c_int, [C.c_void_p, C.c_int]),
        'nt_external_claim': (C.c_int, [C.c_void_p, C.c_int, C.c_int]),
        'nt_claim': (C.c_int, [C.c_void_p, C.c_int, C.c_int]),
        'nt_arrival': (C.c_int, [C.c_void_p, C.c_int, C.c_int, C.c_double]),
        'nt_clock': (C.c_int, [C.c_void_p, C.c_double, C.c_double, C.c_double]),
        'nt_waiting': (C.c_int, [C.c_void_p, C.c_int, C.c_double]),
        'nt_winner': (C.c_int, [C.c_void_p, C.c_int, C.c_int, C.c_int]),
        'nt_key_speed': (C.c_int, [C.c_void_p, C.c_int, C.c_double]),
        'nt_speed': (C.c_int, [C.c_void_p, C.c_double]),
        'nt_control': (C.c_int, [C.c_void_p, C.c_int, C.c_int]),
        'nt_signal_aspects': (C.c_int, [C.c_void_p, C.POINTER(C.c_ubyte), C.c_int]),
        'nt_profile_enable': (C.c_int, [C.c_void_p, C.c_int]),
        'nt_profile_read': (C.c_int, [C.c_void_p, C.POINTER(_Profile)]),
        'nt_step': (C.c_int, [C.c_void_p, C.c_double]),
        'nt_pedestrian_lane': (C.c_int, [C.c_void_p, C.POINTER(_Point), C.c_int, C.c_double]),
        'nt_pedestrian_spawn': (C.c_int, [C.c_void_p, C.c_int, C.c_int, C.c_double]),
        'nt_pedestrian_waits': (C.c_int, [C.c_void_p]),
        'nt_pedestrian_states': (C.POINTER(NativePedestrianState), [C.c_void_p, C.POINTER(C.c_int)]),
        'nt_pedestrian_completed': (C.POINTER(NativePedestrianState), [C.c_void_p, C.POINTER(C.c_int)]),
        'nt_states': (C.POINTER(NativeVehicleView), [C.c_void_p, C.POINTER(C.c_int)]),
        'nt_shared_vehicle': (C.c_int, [C.c_void_p, C.c_int, C.POINTER(_SharedVehicle)]),
        'nt_shared_text': (C.c_char_p, [C.c_void_p, C.c_int, C.c_int]),
        'nt_completed': (C.POINTER(NativeVehicleView), [C.c_void_p, C.POINTER(C.c_int)]),
    }
    for name, (result, args) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, args
    if lib.nt_abi() != 4:
        raise RuntimeError('Incompatible native traffic ABI')
    from native_spawning import bind
    bind(lib)
    return lib


class NativeTrafficEngine:
    def __init__(self, speed_mph=25.0):
        self._lib = _library()
        self._ptr = self._lib.nt_create(speed_mph)
        if not self._ptr:
            raise ValueError(self._lib.nt_error().decode())
        self._ids = {}
        self._handles = {}
        self._next_handle = 0
        self._connections = []
        self._connection_ids = {}
        self._connection_ids_by_name = {}
        self._signal_aspects = None
        self._keys = {}
        self._intersections = {}
        self._routes = {}
        self._shared_bindings = {}

    def _call(self, name, *args):
        if not self._ptr:
            raise RuntimeError('Native traffic engine is closed')
        result = getattr(self._lib, name)(self._ptr, *args)
        if result < 0:
            raise ValueError(self._lib.nt_error().decode())
        return result

    @classmethod
    def from_simulation(cls, traffic):
        engine = cls(traffic.speed_mph)
        try:
            engine.prepare(traffic.cars)
            engine.prepare_connections(traffic.stop_coordinator.claims.values())
            for car in traffic.cars:
                engine.spawn(car)
            for car in traffic.cars:
                for connection in traffic.stop_coordinator.claims_for(car.id):
                    engine._call('nt_claim', engine._handles[car.id], engine._connection_ids[id(connection)])
            foreign = {}
            for (owner, _), connection in traffic.stop_coordinator.claims.items():
                if owner not in engine._handles:
                    handle = foreign.setdefault(owner, -1-len(foreign))
                    engine._ids[handle] = owner
                    engine._call('nt_external_claim', handle, engine._connection_ids[id(connection)])
            for car_id, arrival in traffic.stop_coordinator.arrivals.items():
                if car_id not in engine._handles:
                    continue
                engine._call('nt_arrival', engine._handles[car_id], engine._connection_ids[id(arrival.connection)], arrival.stopped_at)
            resolver = traffic.deadlock_resolver
            engine._call('nt_clock', traffic.elapsed_time, resolver.stall_seconds, resolver.stall_threshold)
            for car_id, seconds in resolver._waiting_seconds.items():
                if car_id in engine._handles:
                    engine._call('nt_waiting', engine._handles[car_id], seconds)
            if resolver.winner_id is not None:
                winner = engine._handles[resolver.winner_id]
                movement = next(i for i, con in enumerate(engine._connections)
                                if con.id == resolver.winner_movement_id)
                engine._call('nt_winner', winner, movement, int(resolver.hard_gridlock))
            return engine
        except BaseException:
            engine.close()
            raise

    def _key(self, key):
        return self._keys.setdefault(key, len(self._keys))

    def prepare(self, cars):
        """Compile new topology only at admission; existing numeric IDs stay stable."""
        self.prepare_connections(connection for car in cars for _, _, connection in car.controlled_movements)

    def prepare_connections(self, connections):
        changed = False
        for connection in connections:
            if id(connection) not in self._connection_ids:
                self._connection_ids[id(connection)] = len(self._connections)
                self._connection_ids_by_name[connection.id] = len(self._connections)
                self._connections.append(connection)
                changed = True
        if not changed:
            return
        rows = []
        for con in self._connections:
            intersection = self._intersections.setdefault(con.intersection_id, len(self._intersections))
            rows.append(_Connection(intersection, CONTROL.get(con.control.kind, 0), MANEUVER.get(con.maneuver.kind, 0),
                                    ROLES.get(con.roundabout_role, 2 if con.roundabout_role else 0),
                                    -1 if con.merge_target is None else self._key(con.merge_target),
                                    *con.source_output.heading, *con.source_output.position))
        n = len(rows)
        from native_spawning import Relation
        groups = {}
        for i, connection in enumerate(self._connections):
            groups.setdefault(connection.intersection_id, []).append((i, connection))
        pairs = []
        for group in groups.values():
            for i, a in group:
                for j, b in group:
                    flags = int(movements_conflict(a, b)) | (int(yields_to(StopArrival('', a, 0), StopArrival('', b, 0))) << 1)
                    if flags:
                        pairs.append(Relation(i, j, flags))
        self._call('nt_network_sparse', (_Connection * n)(*rows), n, (Relation * len(pairs))(*pairs), len(pairs))
        for i, con in enumerate(self._connections):
            self._call('nt_connection_key', i, self._key(('lane_connection', con.id)))

    def register_route(self, car):
        self.prepare((car,))
        for link in getattr(getattr(car, 'route', None), 'edges', ()):
            lane = getattr(link.value, 'lane', None) if hasattr(link, 'value') else None
            if getattr(link, 'kind', None) == 'lane' and lane is None:
                lane = link.value
            if lane is not None and lane.speed_limit_mph is not None:
                self._call('nt_key_speed', self._key(('lane', lane.id)), lane.speed_limit_mph)
        signature = (id(car.points), id(car.route_segments), id(car.controlled_movements))
        route = self._routes.get(signature)
        if route is None:
            points = (_Point * len(car.points))(*(_Point(*p) for p in car.points))
            sections = (_Section * len(car.route_segments))(*(
                _Section(start, end, offset, self._key(key)) for start, end, key, offset in car.route_segments))
            state = _route_state(car)
            movements = (_Movement * len(car.controlled_movements))(*(
                _Movement(m[0], m[1], -1 if state.signal_start(m) is None else state.signal_start(m),
                          self._connection_ids[id(m[2])], self._key(state.incoming(m)))
                for m in car.controlled_movements))
            route = self._call('nt_route', points, len(points), sections, len(sections), movements, len(movements))
            # Retain source tuples: identity keys must not be recycled by Python.
            self._routes[signature] = route
            if not hasattr(self, '_route_sources'):
                self._route_sources = []
            self._route_sources.append((car.points, car.route_segments, car.controlled_movements))
        return route

    def spawn(self, car):
        if car.id in self._handles:
            raise ValueError('Duplicate native vehicle ID: ' + car.id)
        route = self.register_route(car)
        handle = self._next_handle
        spawn = _Spawn(handle, route, int(car.brain.merge_style == 'cautious'), STATES.index(car.brain.state),
                       SIGNALS.index(car.brain.signal_intent), int(car.source_type == 'test_traffic'), car.distance, car.speed, car.length, car.width,
                       -1 if car.speed_cap_mph is None else car.speed_cap_mph, car.brain.stopped_elapsed,
                       car.brain.desired_speed, -1 if car._merge_entry_speed is None else car._merge_entry_speed)
        self._call('nt_spawn', C.byref(spawn), car.id.encode(), car.brain.wait_reason.encode(), car.brain.phantom_target.encode())
        yellow = self._connection_ids_by_name.get(car.brain._yellow_movement_id, -1)
        if yellow >= 0:
            self._call('nt_yellow', handle, yellow, int(car.brain._yellow_go))
        self._ids[handle], self._handles[car.id] = car.id, handle
        self._next_handle += 1

    def step(self, dt):
        self._call('nt_step', dt)

    def register_pedestrian_lane(self, points, crossing_fraction=-1.0):
        """Register a separate pedestrian-only route once; points are world feet."""
        points = tuple(points)
        array = (_Point * len(points))(*(_Point(*point) for point in points))
        return self._call('nt_pedestrian_lane', array, len(points), crossing_fraction)

    def spawn_pedestrian(self, person_id, lane_id, speed):
        """Admit an active walker; movement occurs inside subsequent nt_step calls."""
        self._call('nt_pedestrian_spawn', person_id, lane_id, speed)

    def _pedestrian_rows(self, function):
        if not self._ptr:
            raise RuntimeError('Native traffic engine is closed')
        count = C.c_int()
        pointer = getattr(self._lib, function)(self._ptr, C.byref(count))
        if count.value < 0:
            raise RuntimeError(self._lib.nt_error().decode())
        return [NativePedestrianState.from_buffer_copy(pointer[i]) for i in range(count.value)]

    def pedestrian_states(self):
        return self._pedestrian_rows('nt_pedestrian_states')

    def completed_pedestrians(self):
        return self._pedestrian_rows('nt_pedestrian_completed')

    def pedestrian_waits(self):
        return self._call('nt_pedestrian_waits')

    def vehicle_views(self):
        """Borrow native records; do not retain them across engine calls."""
        if not self._ptr:
            raise RuntimeError('Native traffic engine is closed')
        count = C.c_int()
        pointer = self._lib.nt_states(self._ptr, C.byref(count))
        if count.value < 0:
            raise RuntimeError(self._lib.nt_error().decode())
        return C.cast(pointer, C.POINTER(NativeVehicleView * count.value)).contents if count.value else ()

    def snapshot(self, *, include_completed=False):
        return {self._ids[s.handle]: NativeVehicleState(
            s.distance, s.speed, (s.x, s.y), (s.hx, s.hy), STATES[s.state].value, SIGNALS[s.signal].value,
            s.reason.decode(), s.desired, s.dwell, None if s.claim < 0 else self._connections[s.claim].id,
            bool(s.alive), s.phantom.decode()) for s in self.vehicle_views() if s.alive or include_completed}

    def sync(self, cars):
        """Explicit output-only synchronization for render/debug consumers."""
        by_id = {c.id: c for c in cars}
        completed = []
        for s in self.vehicle_views():
            car = by_id[self._ids[s.handle]]
            car.__dict__.update(distance=s.distance, speed=s.speed,
                position=(s.x, s.y), heading=(s.hx, s.hy),
                _merge_entry_speed=None if s.entry < 0 else s.entry,
                _claimed_movement=None if s.claim < 0 else self._connections[s.claim])
            car.brain.__dict__.update(state=STATES[s.state], signal_intent=SIGNALS[s.signal],
                wait_reason=s.reason.decode(), phantom_target=s.phantom.decode(),
                desired_speed=s.desired, stopped_elapsed=s.dwell,
                _yellow_movement_id=None if s.yellow_movement < 0 else self._connections[s.yellow_movement].id,
                _yellow_go=bool(s.yellow_go))
            if not s.alive:
                completed.append(car)
        return completed

    def place(self, vehicle_id, distance):
        self._call('nt_place', self._handles[vehicle_id], distance)

    def resize(self, vehicle_id, length, width):
        self._call('nt_resize', self._handles[vehicle_id], length, width)

    def remove(self, vehicle_id):
        handle = self._handles[vehicle_id]
        binding = self._shared_bindings.get(handle)
        if binding is not None:
            binding.detach()
        self._call('nt_remove', handle)
        del self._handles[vehicle_id]

    def set_speed(self, speed_mph):
        self._call('nt_speed', speed_mph)

    def set_control(self, connection, kind):
        self._call('nt_control', self._connection_ids[id(connection)], CONTROL.get(kind, 0))

    def set_signal_aspects(self, aspects):
        aspects = tuple(aspects)
        if aspects != self._signal_aspects:
            values = (C.c_ubyte * len(aspects))(*aspects)
            self._call('nt_signal_aspects', values, len(aspects))
            self._signal_aspects = aspects

    def enable_profile(self, enabled=True):
        self._call('nt_profile_enable', int(enabled))

    def profile_snapshot(self):
        profile = _Profile()
        self._call('nt_profile_read', C.byref(profile))
        return {
            'ticks': profile.ticks,
            'vehicle_visits': profile.vehicle_visits,
            'preparation_ms': profile.preparation_ms,
            'control_ms': profile.control_ms,
            'decision_ms': profile.decision_ms,
            'arbitration_ms': profile.arbitration_ms,
            'movement_ms': profile.movement_ms,
        }

    def close(self):
        if getattr(self, '_ptr', None):
            for binding in tuple(self._shared_bindings.values()):
                binding.detach()
            self._lib.nt_destroy(self._ptr)
            self._ptr = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()
