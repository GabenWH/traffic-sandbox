"""Shared city road vehicles and optional junction-generated traffic."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections.abc import Sequence
from itertools import count
from functools import partial
from math import dist, isfinite, sqrt
import random
from time import perf_counter
from types import MappingProxyType
from typing import Callable

from city import CityMap
from car_brain import (CarBrain, CarDecision, CarObservation, BehaviorState,
                       COMFORTABLE_BRAKING)
from intersection_controls import (AllWayStopCoordinator, FixedTimeSignalController,
                                   SignalAspect, movements_conflict)
from merge_behavior import observe_merge, MERGE_STRATEGIES, MergeTrafficSnapshot
from soft_deadlock import DeadlockCandidate, SoftDeadlockResolver, merge_space_clear
from simulation_profiler import SimulationProfiler
from simulation_cache import CachedValue, RevisionSource
from mobility import (
    LaneTraversal,
    MobilityLink,
    MobilityNode,
    PortTraversal,
    nearest_lane_position,
    vehicle_link_points,
    vehicle_route_points,
)
from models import ManeuverType, ControlType, Intersection, Lane, LaneConnection, Point, polyline_length
from pathfinding import Path
from traffic_occupancy import TrafficOccupancyIndex
from traffic_network_cache import JunctionLookup
from traffic_route_state import RouteGeometry, RouteState
from traffic_debugger import TrafficDebugger
from units import mph_to_pixels_per_second
from vehicle import VehicleAppearance, vehicle_footprints_overlap


TEST_CAR_SPEED_MPH = 25.0
TEST_SPAWN_INTERVAL = 1.5
TEST_TRAFFIC_LIMIT = 60
TEST_CAR_ACCELERATION = 10.0
TEST_CAR_BRAKING = 24.0
TEST_CAR_FOLLOWING_GAP = 22.0
TEST_CAR_LOOKAHEAD = 128.0
_car_ids = count(1)


@dataclass(frozen=True)
class TrafficIntent:
    """One car's decision from the immutable start-of-tick traffic snapshot."""

    car: "RoutedRoadVehicle"
    distance_before: float
    speed_before: float
    route_movement: tuple[float, float, LaneConnection] | None
    movement: tuple[float, float, LaneConnection] | None
    has_claim: bool
    is_merge: bool
    merge_observation: object | None
    priority: bool
    distance_to_stop: float | None
    lead_car: "RoutedRoadVehicle" | None
    lead_distance: float | None
    decision: CarDecision
    signal_entry: bool = False


