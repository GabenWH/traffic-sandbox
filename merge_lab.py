"""Repeatable torture tests for merge and junction decisions.

The lab starts every scenario from a known map, seed, and set of car intents.
That makes a result comparable after a CarBrain or conflict-rule change.  It is
also intentionally data-first at the boundary: a report is frames of intent,
priority facts, and resulting motion—not a screenshot of a particular object.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from math import ceil, hypot
from pathlib import Path
import random
from statistics import mean, median
from time import perf_counter
from typing import Callable

from city import CityMap, Terrain
from models import IntersectionKind
from persistence import world_from_dict
from traffic_debugger import FrameTrace, TrafficDebugger
from traffic_testbed import RoutedTestCar, TestTrafficSimulation


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class MergeLabScenario:
    """A named initial traffic state, not a random UI interaction."""

    name: str
    description: str
    conditions: tuple[str, ...]
    build: Callable[[int], tuple[CityMap, TestTrafficSimulation]]


@dataclass(frozen=True)
class MergeLabReport:
    scenario: str
    seed: int
    engine: str
    seconds: float
    completed: int
    remaining: int
    overlap_pair_ticks: int
    first_overlap: dict[str, object] | None
    timing_summary_ms: dict[str, float]
    tick_times_ms: tuple[float, ...]
    hard_gridlock_seconds: float
    state_digest: str
    peak_active: int
    windows: tuple["TrafficWindow", ...]
    frames: tuple[FrameTrace, ...]


@dataclass(frozen=True)
class TrafficWindow:
    """One fixed slice of a sustained run for spotting flow degradation."""

    started_at: float
    ended_at: float
    tick_count: int
    completed: int
    mean_active: float
    peak_active: int
    overlap_pair_ticks: int
    hard_gridlock_seconds: float
    temporary_winner_ticks: int
    median_tick_ms: float
    p95_tick_ms: float
    p99_tick_ms: float


def _roundabout_city() -> CityMap:
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0, 300), (600, 300)], name="East-west through road")
    city.add_road([(300, 0), (300, 600)], name="North-south side road")
    city.standard_intersections[0].kind = IntersectionKind.ROUNDABOUT
    city.rebuild_mobility_network()
    return city


def _endpoints(city: CityMap) -> dict[tuple[float, float], object]:
    return {junction.position: junction for junction in city.cul_de_sacs}


def _traffic(
    seed: int,
    *,
    interval: float = 1000.0,
    max_cars: int = 60,
) -> TestTrafficSimulation:
    return TestTrafficSimulation(
        spawn_interval=interval,
        max_cars=max_cars,
        rng=random.Random(seed),
        # A lab run keeps its full trace; the interactive UI intentionally
        # keeps only a short rolling history.
        debugger=TrafficDebugger(max_frames=10_000),
    )


def _spawn(
    traffic: TestTrafficSimulation, city: CityMap, source: tuple[float, float],
    destination: tuple[float, float],
) -> RoutedTestCar:
    car = traffic.spawn_car(city, _endpoints(city)[source], _endpoints(city)[destination])
    if car is None:  # A broken route should fail loudly in a laboratory setup.
        raise RuntimeError(f"Lab route missing: {source} -> {destination}")
    return car


def _before_entry(car: RoutedTestCar, feet: float = 20.0) -> None:
    entry = car.controlled_movements[0]
    car.distance = max(0.0, entry[0] - car.length / 2 - feet)
    car.advance(0)


def _on_joining_lane(car: RoutedTestCar, joining: RoutedTestCar, feet_before: float) -> None:
    target = joining.controlled_movements[0][2].merge_target
    shared = next(segment for segment in car.route_segments if segment[2] == target)
    car.distance = max(0.0, shared[0] - feet_before)
    car.advance(0)


def _clear_entry(seed: int) -> tuple[CityMap, TestTrafficSimulation]:
    city, traffic = _roundabout_city(), _traffic(seed)
    _before_entry(_spawn(traffic, city, (0, 300), (600, 300)), 35)
    return city, traffic


def _circulating_leader(seed: int) -> tuple[CityMap, TestTrafficSimulation]:
    city, traffic = _roundabout_city(), _traffic(seed)
    leader = _spawn(traffic, city, (300, 0), (300, 600))
    joining = _spawn(traffic, city, (0, 300), (600, 300))
    _on_joining_lane(leader, joining, 12)
    _before_entry(joining, 28)
    return city, traffic


def _simultaneous_entry(seed: int) -> tuple[CityMap, TestTrafficSimulation]:
    city, traffic = _roundabout_city(), _traffic(seed)
    _before_entry(_spawn(traffic, city, (0, 300), (600, 300)), 8)
    _before_entry(_spawn(traffic, city, (300, 0), (300, 600)), 8)
    return city, traffic


def _queued_ring(seed: int) -> tuple[CityMap, TestTrafficSimulation]:
    city, traffic = _roundabout_city(), _traffic(seed)
    joining = _spawn(traffic, city, (0, 300), (600, 300))
    leader = _spawn(traffic, city, (300, 0), (300, 600))
    # This east-to-south route reaches the same first ring arc as the joining
    # car, giving us a genuine close queue rather than merely nearby traffic.
    tail = _spawn(traffic, city, (600, 300), (300, 600))
    _before_entry(joining, 8)
    _on_joining_lane(leader, joining, 4)
    _on_joining_lane(tail, joining, 30)
    leader.speed = 1.0
    tail.speed = 3.0
    return city, traffic


def _continuous_pressure(seed: int) -> tuple[CityMap, TestTrafficSimulation]:
    city, traffic = _roundabout_city(), _traffic(seed, interval=0.45)
    for junction in city.cul_de_sacs:
        traffic.toggle_junction(junction)
    return city, traffic


def _slip_lane_short_link(seed: int) -> tuple[CityMap, TestTrafficSimulation]:
    raw = (ROOT / "tests/fixtures/slip_lanes.json").read_text()
    city = world_from_dict(json.loads(raw)).city_map
    traffic = _traffic(seed, interval=0.7)
    for junction in city.cul_de_sacs:
        traffic.toggle_junction(junction)
    return city, traffic


def _dense_network_gauntlet(seed: int) -> tuple[CityMap, TestTrafficSimulation]:
    """Large mixed network with ordinary, stopped, one-way, and merge traffic."""
    city = CityMap(width=2200, height=1700, terrain=Terrain(trees=[]))
    for y in (200, 600, 1000, 1400):
        city.add_road([(100, y), (1900, y)], name=f"Avenue {y}")
    for x in (300, 700, 1100, 1500):
        city.add_road([(x, 50), (x, 1550)], name=f"Street {x}")

    # A one-way cross-town route creates asymmetric demand. The two curved
    # bypasses join close to larger junctions, producing the short-link and
    # merge interactions that are most likely to propagate queues upstream.
    city.add_road(
        [(100, 800), (1900, 800)],
        name="One-way cross-town",
        forward_lane_count=1,
        reverse_lane_count=0,
    )
    city.add_road(
        [(540, 600), (600, 540), (700, 460)],
        name="Northbound slip",
        forward_lane_count=1,
        reverse_lane_count=0,
    )
    city.add_road(
        [(1500, 1140), (1560, 1080), (1660, 1000)],
        name="Eastbound slip",
        forward_lane_count=1,
        reverse_lane_count=0,
    )

    def nearest(position):
        return min(
            city.standard_intersections,
            key=lambda junction: (
                (junction.position[0] - position[0]) ** 2
                + (junction.position[1] - position[1]) ** 2
            ),
        )

    for position in ((700, 600), (1500, 1000), (1100, 800)):
        nearest(position).kind = IntersectionKind.ROUNDABOUT
    city.rebuild_mobility_network()
    for position in ((300, 200), (1100, 1400), (1500, 600)):
        nearest(position).set_all_way_stop(True)

    traffic = _traffic(seed, interval=0.12, max_cars=240)
    for junction in city.cul_de_sacs:
        traffic.toggle_junction(junction)
    # Avoid an artificial once-per-interval spike where all sixteen boundary
    # sources run pathfinding and spawn checks on the exact same frame.
    for index, junction in enumerate(city.cul_de_sacs):
        traffic._spawn_elapsed[junction.id] = (
            index * traffic.spawn_interval / len(city.cul_de_sacs)
        )
    return city, traffic


def scenario_catalog() -> tuple[MergeLabScenario, ...]:
    """Return the current stress matrix. Add cases here before changing AI."""
    return (
        MergeLabScenario("roundabout-clear-entry", "One rolling entry into an empty ring.",
                         ("roundabout", "clear-gap", "rolling"), _clear_entry),
        MergeLabScenario("roundabout-circulating-leader", "Entry paced against real ring traffic.",
                         ("roundabout", "front-gap", "rolling"), _circulating_leader),
        MergeLabScenario("roundabout-simultaneous-entry", "Two approaches request the ring together.",
                         ("roundabout", "competing-claims", "priority"), _simultaneous_entry),
        MergeLabScenario("roundabout-queued-ring", "Slow, close ring traffic tests rear and front gaps.",
                         ("roundabout", "queued", "front-gap", "rear-gap"), _queued_ring),
        MergeLabScenario("roundabout-continuous-pressure", "All four approaches keep producing traffic.",
                         ("roundabout", "mixed-brains", "sustained-load"), _continuous_pressure),
        MergeLabScenario("slip-lane-short-link", "A close junction followed by a roundabout yield.",
                         ("short-link", "chain-signals", "sustained-load"), _slip_lane_short_link),
        MergeLabScenario(
            "dense-network-gauntlet",
            "A large mixed grid driven to saturation through stops, circles, and slip lanes.",
            ("large-network", "roundabout", "all-way-stop", "one-way",
             "short-link", "sustained-load"),
            _dense_network_gauntlet,
        ),
    )


class MergeLab:
    """Run a named scenario and turn its trace into comparable measurements."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def run(
        self,
        scenario_name: str,
        *,
        seconds: float = 30.0,
        dt: float = 0.05,
        engine: str = "legacy",
        trace: bool = True,
        window_seconds: float = 60.0,
    ) -> MergeLabReport:
        if seconds <= 0 or not 0 < dt <= 0.05:
            raise ValueError("Use positive seconds and 0 < dt <= 0.05")
        if engine not in ("legacy", "data_first"):
            raise ValueError("Traffic engine must be legacy or data_first")
        if window_seconds <= 0:
            raise ValueError("Traffic window duration must be positive")
        scenarios = {scenario.name: scenario for scenario in scenario_catalog()}
        if scenario_name not in scenarios:
            raise ValueError("Unknown scenario. Available scenarios: " + ", ".join(scenarios))
        city, traffic = scenarios[scenario_name].build(self.seed)
        traffic.update_mode = engine
        if not trace:
            traffic.debugger = None
        completed = overlaps = 0
        hard_gridlock_seconds = 0.0
        first_overlap: dict[str, object] | None = None
        tick_times_ms: list[float] = []
        window_count = ceil(seconds / window_seconds)
        window_samples = [{
            "completed": 0,
            "active": [],
            "overlaps": 0,
            "hard_gridlock_seconds": 0.0,
            "temporary_winner_ticks": 0,
            "tick_times_ms": [],
        } for _ in range(window_count)]
        digest = hashlib.sha256()
        ordinals: dict[str, int] = {}
        next_ordinal = 1
        for tick in range(round(seconds / dt)):
            for car in traffic.cars:
                if car.id not in ordinals:
                    ordinals[car.id] = next_ordinal
                    next_ordinal += 1
            started = perf_counter()
            finished = traffic.update(city, dt)
            tick_times_ms.append((perf_counter() - started) * 1000)
            window_index = min(
                int((tick * dt) / window_seconds),
                window_count - 1,
            )
            window = window_samples[window_index]
            window["tick_times_ms"].append(tick_times_ms[-1])
            for car in (*traffic.cars, *finished):
                if car.id not in ordinals:
                    ordinals[car.id] = next_ordinal
                    next_ordinal += 1
            completed += len(finished)
            window["completed"] += len(finished)
            window["active"].append(len(traffic.cars))
            if traffic.deadlock_resolver.hard_gridlock:
                hard_gridlock_seconds += dt
                window["hard_gridlock_seconds"] += dt
            if traffic.deadlock_resolver.winner_id is not None:
                window["temporary_winner_ticks"] += 1
            tick_overlaps = 0
            for car, other in _overlapping_pairs(traffic.cars):
                overlaps += 1
                tick_overlaps += 1
                if first_overlap is None:
                    first_overlap = {
                        "time": round(traffic.elapsed_time, 3),
                        "cars": (car.id, other.id),
                        "positions": (car.position, other.position),
                    }
            window["overlaps"] += tick_overlaps
            junction_positions = {
                junction.id: junction.position for junction in city.intersections
            }

            def movement_state(connection):
                if connection is None:
                    return None
                return (
                    connection.roundabout_role,
                    connection.control.kind.value,
                    tuple(connection.path),
                )

            state = {
                "tick": tick,
                "completed": sorted(ordinals[car.id] for car in finished),
                "cars": sorted((
                    ordinals[car.id],
                    tuple(car.points),
                    round(car.distance, 6),
                    round(car.speed, 6),
                    car.brain.state.value,
                    car.brain.wait_reason,
                    round(car.brain.stopped_elapsed, 6),
                    car.brain.signal_intent.value,
                    movement_state(car._claimed_movement),
                    car.brain.merge_style,
                ) for car in traffic.cars),
                "arrivals": sorted((
                    car_id,
                    round(arrival.stopped_at, 6),
                    movement_state(arrival.connection),
                ) for car_id, arrival in traffic.stop_coordinator.arrivals.items()),
                "claims": sorted((
                    owner,
                    movement_state(connection),
                ) for (owner, _), connection in traffic.stop_coordinator.claims.items()),
                "deadlock": (
                    round(traffic.deadlock_resolver.stall_seconds, 6),
                    traffic.deadlock_resolver.winner_id,
                    traffic.deadlock_resolver.hard_gridlock,
                ),
                "spawn_timers": sorted((
                    junction_positions[junction_id], round(value, 6),
                ) for junction_id, value in traffic._spawn_elapsed.items()),
                "rng": repr(traffic.rng.getstate()),
            }
            digest.update(json.dumps(state, sort_keys=True).encode())
        frames = tuple(traffic.debugger.frames) if traffic.debugger is not None else ()
        windows = tuple(
            TrafficWindow(
                started_at=round(index * window_seconds, 6),
                ended_at=round(min(seconds, (index + 1) * window_seconds), 6),
                tick_count=len(sample["tick_times_ms"]),
                completed=int(sample["completed"]),
                mean_active=round(mean(sample["active"]), 3) if sample["active"] else 0.0,
                peak_active=max(sample["active"], default=0),
                overlap_pair_ticks=int(sample["overlaps"]),
                hard_gridlock_seconds=round(float(sample["hard_gridlock_seconds"]), 6),
                temporary_winner_ticks=int(sample["temporary_winner_ticks"]),
                median_tick_ms=round(median(sample["tick_times_ms"]), 4)
                if sample["tick_times_ms"] else 0.0,
                p95_tick_ms=round(_percentile(sample["tick_times_ms"], 0.95), 4),
                p99_tick_ms=round(_percentile(sample["tick_times_ms"], 0.99), 4),
            )
            for index, sample in enumerate(window_samples)
        )
        return MergeLabReport(
            scenario=scenario_name, seed=self.seed, engine=engine, seconds=seconds,
            completed=completed, remaining=len(traffic.cars),
            overlap_pair_ticks=overlaps, first_overlap=first_overlap,
            timing_summary_ms=_timing_summary(frames),
            tick_times_ms=tuple(tick_times_ms),
            hard_gridlock_seconds=round(hard_gridlock_seconds, 6),
            state_digest=digest.hexdigest(),
            peak_active=max((window.peak_active for window in windows), default=0),
            windows=windows,
            frames=frames,
        )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _timing_summary(frames: tuple[FrameTrace, ...]) -> dict[str, float]:
    if not frames:
        return {}
    names = {name for frame in frames for name in frame.timings_ms}
    return {
        name: round(sum(frame.timings_ms.get(name, 0.0) for frame in frames) / len(frames), 4)
        for name in sorted(names)
    }


