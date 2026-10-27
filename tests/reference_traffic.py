"""Frozen Python traffic engines for differential tests only.

Source: acbc399, before the C++ consolidation. Not an application mode.
"""
from __future__ import annotations
"""Shared city road vehicles and optional junction-generated traffic."""



from dataclasses import dataclass, field, replace
from collections.abc import Sequence
from itertools import count
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
    update_mode: str = "legacy"
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
        for car in self.cars:
            car._on_occupancy_change = self._mark_occupancy_changed

    def _cars_snapshot(self) -> tuple[RoutedRoadVehicle, ...]:
        return self._roster_view.get()[0]

    def _mark_occupancy_changed(self, car: RoutedRoadVehicle) -> None:
        # Explicit advance/place calls on a public vehicle view are inputs too.
        # Reimport the complete mirrored state before the next native operation.
        if self._native_controller is not None and not self._native_controller.publishing:
            self._discard_native()
        identity = id(car)
        if identity not in self._occupancy_changes and not self.occupancy.is_current(car):
            self._occupancy_changes[identity] = car

    def _publish_occupancy_changes(self, *, removed=()) -> bool:
        for car in removed:
            self._occupancy_changes.pop(id(car), None)
            car._on_occupancy_change = None
        if self._occupancy_changes or removed:
            self.occupancy.publish_changes(self._occupancy_changes.values(), removed=removed)
            self._occupancy_changes.clear()
            return True
        return False

    def _validate_update_mode(self) -> None:
        if self.native_output_mode not in ("copy", "shared"):
            raise ValueError("Native output mode must be copy or shared")
        if self.update_mode not in ("legacy", "data_first", "native"):
            raise ValueError("Traffic update mode must be legacy or data_first or native")

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
        self._observe_signal_occupancy()

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

    def spawn_car(
        self,
        city_map: CityMap,
        source: Intersection,
        destination: Intersection,
        *,
        _occupancy: TrafficOccupancyIndex | None = None,
    ) -> RoutedRoadVehicle | None:
        """Spawn one car when a directed route exists between two junctions."""
        self.sync_network(city_map)
        if self.update_mode == "native":
            return self._native_backend(city_map).spawn_car(source, destination)
        if source is destination or self._roster_view.get()[2] >= self.max_cars:
            return None
        route_key = (id(source), id(destination))
        if route_key not in self._spawn_routes:
            self._spawn_routes[route_key] = city_map.find_vehicle_route_between(
                source, destination,
            )
        route = self._spawn_routes[route_key]
        if route is None:
            return None
        existing_ids = self._roster_view.get()[1]
        next_spawn_id = self._spawned_count + 1
        while f"test-car-{next_spawn_id:06d}" in existing_ids:
            next_spawn_id += 1
        car = self.admit_route(
            route,
            source_id=source.id,
            destination_id=destination.id,
            vehicle_id=f"test-car-{next_spawn_id:06d}",
            color=self.rng.choice(self.colors),
            source_type="test_traffic",
            _occupancy=_occupancy,
        )
        if car is None:
            return None
        self._spawned_count = next_spawn_id
        car.brain.merge_style = "cautious" if self._spawned_count % 5 == 0 else "rolling"
        return car

    def admit_route(
        self,
        route: Path[MobilityNode, MobilityLink],
        *,
        vehicle_id: str,
        source_id: str,
        destination_id: str,
        appearance: VehicleAppearance | None = None,
        source_type: str = "external",
        length: float = 14.0,
        width: float = 6.0,
        speed_cap_mph: float | None = None,
        color: str | None = None,
        _occupancy: TrafficOccupancyIndex | None = None,
    ) -> RoutedRoadVehicle | None:
        """Enter a vehicle only when its whole body and forward gap are clear.

        Publish pending placements before checking the retained occupancy index.
        """
        if self.update_mode == "native":
            return self._native_backend().admit_route(
                route, vehicle_id=vehicle_id, source_id=source_id, destination_id=destination_id,
                appearance=appearance, source_type=source_type, length=length, width=width,
                speed_cap_mph=speed_cap_mph, color=color,
            )
        if vehicle_id in self._roster_view.get()[1]:
            return None
        points = vehicle_route_points(route)
        if len(points) < 2 or polyline_length(list(points)) <= 0:
            return None
        initial_speed_mph = min(
            self.speed_mph,
            speed_cap_mph if speed_cap_mph is not None else self.speed_mph,
        )
        if appearance is None:
            appearance = VehicleAppearance()
        car = RoutedRoadVehicle(
            source_id=source_id,
            destination_id=destination_id,
            route=route,
            points=points,
            speed=mph_to_pixels_per_second(initial_speed_mph),
            color=color or self.rng.choice(self.colors),
            appearance=appearance,
            source_type=source_type,
            speed_cap_mph=speed_cap_mph,
            length=length,
            width=width,
            id=vehicle_id,
        )
        # Route clearance only sees cars ahead on shared links. A vehicle just
        # behind the insertion point, or crossing it on another link, can still
        # intersect the new body. Check the actual rectangles before admission.
        if any(vehicle_footprints_overlap(car, other) for other in self.cars):
            return None
        occupancy = _occupancy
        if occupancy is None:
            self._publish_occupancy_changes()
            occupancy = self.occupancy
        spawn_gap = occupancy.lead_gap(car, TEST_CAR_FOLLOWING_GAP + car.length)
        if spawn_gap is not None and spawn_gap < TEST_CAR_FOLLOWING_GAP:
            return None
        with self._roster_revision.mutate():
            self._cars.append(car)
        car._on_occupancy_change = self._mark_occupancy_changed
        # Include admission in every remaining decision, including this spawn batch.
        self.occupancy.publish_changes([car])
        return car

    def update(self, city_map: CityMap, elapsed_seconds: float) -> list[RoutedRoadVehicle]:
        """Spawn and advance test cars, returning cars that reached a sink."""
        self._validate_update_mode()
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("Elapsed time must be finite and nonnegative")
        self.sync_network(city_map)
        # Keep observations frequent even when the UI fast-forwards or a test
        # advances several seconds at once. Otherwise a car can skip a whole
        # entrance between two decisions.
        step_limit = self._signal_step_limit()
        if elapsed_seconds > step_limit + 1e-10:
            completed = []
            remaining = elapsed_seconds
            while remaining > 1e-9:
                step = min(self._signal_step_limit(), remaining)
                completed.extend(self.update(city_map, step))
                remaining -= step
            return completed
        if self.update_mode == "native":
            self._prepare_signal_frame(city_map)
            return self._native_backend(city_map).update(elapsed_seconds)
        self._discard_native()
        frame_started = perf_counter()
        if self.debugger is not None:
            self.debugger.begin_frame()
        self._prepare_signal_frame(city_map)
        self.elapsed_time += elapsed_seconds
        self._publish_occupancy_changes()
        junctions = self._active_junctions_snapshot(city_map)
        if len(junctions) >= 2:
            available_slots = self.max_cars - self._roster_view.get()[2]
            spawn_occupancy = None
            for source in junctions:
                self._spawn_elapsed[source.id] += elapsed_seconds
                if self._spawn_elapsed[source.id] < self.spawn_interval:
                    continue
                self._spawn_elapsed[source.id] %= self.spawn_interval
                # Keep seeded destination choices stable while capped, even
                # though no admissions or route searches are needed.
                destinations = [item for item in junctions if item is not source]
                self.rng.shuffle(destinations)
                if available_slots <= 0:
                    continue
                if spawn_occupancy is None:
                    spawn_occupancy = self.occupancy
                for destination in destinations:
                    if self.spawn_car(
                        city_map, source, destination, _occupancy=spawn_occupancy,
                    ) is not None:
                        available_slots -= 1
                        break
        spawned_at = perf_counter()

        if self.update_mode == "data_first":
            return self._update_data_first(
                elapsed_seconds,
                frame_started=frame_started,
                spawned_at=spawned_at,
            )

        # Observe EVERY approach before granting ANY entry. The order of cars
        # in the Python list must not decide who gets right of way.
        for car in self.cars:
            # A queued circulating car may accelerate back to its road speed.
            # Its current speed alone is not a safe prediction of future travel.
            car.cruise_speed_bound = _route_cruise_speed(car, self.speed_mph)
        priority_contenders = _observe_priority_arrivals(
            self.cars, self.stop_coordinator, self.elapsed_time,
            self.signal_controllers,
        )
        deadlock_candidates = []
        for car in self.cars:
            is_waiting = (
                car.speed <= 0.1
                and car.brain.state.value
                in ("waiting_for_priority", "entering_intersection")
            )
            if car.id != self.deadlock_resolver.winner_id and not is_waiting:
                continue
            movement = _next_controlled_movement(car, self.stop_coordinator)
            if movement is None or movement[2].control.kind is ControlType.SIGNAL:
                continue
            deadlock_candidates.append(DeadlockCandidate(
                car.id,
                ((movement[2].merge_target is not None
                  or car.id in priority_contenders)
                 and (movement[2].control.kind is not ControlType.SIGNAL
                      or self.signal_is_green(movement[2])))
                and car.brain.wait_reason != "following queued car"
                and _temporary_winner_path_clear(
                    car, movement, self.cars, self.occupancy,
                    self.stop_coordinator,
                ),
                movement_id=movement[2].id,
            ))
        deadlock_candidates = tuple(deadlock_candidates)
        temporary_winner = self.deadlock_resolver.choose_winner(deadlock_candidates)
        observed_at = perf_counter()
        # This is the number that was actually considered this frame.  A car
        # finishing later in the frame is still present in its trace record.
        frame_car_count = len(self.cars)
        completed: list[RoutedRoadVehicle] = []
        temporary_winner_entered = False
        decision_seconds = 0.0
        resolution_seconds = 0.0
        for car in list(self.cars):
            distance_before = car.distance
            speed_before = car.speed
            route_movement = _next_route_movement(car)
            movement = _next_controlled_movement(car, self.stop_coordinator)
            has_claim = (
                movement is not None
                and self.stop_coordinator.has_claim(car.id, movement[2])
            )
            inside = car.inside_claimed_movement(self.stop_coordinator)
            distance_to_stop = (
                max(0.0, movement[0] - car.length / 2 - car.distance)
                if movement is not None and not has_claim
                else None
            )
            is_merge = movement is not None and movement[2].merge_target is not None
            merge_observation = observe_merge(car, movement, self.cars) if is_merge else None
            signal_movement = (
                movement is not None
                and movement[2].control.kind is ControlType.SIGNAL
            )
            signal_aspect = self._signal_aspect(movement[2]) if signal_movement else None
            signal_green = signal_movement and not has_claim and signal_aspect is SignalAspect.GREEN
            signal_yellow = signal_movement and signal_aspect is SignalAspect.YELLOW
            signal_red = (
                signal_movement
                and not has_claim
                and not signal_green and not signal_yellow
            )
            priority = _intersection_priority(
                car, movement, distance_to_stop, self.stop_coordinator,
                signal_green=signal_green, signal_yellow=signal_yellow,
            )
            priority_reason = "waiting for intersection priority"
            if movement is not None and not has_claim and not is_merge:
                # Reserve enough space for our whole car beyond the movement.
                # Stopping across the exit would block everyone else's path.
                exit_gap = self.occupancy.gap_from(car, movement[1], TEST_CAR_LOOKAHEAD)
                if exit_gap is not None and exit_gap < TEST_CAR_FOLLOWING_GAP + car.length / 2:
                    priority = False
                    priority_reason = "waiting for room beyond the junction"
                # A short link is not a waiting area: our rear would still
                # block this junction if we had to stop at the next yield.
                # Look through consecutive short links before entering. This
                # is a prediction, not a permanent reservation of the circle;
                # the real yield is checked again as the nose approaches it.
                chain_end = movement[1]
                for following in _route_state(car).following(movement):
                    if following[0] < movement[1]:
                        continue
                    if following[0] - chain_end >= car.length + 4.0:
                        break
                    if following[2].merge_target is not None:
                        opening = MERGE_STRATEGIES[car.brain.merge_style].decide(
                            observe_merge(car, following, self.cars), car.speed,
                            _route_cruise_speed(car, self.speed_mph))
                        if (not opening.can_enter or not self.stop_coordinator.can_enter_merge(
                                car.id, following[2])):
                            priority = False
                            priority_reason = "waiting before short link for the next yield"
                            break
                    chain_end = following[1]
            lead_distance = self.occupancy.lead_gap(car, TEST_CAR_LOOKAHEAD)
            cruise_speed = _route_cruise_speed(car, self.speed_mph)
            # While approaching, phantom following chooses a pace. Once we
            # enter, keep the speed plan that was checked when granting entry.
            # Ordinary following can still brake for a real vehicle ahead.
            active_merge_ranges = (
                *_route_state(car).claimed_ranges(self.stop_coordinator.claims_for(car.id)),
                *car.signal_merge_movements,
            )
            for active in active_merge_ranges:
                if (active[2].merge_target is not None
                        and (self.stop_coordinator.has_claim(car.id, active[2])
                             or active[2].control.kind is ControlType.SIGNAL)
                        and car.distance + car.length/2 >= active[0]
                        and car.distance - car.length/2 < active[1]):
                    # Execute the plan checked at approval. Changing phantom
                    # targets mid-entry must not accelerate beyond that plan.
                    if car._merge_entry_speed is not None:
                        cruise_speed = min(cruise_speed, car._merge_entry_speed)
            decision_started = perf_counter() if self.debugger is not None else 0.0
            decision = car.brain.decide(
                CarObservation(
                    cruise_speed=cruise_speed,
                    speed=car.speed,
                    distance_to_stop=distance_to_stop,
                    must_stop=movement is not None and not has_claim and movement[2].control.kind is ControlType.STOP,
                    must_yield=(
                        movement is not None and not has_claim
                        and movement[2].control.kind not in (
                            ControlType.STOP, ControlType.SIGNAL,
                        )
                    ),
                    signal_red=signal_red,
                    signal_movement_id=movement[2].id if movement else "",
                    signal_green=signal_green, signal_yellow=signal_yellow,
                    priority_reason=priority_reason,
                    merge=merge_observation,
                    has_priority=priority,
                    lead_car_distance=lead_distance,
                    following_gap=car.brain.following_distance(car.speed),
                    inside_intersection=inside,
                    next_maneuver=_signaled_maneuver(car, route_movement),
                    distance_to_maneuver=(
                        max(0.0, route_movement[0] - car.distance)
                        if route_movement is not None else None
                    ),
                    inside_maneuver=(
                        route_movement is not None
                        and route_movement[0] <= car.distance < route_movement[1]
                    ),
                    temporary_winner=car.id == temporary_winner,
                    temporary_winner_blocked=(
                        car.id == self.deadlock_resolver.winner_id
                        and temporary_winner is None
                    ),
                ),
                elapsed_seconds,
            )
            if self.debugger is not None:
                decision_seconds += perf_counter() - decision_started
            resolution_started = perf_counter() if self.debugger is not None else 0.0
            if decision.register_stop and movement is not None and car.id in priority_contenders:
                self.stop_coordinator.observe_stop(car.id, movement[2], self.elapsed_time)
            if (decision.request_claim and movement is not None
                    and (is_merge or car.id in priority_contenders)
                    and (distance_to_stop or 0) <= _entry_claim_distance(car.speed)):
                # Claim only near entry; a car far up the road should not reserve
                # an empty junction for several seconds while it approaches.
                if car.id == temporary_winner:
                    has_claim = self.stop_coordinator.claim_temporary_winner(
                        car.id, movement[2])
                else:
                    if is_merge:
                        has_claim = self.stop_coordinator.claim_merge(car.id, movement[2])
                    else:
                        has_claim = self.stop_coordinator.claim(car.id, movement[2])
                if has_claim:
                    car._claimed_movement = movement[2]
                    if is_merge:
                        car._merge_entry_speed = decision.merge_entry_speed
                        # Begin the checked plan in this same update; do not
                        # spend one tick executing the old approach target.
                        decision = replace(decision, desired_speed=decision.merge_entry_speed)

            if is_merge and decision.signal_entry_allowed:
                car._merge_entry_speed = decision.merge_entry_speed
                decision = replace(decision, desired_speed=decision.merge_entry_speed)

            speed_delta = decision.desired_speed - car.speed
            limit = (TEST_CAR_ACCELERATION if speed_delta > 0 else TEST_CAR_BRAKING) * elapsed_seconds
            car.speed += max(-limit, min(limit, speed_delta))
            travel = car.speed * elapsed_seconds
            if lead_distance is not None:
                travel = min(
                    travel,
                    # Physical overlap guard. Comfortable following distance is
                    # chosen by CarBrain and should not become another stop wall.
                    max(0.0, lead_distance - 4.0),
                )
                if travel == 0.0:
                    car.speed = 0.0
            if movement is not None and not (has_claim or decision.signal_entry_allowed):
                stop_distance = movement[0] - car.length / 2
                travel = min(travel, max(0.0, stop_distance - car.distance))
                if travel == 0.0:
                    car.speed = 0.0
            alive = car.advance(travel / car.speed if car.speed > 0 else 0.0)
            if (car.id == temporary_winner and has_claim and movement is not None
                    and car.distance + car.length/2 >= movement[0]):
                temporary_winner_entered = True
            # Keep every junction occupied until our REAR clears it, even
            # while our FRONT is already obeying the next yield or stop.
            for _, end, connection in car.active_claimed_movements(self.stop_coordinator):
                if car.distance - car.length / 2 >= end:
                    self.stop_coordinator.release(car.id, connection)
            remaining_claims = self.stop_coordinator.claims_for(car.id)
            car._claimed_movement = remaining_claims[-1] if remaining_claims else None
            self._observe_signal_car(car)
            # Later legacy decisions see only this accepted car's new pose.
            self._mark_occupancy_changed(car)
            self._publish_occupancy_changes()
            if not alive:
                completed.append(car)
                self.stop_coordinator.forget_car(car.id)
            if self.debugger is not None:
                self.debugger.record_car(
                    car,
                    distance_before=distance_before,
                    speed_before=speed_before,
                    decision=decision,
                    movement=movement,
                    has_priority=priority,
                    # Report the resolved claim, rather than the fact that
                    # existed before this car asked for one this frame.
                    has_claim=(movement is not None and self.stop_coordinator.has_claim(
                        car.id, movement[2])),
                    merge_observation=merge_observation,
                )
                resolution_seconds += perf_counter() - resolution_started
        if completed:
            with self._roster_revision.mutate():
                for car in completed:
                    self._cars.remove(car)
            self._publish_occupancy_changes(removed=completed)
        stopped_count = sum(car.speed <= 0.1 for car in self.cars)
        traffic_is_flowing = bool(self.cars) and stopped_count < 0.8 * len(self.cars)
        self.deadlock_resolver.observe_frame(
            elapsed_seconds,
            # A few cars creeping inches inside a forty-car standstill are not
            # meaningful throughput. Keep the winner committed until its nose
            # enters the conflict; otherwise its first cautious movement would
            # cancel the very intent meant to break the hesitation cycle.
            made_progress=traffic_is_flowing or bool(completed) or (not deadlock_candidates and bool(self._signal_states)),
            candidate_ids=tuple(candidate.car_id for candidate in deadlock_candidates),
            winner_resolved=(
                temporary_winner_entered
                or any(car.id == self.deadlock_resolver.winner_id for car in completed)
            ),
        )
        finished_at = perf_counter()
        self.profiler.record_tick(
            system="routed_traffic",
            simulated_time=self.elapsed_time,
            elapsed_seconds=elapsed_seconds,
            entity_counts={"cars": frame_car_count},
            timings_ms={
                "spawn": (spawned_at - frame_started) * 1000,
                "observe": (observed_at - spawned_at) * 1000,
                "legacy_update": (finished_at - observed_at) * 1000,
                "total": (finished_at - frame_started) * 1000,
            },
        )
        if self.debugger is not None:
            self.debugger.end_frame(
                simulated_time=self.elapsed_time,
                elapsed_seconds=elapsed_seconds,
                car_count=frame_car_count,
                completed_ids=[car.id for car in completed],
                timings_ms={
                    "spawn": (spawned_at - frame_started) * 1000,
                    "observe": (observed_at - spawned_at) * 1000,
                    # Intent is just CarBrain.  Resolution is the claim,
                    # acceleration clamp, movement, and occupancy refresh that
                    # converts that intent into this frame's final position.
                    "decision": decision_seconds * 1000,
                    "resolution": resolution_seconds * 1000,
                    "total": (finished_at - frame_started) * 1000,
                },
                deadlock_stall_seconds=self.deadlock_resolver.stall_seconds,
                temporary_winner_id=(
                    temporary_winner or self.deadlock_resolver.winner_id
                ),
                hard_gridlock=self.deadlock_resolver.hard_gridlock,
            )
        return completed

    def _update_data_first(
        self,
        elapsed_seconds: float,
        *,
        frame_started: float,
        spawned_at: float,
    ) -> list[RoutedRoadVehicle]:
        """Advance one frame as snapshot -> intents -> resolve -> batch apply."""
        occupancy_phase_seconds: dict[str, float] = (
            dict.fromkeys(("occupancy_position_lookup", "occupancy_bin_build",
                           "occupancy_section_mapping", "occupancy_finalize"), 0.0)
            if self.occupancy.profile_internal_timings else {}
        )

        def publish_occupancy(removed=()) -> None:
            published = self._publish_occupancy_changes(removed=removed)
            if published and self.occupancy.profile_internal_timings:
                for name, duration_ms in self.occupancy.last_rebuild_timings_ms.items():
                    occupancy_phase_seconds[name] = (
                        occupancy_phase_seconds.get(name, 0.0) + duration_ms / 1000.0
                    )

        occupancy_started = perf_counter()
        cars = self._cars_snapshot()

        for car in cars:
            car.cruise_speed_bound = _route_cruise_speed(car, self.speed_mph)
        # Route positions stay fixed through observation and intent generation.
        # Share merge facts across those passes, then discard before batch apply.
        merge_snapshot = MergeTrafficSnapshot(cars)
        snapshot_at = perf_counter()

        priority_contenders = _observe_priority_arrivals(
            cars, self.stop_coordinator, self.elapsed_time,
            self.signal_controllers,
        )
        deadlock_candidates = []
        for car in cars:
            is_waiting = (
                car.speed <= 0.1
                and car.brain.state.value
                in ("waiting_for_priority", "entering_intersection")
            )
            if car.id != self.deadlock_resolver.winner_id and not is_waiting:
                continue
            movement = _next_controlled_movement(car, self.stop_coordinator)
            if movement is None or movement[2].control.kind is ControlType.SIGNAL:
                continue
            deadlock_candidates.append(DeadlockCandidate(
                car.id,
                ((movement[2].merge_target is not None
                  or car.id in priority_contenders)
                 and (movement[2].control.kind is not ControlType.SIGNAL
                      or self.signal_is_green(movement[2])))
                and car.brain.wait_reason != "following queued car"
                and _temporary_winner_path_clear(
                    car, movement, cars, self.occupancy,
                    self.stop_coordinator, merge_snapshot,
                ),
                movement_id=movement[2].id,
            ))
        deadlock_candidates = tuple(deadlock_candidates)
        temporary_winner = self.deadlock_resolver.choose_winner(deadlock_candidates)

        intent_phase_seconds = {
            "intent_route_lookup": 0.0,
            "intent_control_state": 0.0,
            "intent_control_claim_lookup": 0.0,
            "intent_control_inside_scan": 0.0,
            "intent_control_stop_distance": 0.0,
            "intent_merge_observation": 0.0,
            "intent_priority_query": 0.0,
            "intent_exit_gap": 0.0,
            "intent_chain_check": 0.0,
            "intent_leader_lookup": 0.0,
            "intent_speed_target": 0.0,
            "intent_brain_decision": 0.0,
            "intent_packaging": 0.0,
        }

        # Start the timed per-car pass. It collects decisions but does not
        # apply any car's movement; that happens after all intents are built.
        observed_at = perf_counter()
        frame_car_count = len(cars)
        intents: list[TrafficIntent] = []
        for car in cars:
            # Find this car's next route step and next controlled crossing or merge.
            phase_started = perf_counter()
            route_movement = _next_route_movement(car)
            movement = _next_controlled_movement(car, self.stop_coordinator)
            intent_phase_seconds["intent_route_lookup"] += perf_counter() - phase_started

            # Capture existing coordinator state and whether the car is already
            # inside one of the crossings it controls.
            phase_started = perf_counter()
            subphase_started = perf_counter()
            has_claim = movement is not None and self.stop_coordinator.has_claim(car.id, movement[2])
            intent_phase_seconds["intent_control_claim_lookup"] += perf_counter() - subphase_started

            subphase_started = perf_counter()
            inside = car.inside_claimed_movement(self.stop_coordinator)
            intent_phase_seconds["intent_control_inside_scan"] += perf_counter() - subphase_started

            # Measure the remaining distance to the stop line only when the car
            # still needs permission to enter.
            subphase_started = perf_counter()
            distance_to_stop = (
                max(0.0, movement[0] - car.length / 2 - car.distance)
                if movement is not None and not has_claim
                else None
            )
            intent_phase_seconds["intent_control_stop_distance"] += perf_counter() - subphase_started
            intent_phase_seconds["intent_control_state"] += perf_counter() - phase_started

            signal_movement = (
                movement is not None
                and movement[2].control.kind is ControlType.SIGNAL
            )
            signal_aspect = self._signal_aspect(movement[2]) if signal_movement else None
            signal_green = signal_movement and not has_claim and signal_aspect is SignalAspect.GREEN
            signal_yellow = signal_movement and signal_aspect is SignalAspect.YELLOW
            signal_red = (
                signal_movement
                and not has_claim
                and not signal_green and not signal_yellow
            )

            # Observe merge traffic and ask the shared coordinator whether this
            # car may claim the crossing or enter the merge.
            phase_started = perf_counter()
            is_merge = movement is not None and movement[2].merge_target is not None
            merge_observation = observe_merge(
                car, movement, cars, snapshot=merge_snapshot,
            ) if is_merge else None
            intent_phase_seconds["intent_merge_observation"] += perf_counter() - phase_started

            phase_started = perf_counter()
            priority = _intersection_priority(
                car, movement, distance_to_stop, self.stop_coordinator,
                signal_green=signal_green, signal_yellow=signal_yellow,
            )
            priority_reason = "waiting for intersection priority"
            intent_phase_seconds["intent_priority_query"] += perf_counter() - phase_started

            if movement is not None and not has_claim and not is_merge:
                # A clear junction is not enough if the exit is queued. Also
                # check a closely spaced next movement so the car does not enter
                # a short link it cannot clear safely.
                phase_started = perf_counter()
                exit_gap = self.occupancy.gap_from(
                    car, movement[1], TEST_CAR_LOOKAHEAD,
                )
                intent_phase_seconds["intent_exit_gap"] += perf_counter() - phase_started
                if (exit_gap is not None
                        and exit_gap < TEST_CAR_FOLLOWING_GAP + car.length / 2):
                    priority = False
                    priority_reason = "waiting for room beyond the junction"

                phase_started = perf_counter()
                chain_end = movement[1]
                for following in _route_state(car).following(movement):
                    if following[0] < movement[1]:
                        continue
                    if following[0] - chain_end >= car.length + 4.0:
                        break
                    if following[2].merge_target is not None:
                        opening = MERGE_STRATEGIES[car.brain.merge_style].decide(
                            observe_merge(car, following, cars, snapshot=merge_snapshot),
                            car.speed,
                            _route_cruise_speed(car, self.speed_mph),
                        )
                        if (not opening.can_enter
                                or not self.stop_coordinator.can_enter_merge(
                                    car.id, following[2],
                                )):
                            priority = False
                            priority_reason = (
                                "waiting before short link for the next yield"
                            )
                            break
                    chain_end = following[1]
                intent_phase_seconds["intent_chain_check"] += perf_counter() - phase_started

            # Observe the immediate leader and calculate the speed target. A car
            # already in a merge keeps the speed cap chosen at merge entry.
            phase_started = perf_counter()
            lead = self.occupancy.lead_car_gap(car, TEST_CAR_LOOKAHEAD)
            lead_car = lead[0] if lead is not None else None
            lead_distance = lead[1] if lead is not None else None
            intent_phase_seconds["intent_leader_lookup"] += perf_counter() - phase_started

            phase_started = perf_counter()
            cruise_speed = _route_cruise_speed(car, self.speed_mph)
            active_merge_ranges = (
                *_route_state(car).claimed_ranges(self.stop_coordinator.claims_for(car.id)),
                *car.signal_merge_movements,
            )
            for active in active_merge_ranges:
                if (active[2].merge_target is not None
                        and (self.stop_coordinator.has_claim(car.id, active[2])
                             or active[2].control.kind is ControlType.SIGNAL)
                        and car.distance + car.length / 2 >= active[0]
                        and car.distance - car.length / 2 < active[1]
                        and car._merge_entry_speed is not None):
                    cruise_speed = min(cruise_speed, car._merge_entry_speed)
            intent_phase_seconds["intent_speed_target"] += perf_counter() - phase_started

            # Give the brain a snapshot of traffic, controls, route position,
            # priority, and deadlock status; it returns a proposed decision.
            phase_started = perf_counter()
            decision = car.brain.decide(
                CarObservation(
                    cruise_speed=cruise_speed,
                    speed=car.speed,
                    distance_to_stop=distance_to_stop,
                    must_stop=(
                        movement is not None and not has_claim
                        and movement[2].control.kind is ControlType.STOP
                    ),
                    must_yield=(
                        movement is not None and not has_claim
                        and movement[2].control.kind not in (
                            ControlType.STOP, ControlType.SIGNAL,
                        )
                    ),
                    signal_red=signal_red,
                    signal_movement_id=movement[2].id if movement else "",
                    signal_green=signal_green, signal_yellow=signal_yellow,
                    priority_reason=priority_reason,
                    merge=merge_observation,
                    has_priority=priority,
                    lead_car_distance=lead_distance,
                    following_gap=car.brain.following_distance(car.speed),
                    inside_intersection=inside,
                    next_maneuver=_signaled_maneuver(car, route_movement),
                    distance_to_maneuver=(
                        max(0.0, route_movement[0] - car.distance)
                        if route_movement is not None else None
                    ),
                    inside_maneuver=(
                        route_movement is not None
                        and route_movement[0] <= car.distance < route_movement[1]
                    ),
                    temporary_winner=car.id == temporary_winner,
                    temporary_winner_blocked=(
                        car.id == self.deadlock_resolver.winner_id
                        and temporary_winner is None
                    ),
                ),
                elapsed_seconds,
            )
            intent_phase_seconds["intent_brain_decision"] += perf_counter() - phase_started

            # Keep the car's starting state and proposed decision together.
            # Conflict resolution consumes this complete set after every car
            # has produced an intent.
            phase_started = perf_counter()
            intents.append(TrafficIntent(
                car=car,
                distance_before=car.distance,
                speed_before=car.speed,
                route_movement=route_movement,
                movement=movement,
                has_claim=has_claim,
                is_merge=is_merge,
                merge_observation=merge_observation,
                priority=priority,
                distance_to_stop=distance_to_stop,
                lead_car=lead_car,
                lead_distance=lead_distance,
                decision=decision,
                signal_entry=decision.signal_entry_allowed,
            ))
            intent_phase_seconds["intent_packaging"] += perf_counter() - phase_started
        # End of intent_generation; coordinator arbitration starts below.
        intents_at = perf_counter()
        intent_phase_timings_ms = {
            name: seconds * 1000.0
            for name, seconds in intent_phase_seconds.items()
        }

        # Resolve every request against the same collected intent set. Stable
        # priority order makes arbitration independent of the mutable car list.
        for intent in intents:
            if (intent.decision.register_stop and intent.movement is not None
                    and intent.car.id in priority_contenders):
                self.stop_coordinator.observe_stop(
                    intent.car.id, intent.movement[2], self.elapsed_time,
                )

        def claim_order(intent: TrafficIntent) -> tuple[object, ...]:
            if intent.car.id == temporary_winner:
                return (0, 0.0, 0.0, intent.car.id)
            priority_key = self.stop_coordinator.priority_key(intent.car.id)
            if priority_key is not None:
                return (1, *priority_key)
            return (2, 0.0, 0.0, intent.car.id)

        by_id = {intent.car.id: intent for intent in intents}
        claim_revisions_before = {
            intent.movement[2].intersection_id:
            self.stop_coordinator.claim_revision_for(
                intent.movement[2].intersection_id,
            )
            for intent in intents
            if intent.signal_entry and intent.movement is not None
        }
        for intent in sorted(intents, key=claim_order):
            movement = intent.movement
            decision = intent.decision
            has_claim = intent.has_claim
            if (decision.request_claim and movement is not None
                    and (intent.is_merge or intent.car.id in priority_contenders)
                    and (intent.distance_to_stop or 0.0)
                    <= _entry_claim_distance(intent.speed_before)):
                if intent.car.id == temporary_winner:
                    has_claim = self.stop_coordinator.claim_temporary_winner(
                        intent.car.id, movement[2],
                    )
                elif intent.is_merge:
                    has_claim = self.stop_coordinator.claim_merge(
                        intent.car.id, movement[2],
                    )
                else:
                    has_claim = self.stop_coordinator.claim(
                        intent.car.id, movement[2],
                    )
                if has_claim:
                    intent.car._claimed_movement = movement[2]
                    if intent.is_merge:
                        intent.car._merge_entry_speed = decision.merge_entry_speed
                        decision = replace(
                            decision,
                            desired_speed=decision.merge_entry_speed,
                        )
            by_id[intent.car.id] = replace(
                intent, has_claim=has_claim, decision=decision,
            )
        resolved = []
        for original in intents:
            intent = by_id[original.car.id]
            decision = intent.decision
            if (intent.signal_entry and intent.movement is not None
                    and intent.distance_to_stop is not None
                    and intent.distance_to_stop <= _entry_claim_distance(
                        intent.speed_before,
                    )
                    and self.stop_coordinator.claim_revision_for(
                        intent.movement[2].intersection_id,
                    ) != claim_revisions_before.get(
                        intent.movement[2].intersection_id, 0,
                    )
                    and not self.stop_coordinator.can_enter_signal(
                        intent.car.id, intent.movement[2],
                    )):
                decision = replace(
                    decision, signal_entry_allowed=False,
                    desired_speed=min(decision.desired_speed, sqrt(
                        2 * COMFORTABLE_BRAKING * max(0.0, intent.distance_to_stop or 0.0))),
                    state=BehaviorState.WAITING_FOR_PRIORITY,
                    wait_reason="waiting for conflicting traffic",
                )
                intent.car.brain.state = decision.state
                intent.car.brain.wait_reason = decision.wait_reason
                intent.car.brain.desired_speed = decision.desired_speed
                intent = replace(intent, signal_entry=False, priority=False, decision=decision)
            if intent.signal_entry and intent.is_merge:
                intent.car._merge_entry_speed = decision.merge_entry_speed
                intent = replace(intent, decision=replace(decision, desired_speed=decision.merge_entry_speed))
            resolved.append(intent)
        resolved_at = perf_counter()

        next_speeds: dict[str, float] = {}
        planned_travel: dict[str, float] = {}
        for intent in resolved:
            car = intent.car
            decision = intent.decision
            speed_delta = decision.desired_speed - car.speed
            limit = (
                TEST_CAR_ACCELERATION if speed_delta > 0 else TEST_CAR_BRAKING
            ) * elapsed_seconds
            next_speed = car.speed + max(-limit, min(limit, speed_delta))
            travel = next_speed * elapsed_seconds
            if intent.movement is not None and not (intent.has_claim or intent.signal_entry):
                stop_distance = intent.movement[0] - car.length / 2
                travel = min(
                    travel,
                    max(0.0, stop_distance - intent.distance_before),
                )
            next_speeds[car.id] = next_speed
            planned_travel[car.id] = travel

        # A follower may use space its leader creates in this same accepted
        # batch. Relaxing the dependency chain preserves four feet of final
        # clearance without reintroducing car-list update order.
        for _ in range(len(resolved)):
            changed = False
            for intent in resolved:
                if intent.lead_car is None or intent.lead_distance is None:
                    continue
                leader_travel = planned_travel.get(intent.lead_car.id, 0.0)
                safe_travel = max(0.0, intent.lead_distance + leader_travel - 4.0)
                if planned_travel[intent.car.id] > safe_travel:
                    planned_travel[intent.car.id] = safe_travel
                    changed = True
            if not changed:
                break

        completed: list[RoutedRoadVehicle] = []
        temporary_winner_entered = False
        for intent in resolved:
            car = intent.car
            travel = planned_travel[car.id]
            car.speed = next_speeds[car.id] if travel > 0.0 else 0.0
            alive = car.advance(travel / car.speed if car.speed > 0 else 0.0)
            if (car.id == temporary_winner and intent.has_claim
                    and intent.movement is not None
                    and car.distance + car.length / 2 >= intent.movement[0]):
                temporary_winner_entered = True
            if not alive:
                completed.append(car)
        applied_at = perf_counter()

        # Claims and occupancy change only after the full position batch lands.
        for intent in resolved:
            car = intent.car
            for _, end, connection in car.active_claimed_movements(self.stop_coordinator):
                if car.distance - car.length / 2 >= end:
                    self.stop_coordinator.release(car.id, connection)
            remaining_claims = self.stop_coordinator.claims_for(car.id)
            car._claimed_movement = remaining_claims[-1] if remaining_claims else None
            self._observe_signal_car(car)
            self._mark_occupancy_changed(car)
        if completed:
            with self._roster_revision.mutate():
                for car in completed:
                    self.stop_coordinator.forget_car(car.id)
                    self._cars.remove(car)
        publish_occupancy(removed=completed)
        occupancy_at = perf_counter()

        stopped_count = sum(car.speed <= 0.1 for car in self.cars)
        traffic_is_flowing = bool(self.cars) and stopped_count < 0.8 * len(self.cars)
        self.deadlock_resolver.observe_frame(
            elapsed_seconds,
            made_progress=traffic_is_flowing or bool(completed) or (not deadlock_candidates and bool(self._signal_states)),
            candidate_ids=tuple(candidate.car_id for candidate in deadlock_candidates),
            winner_resolved=(
                temporary_winner_entered
                or any(car.id == self.deadlock_resolver.winner_id for car in completed)
            ),
        )
        finished_at = perf_counter()
        profiler_timings = {
            "spawn": (spawned_at - frame_started) * 1000,
            "snapshot": (snapshot_at - occupancy_started) * 1000,
            "observe": (observed_at - snapshot_at) * 1000,
            "intent_generation": (intents_at - observed_at) * 1000,
            **intent_phase_timings_ms,
            "conflict_resolution": (resolved_at - intents_at) * 1000,
            "movement_apply": (applied_at - resolved_at) * 1000,
            "occupancy_rebuild": (occupancy_at - applied_at) * 1000,
            **{
                name: duration * 1000
                for name, duration in occupancy_phase_seconds.items()
            },
            "post_update": (finished_at - occupancy_at) * 1000,
            "total": (finished_at - frame_started) * 1000,
        }
        self.profiler.record_tick(
            system="routed_traffic",
            simulated_time=self.elapsed_time,
            elapsed_seconds=elapsed_seconds,
            entity_counts={"cars": frame_car_count},
            timings_ms=profiler_timings,
        )
        if self.debugger is not None:
            for intent in resolved:
                self.debugger.record_car(
                    intent.car,
                    distance_before=intent.distance_before,
                    speed_before=intent.speed_before,
                    decision=intent.decision,
                    movement=intent.movement,
                    has_priority=intent.priority,
                    has_claim=(
                        intent.movement is not None
                        and self.stop_coordinator.has_claim(
                            intent.car.id, intent.movement[2],
                        )
                    ),
                    merge_observation=intent.merge_observation,
                )
            self.debugger.end_frame(
                simulated_time=self.elapsed_time,
                elapsed_seconds=elapsed_seconds,
                car_count=frame_car_count,
                completed_ids=[car.id for car in completed],
                timings_ms={
                    "spawn": (spawned_at - frame_started) * 1000,
                    "snapshot": (snapshot_at - occupancy_started) * 1000,
                    "observe": (observed_at - snapshot_at) * 1000,
                    "intent": (intents_at - observed_at) * 1000,
                    "resolve": (resolved_at - intents_at) * 1000,
                    "apply": (applied_at - resolved_at) * 1000,
                    "occupancy": (occupancy_at - applied_at) * 1000,
                    "total": (finished_at - frame_started) * 1000,
                },
                deadlock_stall_seconds=self.deadlock_resolver.stall_seconds,
                temporary_winner_id=(
                    temporary_winner or self.deadlock_resolver.winner_id
                ),
                hard_gridlock=self.deadlock_resolver.hard_gridlock,
            )
        return completed

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


def as_reference(simulation, mode="data_first"):
    """Detach a scenario's initial state into the frozen Python test oracle."""
    simulation._discard_native()
    simulation.occupancy._refresh = None
    simulation.stop_coordinator._on_native_edit = None
    simulation.deadlock_resolver._on_native_edit = None
    simulation.__class__ = RoadVehicleSimulation
    simulation.update_mode = mode
    simulation.occupancy.rebuild(simulation.cars)
    simulation._occupancy_changes.clear()
    for car in simulation.cars:
        car._on_occupancy_change = simulation._mark_occupancy_changed
        car._on_native_edit = None
        car.brain._on_native_edit = None
    return simulation