@dataclass
class RoutedRoadVehicle:
    """Progress and behavior state for one routed city road vehicle."""

    source_id: str
    destination_id: str
    route: Path[MobilityNode, MobilityLink]
    points: tuple[Point, ...]
    speed: float
    color: str
    appearance: VehicleAppearance = field(default_factory=VehicleAppearance)
    source_type: str = "external"
    speed_cap_mph: float | None = None
    distance: float = 0.0
    position: Point = field(init=False)
    heading: Point = field(init=False)
    total_length: float = field(init=False)
    item: int | None = None
    rendered: bool = False
    render_style: str | None = None
    length: float = 14.0
    width: float = 6.0
    id: str = field(default_factory=lambda: f"test-car-{next(_car_ids)}")
    brain: CarBrain = field(default_factory=CarBrain)
    controlled_movements: tuple[tuple[float, float, LaneConnection], ...] = field(
        init=False, repr=False,
    )
    signal_merge_movements: tuple[tuple[float, float, LaneConnection], ...] = field(
        init=False, repr=False,
    )
    _controlled_movement_by_id: dict[str, tuple[float, float, LaneConnection]] = field(
        init=False, repr=False,
    )
    route_segments: tuple[tuple[float, float, tuple[object, ...], float], ...] = field(
        init=False, repr=False,
    )
    _occupancy_segment_index: int = field(default=0, init=False, repr=False)
    _route_cache: RouteState = field(default_factory=RouteState, init=False, repr=False, compare=False)
    _geometry: RouteGeometry = field(default_factory=RouteGeometry, init=False, repr=False, compare=False)
    _on_occupancy_change: Callable | None = field(default=None, init=False, repr=False, compare=False)
    _occupancy_route_segments: object = field(default=None, init=False, repr=False)
    _claimed_movement: LaneConnection | None = field(default=None, init=False, repr=False)
    cruise_speed_bound: float = field(default=TEST_CAR_SPEED_MPH*22/15, init=False)
    _merge_entry_speed: float | None = field(default=None, init=False, repr=False)
    signal_items: list[int] = field(default_factory=list, repr=False)

    def __setattr__(self, name, value):
        if name in ('distance', 'speed', 'position', 'heading', 'length', 'width',
                    'speed_cap_mph', 'brain', '_claimed_movement', '_merge_entry_speed',
                    'id', 'source_type', 'route', 'points', 'route_segments',
                    'controlled_movements', 'signal_merge_movements', 'total_length'):
            callback = self.__dict__.get('_on_native_edit')
            if callback is not None:
                if name == 'id' and self.__dict__.get('id') != value:
                    raise AttributeError('An admitted vehicle ID is read-only; remove and admit a new vehicle')
                callback()
        previous_brain = self.__dict__.get('brain') if name == 'brain' else None
        object.__setattr__(self, name, value)
        if name == 'brain':
            if previous_brain is not None and previous_brain is not value:
                previous_brain._on_native_edit = None
            if self.__dict__.get('_on_native_edit') is not None:
                value._on_native_edit = self._on_native_edit

    def __post_init__(self) -> None:
        self.total_length = polyline_length(list(self.points))
        if len(self.points) < 2 or self.total_length <= 0:
            raise ValueError("A road vehicle needs a non-degenerate path")
        if not isfinite(self.speed) or self.speed <= 0:
            raise ValueError("A road vehicle needs a positive speed")
        if any(not isfinite(size) or size <= 0 for size in (self.length, self.width)):
            raise ValueError("A road vehicle needs positive finite dimensions")
        self.controlled_movements = _controlled_movement_ranges(self.route)
        self.signal_merge_movements = tuple(
            item for item in self.controlled_movements
            if item[2].merge_target is not None
        )
        self._controlled_movement_by_id = {
            movement[2].id: movement for movement in self.controlled_movements
        }
        self.route_segments = _route_occupancy_segments(self.route)
        self._route_cache.sync(self.controlled_movements, self.route_segments)
        self.position, self.heading = self._geometry.position_and_heading(self.points, 0.0)

    def advance(self, elapsed_seconds: float) -> bool:
        """Advance the car and return whether it still lies on its route."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        self.distance = min(self.total_length, self.distance + self.speed * elapsed_seconds)
        # Substeps can accumulate a few trillionths of a foot of rounding error.
        if self.total_length - self.distance < 1e-8:
            self.distance = self.total_length
        self.position, self.heading = self._geometry.position_and_heading(self.points, self.distance)
        if self._on_occupancy_change is not None:
            self._on_occupancy_change(self)
        return self.distance < self.total_length

    def place(self, distance: float) -> None:
        """Explicitly place/rewind a vehicle and queue its occupancy update."""
        if not isfinite(distance):
            raise ValueError("Vehicle distance must be finite")
        self.distance = max(0.0, min(self.total_length, distance))
        self.advance(0.0)

    @property
    def claimed_movement(self) -> LaneConnection | None:
        return self._claimed_movement

    def controlled_movement_for(
        self, connection: LaneConnection,
    ) -> tuple[float, float, LaneConnection] | None:
        movement = self._controlled_movement_by_id.get(connection.id)
        return movement if movement is not None and movement[2] is connection else None

    def active_claimed_movements(
        self, coordinator: AllWayStopCoordinator,
    ) -> tuple[tuple[float, float, LaneConnection], ...]:
        movements = (
            self.controlled_movement_for(connection)
            for connection in coordinator.claims_for(self.id)
        )
        return tuple(movement for movement in movements if movement is not None)

    def inside_claimed_movement(self, coordinator: AllWayStopCoordinator) -> bool:
        front = self.distance + self.length / 2
        rear = self.distance - self.length / 2
        return any(
            start <= front and rear < end
            for start, end, _connection in self.active_claimed_movements(coordinator)
        ) or any(
            coordinator.has_signal_occupancy(self.id, connection)
            for _start, _end, connection in self.controlled_movements
            if connection.control.kind is ControlType.SIGNAL
        )

    def occupancy_position(self) -> tuple[tuple[object, ...], float] | None:
        """Return canonical mobility-link key and longitudinal position."""
        if self._occupancy_route_segments is not self.route_segments:
            self._occupancy_segment_index = 0
            self._occupancy_route_segments = self.route_segments
        index = self._occupancy_segment_index
        # Ordinary motion advances this cursor; direct placement/rewinding can
        # also move it backwards without leaving the old lane occupied.
        while index > 0 and self.distance < self.route_segments[index - 1][1]:
            index -= 1
        while index < len(self.route_segments):
            start, end, key, offset = self.route_segments[index]
            if self.distance < end or end == self.total_length:
                self._occupancy_segment_index = index
                return key, offset + max(0.0, min(end - start, self.distance - start))
            index += 1
        self._occupancy_segment_index = index
        return None


class _ReadOnlySequence(Sequence):
    """A live collection view whose mutations belong to the simulation."""

    def __init__(self, items):
        self._items = items

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, index):
        return self._items[index]

    def __eq__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        return self._items == list(other)

    def __repr__(self):
        return repr(self._items)


@dataclass
class RoadVehicleSimulation:
    """Advance all city road vehicles and generate optional test traffic."""

    spawn_interval: float = TEST_SPAWN_INTERVAL
    max_cars: int = TEST_TRAFFIC_LIMIT
    speed_mph: float = TEST_CAR_SPEED_MPH
    rng: random.Random = field(default_factory=random.Random, repr=False)
    active_junction_ids: Sequence[str] = field(default_factory=list)
    cars: Sequence[RoutedRoadVehicle] = field(default_factory=list)
    _cars: list[RoutedRoadVehicle] = field(default_factory=list, init=False, repr=False)
    _active_junction_ids: list[str] = field(default_factory=list, init=False, repr=False)
    _spawn_elapsed: dict[str, float] = field(default_factory=dict, repr=False)
    stop_coordinator: AllWayStopCoordinator = field(
        default_factory=AllWayStopCoordinator, repr=False,
    )
    signal_controllers: dict[str, FixedTimeSignalController] = field(
        default_factory=dict, repr=False,
    )
    _signal_states: dict = field(default_factory=dict, init=False, repr=False)
    _signal_permissions: dict = field(default_factory=dict, init=False, repr=False)
    _signal_connections: dict = field(default_factory=dict, init=False, repr=False)
    _signal_network_token: tuple | None = field(default=None, init=False, repr=False)
    _signal_validation_key: tuple | None = field(default=None, init=False, repr=False)
    elapsed_time: float = 0.0
    _spawned_count: int = field(default=0, init=False, repr=False)
    _network_token: tuple[int, int] | None = field(default=None, init=False, repr=False)
    _spawn_routes: dict[tuple[int, int], Path[MobilityNode, MobilityLink] | None] = field(
        default_factory=dict, init=False, repr=False,
    )
    _junction_lookup: JunctionLookup = field(
        default_factory=JunctionLookup, init=False, repr=False, compare=False,
    )
    _sources_revision: RevisionSource = field(
        default_factory=lambda: RevisionSource("traffic sources"), init=False, repr=False,
    )
    _roster_revision: RevisionSource = field(
        default_factory=lambda: RevisionSource("traffic roster"), init=False, repr=False,
    )
    _source_junctions: object = field(default=None, init=False, repr=False)
    _sources_synced_stamp: object = field(default=None, init=False, repr=False)
    _sources_view: CachedValue = field(init=False, repr=False)
    _roster_view: CachedValue = field(init=False, repr=False)
    _occupancy_dirty: bool = field(default=False, init=False, repr=False)
    _occupancy_changes: dict[int, RoutedRoadVehicle] = field(
        default_factory=dict, init=False, repr=False,
    )
    occupancy: TrafficOccupancyIndex = field(
        default_factory=TrafficOccupancyIndex, repr=False,
    )
    # Optional recorder.  It observes completed decisions; it never feeds a
    # decision back into the traffic model.
    debugger: TrafficDebugger | None = field(default=None, repr=False)
    profiler: SimulationProfiler = field(
        default_factory=SimulationProfiler, repr=False,
    )
    deadlock_resolver: SoftDeadlockResolver = field(
        default_factory=SoftDeadlockResolver, repr=False,
    )
    update_mode: str = "cpp"
    native_output_mode: str = "copy"
    _native_controller: object = field(default=None, init=False, repr=False, compare=False)

    colors = ("#ff5b72", "#37e6ff", "#f7d154", "#7fea8c", "#c98cff")

    @property
    def vehicles(self) -> list[RoutedRoadVehicle]:
        """All active city road users, regardless of their purpose."""
        return self.cars

    def __setattr__(self, name, value):
        if name in ("cars", "active_junction_ids") and isinstance(
                self.__dict__.get(name), _ReadOnlySequence):
            raise AttributeError(f"{name} is read-only; use the simulation mutation APIs")
        if name in ("update_mode", "native_output_mode") and self.__dict__.get(name) != value and self.__dict__.get("_native_controller") is not None:
            self._discard_native()
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        if not isfinite(self.spawn_interval) or self.spawn_interval <= 0:
            raise ValueError("Test-traffic spawn interval must be positive")
        if self.max_cars < 1:
            raise ValueError("Test traffic must allow at least one car")
        if not isfinite(self.speed_mph) or self.speed_mph <= 0:
            raise ValueError("Test-traffic speed must be positive")
        self._validate_update_mode()
        if len({car.id for car in self.cars}) != len(self.cars):
            raise ValueError("Preloaded traffic cars must have unique IDs")
        self._cars = list(self.cars)
        self._active_junction_ids = list(self.active_junction_ids)
        self.cars = _ReadOnlySequence(self._cars)
        self.active_junction_ids = _ReadOnlySequence(self._active_junction_ids)
        self._spawned_count = len(self.cars)
        self._sources_view = CachedValue(
            "active traffic sources",
            dependencies=(*self._junction_lookup.dependencies, self._sources_revision),
            build=lambda: tuple(self._source_junctions[item] for item in self.active_junction_ids),
        )
        self._roster_view = CachedValue(
            "traffic roster", dependencies=(self._roster_revision,),
            build=lambda: (
                tuple(sorted(self.cars, key=lambda car: car.id)),
                MappingProxyType({car.id: car for car in self.cars}),
                sum(car.source_type == "test_traffic" for car in self.cars),
            ),
        )
        self.occupancy.rebuild(self.cars)
        self.occupancy._refresh = self._ensure_occupancy
        for car in self.cars:
            car._on_occupancy_change = self._mark_occupancy_changed
            self._watch_native_edits(car)

    def _cars_snapshot(self) -> tuple[RoutedRoadVehicle, ...]:
        return self._roster_view.get()[0]

    def _watch_native_edits(self, car):
        callback = partial(self._native_input_changed, car)
        car._on_native_edit = car.brain._on_native_edit = callback

    def _native_input_changed(self, car=None):
        controller = self._native_controller
        if controller is not None and controller.publishing:
            return
        if car is not None:
            if getattr(car._on_occupancy_change, '__self__', None) is not self:
                return
            self._occupancy_changes[id(car)] = car
            with self._roster_revision.mutate():
                pass
        self._discard_native()

    def _mark_occupancy_changed(self, car: RoutedRoadVehicle) -> None:
        # Explicit advance/place calls on a public vehicle view are inputs too.
        # Reimport the complete mirrored state before the next native operation.
        if self._native_controller is not None and not self._native_controller.publishing:
            self._discard_native()
        identity = id(car)
        if identity not in self._occupancy_changes:
            self._occupancy_changes[identity] = car

    def _ensure_occupancy(self):
        """Refresh Python's optional query index only when a consumer asks."""
        if self._occupancy_dirty:
            self.occupancy.rebuild(self.cars)
            self._occupancy_changes.clear()
            self._occupancy_dirty = False
        elif self._occupancy_changes:
            pending = tuple(self._occupancy_changes.values())
            self._occupancy_changes.clear()
            self.occupancy.publish_changes(pending)

    def _publish_occupancy_changes(self, *, removed=()) -> bool:
        for car in removed:
            self._occupancy_changes.pop(id(car), None)
            car._on_occupancy_change = None
            car._on_native_edit = None
            car.brain._on_native_edit = None
        if self._occupancy_dirty:
            self._ensure_occupancy()
            return True
        if self._occupancy_changes or removed:
            self.occupancy.publish_changes(self._occupancy_changes.values(), removed=removed)
            self._occupancy_changes.clear()
            return True
        return False

    def _validate_update_mode(self) -> None:
        if self.native_output_mode not in ("copy", "shared"):
            raise ValueError("Native output mode must be copy or shared")
        if self.update_mode != "cpp":
            raise ValueError("Traffic update mode must be cpp")

    def _native_backend(self, city_map=None):
        if self._native_controller is None:
            from native_spawning import NativeRoadSimulation
            self._native_controller = NativeRoadSimulation(self, city_map)
        elif city_map is not None:
            self._native_controller.bind_city(city_map)
        return self._native_controller

    def _discard_native(self):
        if self._native_controller is not None:
            self._native_controller.close()
            self._native_controller = None

    def signal_is_green(self, connection: LaneConnection) -> bool:
        """Return the configured signal permission for one movement.

        Signal controls without a matching controller fail closed, so a
        partially configured intersection cannot silently behave like yield.
        """
        controller_id = connection.control.controller_id
        controller = self.signal_controllers.get(controller_id) if controller_id else None
        return controller is not None and controller.is_green(
            connection.id, self.elapsed_time,
        )

    def _signal_aspect(self, connection: LaneConnection):
        controller_id = connection.control.controller_id
        if not controller_id:
            return None
        return self._signal_permissions.get(controller_id, {}).get(connection.id)

    def _signal_step_limit(self) -> float:
        limit = 0.05
        for controller in self.signal_controllers.values():
            boundary = controller.next_boundary_after(self.elapsed_time)
            if 0 < boundary - self.elapsed_time < 1e-10:
                self.elapsed_time = boundary
                boundary = controller.next_boundary_after(self.elapsed_time)
            limit = min(limit, boundary - self.elapsed_time)
        return limit

    def _prepare_signal_frame(self, city_map: CityMap) -> None:
        states = {key: controller.state_at(self.elapsed_time)
                  for key, controller in self.signal_controllers.items() if key}
        state_changed = states != self._signal_states
        self._signal_states = states
        token = (id(city_map), city_map.mobility_revision)
        network_changed = token != self._signal_network_token
        if network_changed:
            self._signal_connections = {}
            for layer in city_map.mobility.layers.values():
                for node in layer.graph.nodes:
                    for transition in layer.graph.transitions_from(node):
                        if transition.edge.kind == "lane_connection":
                            connection = transition.edge.value
                            self._signal_connections[connection.id] = connection
            self._signal_network_token = token
            self._signal_validation_key = None
            self.stop_coordinator.configure_signal_conflicts(
                self._signal_connections.values(),
            )
        if state_changed or network_changed:
            self._signal_permissions = {
                controller_id: {
                    movement_id: state.aspect
                    for movement_id in state.movement_ids
                }
                for controller_id, state in states.items()
                if state.aspect in (SignalAspect.GREEN, SignalAspect.YELLOW)
            }
        green = []
        for controller_id, state in self._signal_states.items():
            if state.aspect not in (SignalAspect.GREEN, SignalAspect.YELLOW):
                continue
            for movement_id in sorted(state.movement_ids):
                connection = self._signal_connections.get(movement_id)
                if (connection is not None and connection.control.kind is ControlType.SIGNAL
                        and connection.control.controller_id == controller_id):
                    green.append(connection)
        key = tuple((connection.id, connection.control.controller_id) for connection in green)
        if key != self._signal_validation_key:
            for index, connection in enumerate(green):
                for other in green[index + 1:]:
                    if (connection.source_output != other.source_output
                            and movements_conflict(connection, other)):
                        raise ValueError("Conflicting protected signal permissions: "
                                         + connection.id + " and " + other.id)
            self._signal_validation_key = key
        # C++ owns physical signal occupancy; the previous native event snapshot
        # remains available until the next native step publishes its result.

    def _observe_signal_occupancy(self) -> None:
        self.stop_coordinator.observe_signal_occupants(
            (car.id, connection)
            for car in self.cars
            for start, end, connection in car.controlled_movements
            if connection.control.kind is ControlType.SIGNAL
            and car.distance + car.length / 2 > start + 1e-8
            and car.distance - car.length / 2 < end
        )

    def _observe_signal_car(self, car: RoutedRoadVehicle) -> None:
        self.stop_coordinator.observe_signal_car(
            car.id,
            (connection for start, end, connection in car.controlled_movements
             if connection.control.kind is ControlType.SIGNAL
             and car.distance + car.length / 2 > start + 1e-8
             and car.distance - car.length / 2 < end),
        )

    def sync_network(self, city_map: CityMap) -> tuple[bool, list[RoutedRoadVehicle]]:
        """Discard routes made for an older version of the city lane graph."""
        token = (id(city_map), city_map.mobility_revision)
        if self._network_token is None:
            self._network_token = token
            return False, []
        if token == self._network_token:
            return False, []
        self._network_token = token
        self._spawn_routes.clear()
        return True, self.clear_vehicles()

    def toggle_junction(self, junction: Intersection) -> bool:
        """Toggle a junction as a combined source/sink; return its new state."""
        with self._sources_revision.mutate():
            if junction.id in self.active_junction_ids:
                self._active_junction_ids.remove(junction.id)
                self._spawn_elapsed.pop(junction.id, None)
                return False
            self._active_junction_ids.append(junction.id)
            self._spawn_elapsed[junction.id] = 0.0
            return True

    def is_active(self, junction: Intersection) -> bool:
        return junction.id in self.active_junction_ids

    def active_junctions(self, city_map: CityMap) -> list[Intersection]:
        return list(self._active_junctions_snapshot(city_map))

    def _active_junctions_snapshot(self, city_map: CityMap) -> tuple[Intersection, ...]:
        by_id = self._junction_lookup.get(city_map)
        if (by_id is not self._source_junctions
                or self._sources_synced_stamp != self._sources_revision.stamp()):
            with self._sources_revision.mutate():
                self._source_junctions = by_id
                self._active_junction_ids[:] = [
                    item for item in self.active_junction_ids if item in by_id
                ]
                for item in tuple(self._spawn_elapsed):
                    if item not in self.active_junction_ids:
                        del self._spawn_elapsed[item]
                for item in self.active_junction_ids:
                    self._spawn_elapsed.setdefault(item, 0.0)
            self._sources_synced_stamp = self._sources_revision.stamp()
        return self._sources_view.get()

    def spawn_car(self, city_map, source, destination, *, _occupancy=None):
        """Request native routing and admission for one generated vehicle."""
        self.sync_network(city_map)
        return self._native_backend(city_map).spawn_car(source, destination)

    def admit_route(self, route, *, vehicle_id, source_id, destination_id,
                    appearance=None, source_type="external", length=14.0,
                    width=6.0, speed_cap_mph=None, color=None, _occupancy=None):
        """Request native body/gap clearance and admission for an external trip."""
        return self._native_backend().admit_route(
            route, vehicle_id=vehicle_id, source_id=source_id, destination_id=destination_id,
            appearance=appearance, source_type=source_type, length=length, width=width,
            speed_cap_mph=speed_cap_mph, color=color)

    def update(self, city_map, elapsed_seconds):
        """Advance the sole C++ driver and return completed vehicle events."""
        self._validate_update_mode()
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        self.sync_network(city_map)
        limit = self._signal_step_limit()
        if elapsed_seconds > limit + 1e-10:
            completed = []
            remaining = elapsed_seconds
            while remaining > 1e-9:
                step = min(self._signal_step_limit(), remaining)
                completed.extend(self.update(city_map, step))
                remaining -= step
            return completed
        self._prepare_signal_frame(city_map)
        return self._native_backend(city_map).update(elapsed_seconds)


    def clear_vehicles(self) -> list[RoutedRoadVehicle]:
        """Remove every active city road vehicle and release its claims."""
        self._discard_native()
        removed = list(self.cars)
        for car in removed:
            self.stop_coordinator.forget_car(car.id)
            car._claimed_movement = None
        with self._roster_revision.mutate():
            self._cars.clear()
        self._publish_occupancy_changes(removed=removed)
        self.deadlock_resolver.reset()
        return removed

    def _vehicle(self, vehicle_id: str) -> RoutedRoadVehicle:
        try:
            return self._roster_view.get()[1][vehicle_id]
        except KeyError:
            raise KeyError(f"Unknown road vehicle: {vehicle_id}") from None

    def place_vehicle(self, vehicle_id: str, distance: float) -> None:
        """Publish a manual placement before the next occupancy query."""
        self._vehicle(vehicle_id).place(distance)
        if self._native_controller is not None:
            self._native_controller.engine.place(vehicle_id, distance)
        self._publish_occupancy_changes()

    def resize_vehicle(self, vehicle_id: str, *, length: float, width: float) -> None:
        if any(not isfinite(size) or size <= 0 for size in (length, width)):
            raise ValueError("Vehicle dimensions must be positive and finite")
        car = self._vehicle(vehicle_id)
        car.length, car.width = length, width
        if self._native_controller is not None:
            self._native_controller.engine.resize(vehicle_id, length, width)
        self._mark_occupancy_changed(car)
        self._publish_occupancy_changes()

    def replace_vehicle_route(self, vehicle_id: str, route, *, distance: float = 0.0) -> None:
        """Replace route metadata and discard claims from the old route."""
        car = self._vehicle(vehicle_id)
        points = vehicle_route_points(route)
        total_length = polyline_length(list(points))
        if len(points) < 2 or total_length <= 0 or not isfinite(distance):
            raise ValueError("A road vehicle needs a non-degenerate route and finite distance")
        movements = _controlled_movement_ranges(route)
        segments = _route_occupancy_segments(route)
        # Validate the route source's write guard before changing live fields.
        car._route_cache.sync(movements, segments)
        self._discard_native()
        self.stop_coordinator.forget_car(vehicle_id)
        car.route, car.points, car.total_length = route, points, total_length
        car.controlled_movements, car.route_segments = movements, segments
        car._controlled_movement_by_id = {m[2].id: m for m in movements}
        car._claimed_movement = None
        car._merge_entry_speed = None
        car.brain = CarBrain()
        car.place(distance)
        self._publish_occupancy_changes()

    def reorder_vehicles(self, vehicle_ids) -> None:
        """Lab/setup operation: replace processing and equal-position tie order."""
        ids = tuple(vehicle_ids)
        by_id = self._roster_view.get()[1]
        if len(ids) != len(by_id) or set(ids) != set(by_id):
            raise ValueError("Vehicle order must contain each active ID exactly once")
        if ids == tuple(car.id for car in self.cars):
            return
        self._discard_native()
        with self._roster_revision.mutate():
            self._cars[:] = [by_id[item] for item in ids]
        # Explicit processing-order replacement also replaces occupancy tie order.
        self.occupancy.rebuild(self.cars)
        self._occupancy_changes.clear()

    def clear_cars(self) -> list[RoutedRoadVehicle]:
        """Compatibility name for clearing the shared vehicle collection."""
        return self.clear_vehicles()

    def remove_vehicle(self, vehicle_id: str) -> RoutedRoadVehicle | None:
        """Remove one routed vehicle and release its intersection claims."""
        car = next((item for item in self.cars if item.id == vehicle_id), None)
        if car is None:
            return None
        if self._native_controller is not None:
            self._native_controller.engine.remove(vehicle_id)
        with self._roster_revision.mutate():
            self._cars.remove(car)
        self.stop_coordinator.forget_car(car.id)
        car._claimed_movement = None
        self._publish_occupancy_changes(removed=[car])
        self.deadlock_resolver.reset()
        return car

    def clear_test_traffic(self) -> list[RoutedRoadVehicle]:
        """Clear source-generated cars without interrupting delivery vehicles."""
        removed = [car for car in self.cars if car.source_type == "test_traffic"]
        for car in removed:
            self.remove_vehicle(car.id)
        with self._sources_revision.mutate():
            self._active_junction_ids.clear()
            self._spawn_elapsed.clear()
        return removed

    def clear(self) -> list[RoutedRoadVehicle]:
        removed = self.clear_vehicles()
        with self._sources_revision.mutate():
            self._active_junction_ids.clear()
            self._spawn_elapsed.clear()
        return removed