def _cars_overlap(a: RoutedTestCar, b: RoutedTestCar) -> bool:
    """Separating-axis rectangle check; nearby lanes alone are not a collision."""
    for heading in (a.heading, b.heading):
        for axis in (heading, (-heading[1], heading[0])):
            separation = abs(sum((b.position[k] - a.position[k]) * axis[k] for k in (0, 1)))
            def radius(car: RoutedTestCar) -> float:
                along = abs(sum(car.heading[k] * axis[k] for k in (0, 1)))
                across = abs(-car.heading[1] * axis[0] + car.heading[0] * axis[1])
                return along * car.length / 2 + across * car.width / 2
            if separation >= radius(a) + radius(b) - 0.01:
                return False
    return True


def _overlapping_pairs(
    cars: list[RoutedTestCar],
) -> list[tuple[RoutedTestCar, RoutedTestCar]]:
    """Broad-phase the exact rectangle audit through neighboring grid cells."""
    if not cars:
        return []
    cell_size = max(
        32.0,
        max(hypot(car.length, car.width) for car in cars),
    )
    bins: defaultdict[tuple[int, int], list[RoutedTestCar]] = defaultdict(list)
    overlaps = []
    for car in cars:
        cell = (
            int(car.position[0] // cell_size),
            int(car.position[1] // cell_size),
        )
        for x in range(cell[0] - 1, cell[0] + 2):
            for y in range(cell[1] - 1, cell[1] + 2):
                for other in bins[(x, y)]:
                    if _cars_overlap(other, car):
                        overlaps.append((other, car))
        bins[cell].append(car)
    return overlaps