def _position_and_heading(points: tuple[Point, ...], distance_along: float) -> tuple[Point, Point]:
    remaining = max(0.0, float(distance_along))
    last_heading = (1.0, 0.0)
    for start, end in zip(points, points[1:]):
        length = dist(start, end)
        if length == 0:
            continue
        heading = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
        last_heading = heading
        if remaining <= length:
            fraction = remaining / length
            return (
                (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                ),
                heading,
            )
        remaining -= length
    return points[-1], last_heading


def _controlled_movement_ranges(
    route: Path[MobilityNode, MobilityLink],
) -> tuple[tuple[float, float, LaneConnection], ...]:
    distance_along = 0.0
    result: list[tuple[float, float, LaneConnection]] = []
    for link in route.edges:
        points = vehicle_link_points(link)
        length = polyline_length(list(points)) if len(points) >= 2 else 0.0
        if link.kind == "lane_connection" and isinstance(link.value, LaneConnection):
            result.append((distance_along + link.value.control_offset, distance_along + length, link.value))
        distance_along += length
    return tuple(result)


def _route_occupancy_segments(
    route: Path[MobilityNode, MobilityLink],
) -> tuple[tuple[float, float, tuple[object, ...], float], ...]:
    distance_along = 0.0
    result: list[tuple[float, float, tuple[object, ...], float]] = []
    for link in route.edges:
        points = vehicle_link_points(link)
        length = polyline_length(list(points)) if len(points) >= 2 else 0.0
        if length <= 0:
            continue
        key: tuple[object, ...]
        offset = 0.0
        if link.kind == "lane" and isinstance(link.value, Lane):
            key = ("lane", link.value.id)
        elif link.kind == "lane" and isinstance(link.value, LaneTraversal):
            key = ("lane", link.value.lane.id)
            offset = nearest_lane_position(link.value.lane, link.value.points[0])[0].distance
        elif link.kind == "road_port" and isinstance(link.value, PortTraversal):
            key = ("road_port", link.value.port.id, link.value.lane.id)
        elif link.kind == "lane_connection" and isinstance(link.value, LaneConnection):
            key = ("lane_connection", link.value.id)
        else:
            distance_along += length
            continue
        result.append((distance_along, distance_along + length, key, offset))
        distance_along += length
    return tuple(result)


def _entry_claim_distance(speed: float) -> float:
    """Include a rolling lead vehicle before its nose can enter the junction."""
    return max(10.0, speed * 0.6)


def _intersection_priority(
    car, movement, distance_to_stop, coordinator, *, signal_green: bool = False,
    signal_yellow: bool = False,
) -> bool:
    if movement is None:
        return False
    connection = movement[2]
    if connection.control.kind is ControlType.SIGNAL:
        if not (signal_green or signal_yellow):
            return False
        if (distance_to_stop is not None
                and distance_to_stop > _entry_claim_distance(car.speed)):
            return True
        return coordinator.can_enter_signal(car.id, connection)
    if connection.merge_target is not None:
        return coordinator.can_enter_merge(car.id, connection)
    if (connection.control.kind is not ControlType.STOP
            and distance_to_stop is not None
            and distance_to_stop > _entry_claim_distance(car.speed)):
        return coordinator.can_approach(car.id, connection)
    return coordinator.can_claim(car.id, connection)


def _observe_priority_arrivals(
    cars, coordinator, elapsed_time, signal_controllers=None,
) -> set[str]:
    """Register only the entry-ready front vehicle of each incoming lane.

    Route distance to the entry compares cars with different route origins.
    The shared incoming lane key also groups different turn intentions that
    are physically queued behind one another. Active claims are kept until
    the existing rear-clearance rule releases them.
    """
    heads = {}
    for car in cars:
        movement = _next_controlled_movement(car, coordinator)
        if movement is None:
            continue
        start, _, connection = movement
        if connection.merge_target is not None:
            if (coordinator.has_claim(car.id, connection)
                    and car.distance + car.length / 2 < start):
                coordinator.release(car.id, connection)
                car._claimed_movement = None
        connector_start = start - connection.control_offset
        incoming = _route_state(car).incoming(movement)
        key = (connection.intersection_id, incoming)
        distance = connector_start - car.length / 2 - car.distance
        previous = heads.get(key)
        if previous is None or (distance, car.id) < (previous[2], previous[0].id):
            heads[key] = (car, movement, distance)

    ready = []
    for car, movement, _ in heads.values():
        distance = max(0.0, movement[0] - car.length / 2 - car.distance)
        connection = movement[2]
        if connection.merge_target is not None:
            continue
        if connection.control.kind is ControlType.SIGNAL:
            continue
        if not coordinator.has_claim(car.id, connection):
            if distance > _entry_claim_distance(car.speed):
                continue
            if (connection.control.kind is ControlType.STOP
                    and (distance > 0.05 or car.speed > 0.1)):
                continue
        ready.append((car, connection, distance))
    eligible = {car.id: connection for car, connection, _ in ready
                if not coordinator.has_claim(car.id, connection)
                and connection.control.kind is not ControlType.SIGNAL}
    coordinator.retain_arrivals(eligible)
    for car, connection, distance in ready:
        if car.id not in eligible:
            continue
        if connection.control.kind is ControlType.STOP:
            coordinator.observe_stop(car.id, connection, elapsed_time)
        else:
            coordinator.observe_approach(
                car.id, connection, elapsed_time + distance / max(car.speed, 1.0),
            )
    return {car.id for car, _, _ in ready}


def _route_state(car):
    state = car._route_cache
    state.sync(car.controlled_movements, car.route_segments)
    return state


def _signal_is_green(connection, signal_controllers, elapsed_time) -> bool:
    controller_id = connection.control.controller_id
    controller = signal_controllers.get(controller_id or "")
    return controller is not None and controller.is_green(connection.id, elapsed_time)


def _next_controlled_movement(
    car: RoutedRoadVehicle, coordinator: AllWayStopCoordinator,
) -> tuple[float, float, LaneConnection] | None:
    """Find the next entrance to obey, separately from junction occupancy.

    Once the nose enters with permission, look ahead to the next stop/yield.
    The previous claim stays alive until the rear clears that junction.
    """
    return _route_state(car).next_controlled(
        car.distance, car.length,
        lambda connection: (coordinator.has_claim(car.id, connection)
                            or coordinator.has_signal_occupancy(car.id, connection)),
    )


def _next_route_movement(
    car: RoutedRoadVehicle,
) -> tuple[float, float, LaneConnection] | None:
    return _route_state(car).next_route(car.distance)


def _route_cruise_speed(car, speed_mph):
    """Brake before the tight circle, and keep a modest speed until the exit."""
    if car.speed_cap_mph is not None:
        speed_mph = min(speed_mph, car.speed_cap_mph)
    cruise = mph_to_pixels_per_second(speed_mph)
    curve_speed = mph_to_pixels_per_second(min(speed_mph, 12.0))
    active = _route_state(car).next_roundabout(car.distance - car.length / 2)
    if active is not None:
        start, _end, movement = active
        distance = max(0.0, start - car.distance - car.length / 2)
        if movement.roundabout_role == "exit":
            distance = 0.0
        return min(cruise, sqrt(curve_speed**2 + 2 * TEST_CAR_BRAKING * distance))
    return cruise


# Compatibility names for code that still presents user-generated city traffic
# as test cars. Both names refer to the same actor and simulation types.
RoutedTestCar = RoutedRoadVehicle
TestTrafficSimulation = RoadVehicleSimulation


def _signaled_maneuver(car, movement):
    """Wait until the final ring section before signaling the chosen exit."""
    if movement is None:
        return None
    start, end, connection = movement
    if connection.roundabout_role == "exit":
        signal_start = _route_state(car).signal_start(movement)
        if signal_start is not None and car.distance < signal_start:
            return None
    return connection.maneuver.kind


def _temporary_winner_path_clear(
    car, movement, cars, occupancy, coordinator, merge_snapshot=None,
):
    """Check physical space without re-applying conservative social gaps.

    A temporary winner may break a right-of-way tie, but it may not drive into
    a bumper, a committed movement, or an occupied merge point.  Four feet is
    the same small physical margin used by the final same-route travel guard.
    """
    if movement is None or not coordinator.can_claim_temporary_winner(
            car.id, movement[2]):
        return False
    lead_gap = occupancy.lead_gap(car, TEST_CAR_LOOKAHEAD)
    if lead_gap is not None and lead_gap < 4.0:
        return False
    exit_gap = occupancy.gap_from(car, movement[1], TEST_CAR_LOOKAHEAD)
    if exit_gap is not None and exit_gap < 4.0:
        return False
    if movement[2].merge_target is not None:
        observation = observe_merge(car, movement, cars, snapshot=merge_snapshot)
        if observation is None or not merge_space_clear(
                car.length, observation.vehicles, observation.reservations):
            return False

    # Preserve the existing chain-signal rule.  A clear first intersection is
    # not a safe escape when the car cannot fit before the next yield.  Check
    # each close following movement with physical (not comfort) clearances.
    chain_end = movement[1]
    for following in _route_state(car).following(movement):
        if following[0] < movement[1]:
            continue
        if following[0] - chain_end >= car.length + 4.0:
            break
        if not coordinator.can_claim_temporary_winner(car.id, following[2]):
            return False
        following_exit = occupancy.gap_from(car, following[1], TEST_CAR_LOOKAHEAD)
        if following_exit is not None and following_exit < 4.0:
            return False
        if following[2].merge_target is not None:
            observation = observe_merge(car, following, cars, snapshot=merge_snapshot)
            if observation is None or not merge_space_clear(
                    car.length, observation.vehicles, observation.reservations):
                return False
        chain_end = following[1]
    return True
