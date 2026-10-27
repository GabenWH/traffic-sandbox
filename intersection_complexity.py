"""Paired, reproducible performance runs for a single four-leg junction.

The runner changes only the intersection policy/geometry. Every mode receives
the same seeded external arrival schedule for each seed and demand level.
Timing samples cover request admission and one data-first simulation update;
queue and safety-proxy calculations happen outside the timed region.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import permutations
from math import ceil, hypot, log, sqrt
import random
from statistics import median
from time import perf_counter
from typing import Callable, Iterable

from city import CityMap, Terrain
from intersection_controls import movements_conflict
from models import IntersectionKind
from traffic_testbed import TestTrafficSimulation, _controlled_movement_ranges
from units import mph_to_pixels_per_second
from vehicle import vehicle_footprints_overlap


APPROACHES = (
    (300.0, 0.0),   # north
    (600.0, 300.0), # east
    (300.0, 600.0), # south
    (0.0, 300.0),   # west
)
MODES = ("unsignalized", "four_way_stop", "roundabout")
DEMAND_LEVELS = {"low": 2.4, "medium": 1.6, "high": 1.2}
DEFAULT_SEEDS = tuple(range(30))


@dataclass(frozen=True)
class DemandEvent:
    """One external vehicle request, indexed on the simulation time grid."""

    tick: int
    source_index: int
    destination_index: int


def build_intersection_city(mode: str) -> CityMap:
    """Build one identical four-leg cross with the requested junction policy."""
    if mode not in MODES:
        raise ValueError(f"Unknown intersection mode: {mode}")
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0, 300), (600, 300)], name="East-west road")
    city.add_road([(300, 0), (300, 600)], name="North-south road")
    junction = city.standard_intersections[0]
    if mode == "four_way_stop":
        junction.set_all_way_stop(True)
    elif mode == "roundabout":
        junction.kind = IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network()
    return city


def make_demand_schedule(
    *, seed: int, seconds: float, interval: float, dt: float = 0.05,
) -> tuple[DemandEvent, ...]:
    """Make matched directional demand with 55% through, 25% right, 20% left.

    Each of the four approaches has the same arrival headway. Their first
    arrivals are phase-shifted across one headway to avoid a synthetic burst
    in which all four cars arrive on the same update.
    """
    if seconds <= 0 or interval <= 0 or dt <= 0:
        raise ValueError("Seconds, interval, and dt must be positive")
    tick_count = round(seconds / dt)
    interval_ticks = round(interval / dt)
    if interval_ticks < 1 or abs(tick_count * dt - seconds) > 1e-8:
        raise ValueError("seconds and interval must align to the simulation dt")
    if abs(interval_ticks * dt - interval) > 1e-8:
        raise ValueError("interval must align to the simulation dt")

    rng = random.Random(seed)
    events: list[DemandEvent] = []
    for source in range(4):
        tick = source * interval_ticks // 4
        while tick < tick_count:
            choice = rng.random()
            # Approach order is north, east, south, west.
            destination = (
                (source + 2) % 4 if choice < 0.55 else
                (source + 1) % 4 if choice < 0.80 else
                (source - 1) % 4
            )
            events.append(DemandEvent(tick, source, destination))
            tick += interval_ticks
    return tuple(sorted(events, key=lambda event: (event.tick, event.source_index)))


def movement_conflict_catalog(city: CityMap):
    """Return every movement used by benchmark routes and its conflict graph.

    Roundabout entry/exit connectors are generated in the vehicle mobility
    layer, rather than stored in ``Intersection.lane_connections``. Enumerate
    all twelve directed approach-to-approach routes so those connectors are
    included alongside standard-intersection movements.
    """
    endpoints = {junction.position: junction for junction in city.cul_de_sacs}
    movements = {}
    for source_index, destination_index in permutations(range(len(APPROACHES)), 2):
        route = city.find_vehicle_route_between(
            endpoints[APPROACHES[source_index]],
            endpoints[APPROACHES[destination_index]],
        )
        if route is None:
            raise RuntimeError(
                f"Benchmark route missing: {APPROACHES[source_index]} -> "
                f"{APPROACHES[destination_index]}"
            )
        for _, _, connection in _controlled_movement_ranges(route):
            movements[connection.id] = connection
    conflicts = {
        connection_id: frozenset(
            other_id for other_id, other in movements.items()
            if other_id != connection_id and movements_conflict(connection, other)
        )
        for connection_id, connection in movements.items()
    }
    return movements, conflicts


def run_intersection_mode(
    mode: str,
    *,
    seed: int,
    seconds: float,
    interval: float,
    dt: float = 0.05,
    max_cars: int = 80,
    demand_schedule: tuple[DemandEvent, ...] | None = None,
) -> dict[str, object]:
    """Run one mode and return traffic metrics plus internal scaling samples."""
    city = build_intersection_city(mode)
    if demand_schedule is None:
        demand_schedule = make_demand_schedule(
            seed=seed, seconds=seconds, interval=interval, dt=dt,
        )
    tick_count = round(seconds / dt)
    if abs(tick_count * dt - seconds) > 1e-8:
        raise ValueError("seconds must align to the simulation dt")
    if max_cars < 1:
        raise ValueError("max_cars must be positive")

    endpoints = {junction.position: junction for junction in city.cul_de_sacs}
    try:
        ordered_endpoints = tuple(endpoints[position] for position in APPROACHES)
    except KeyError as error:
        raise RuntimeError("The four-approach benchmark route is incomplete") from error

    traffic = TestTrafficSimulation(
        spawn_interval=10_000.0,
        max_cars=max_cars,
        rng=random.Random(seed),
        update_mode="cpp",
    )
    events_by_tick: dict[int, list[DemandEvent]] = defaultdict(list)
    for event in demand_schedule:
        if event.tick < tick_count:
            events_by_tick[event.tick].append(event)

    attempted = admitted = capped = blocked_at_source = 0
    completed = 0
    trip_starts: dict[str, tuple[float, float]] = {}
    trip_times: list[float] = []
    trip_delays: list[float] = []
    hard_gridlock_seconds = 0.0
    temporary_winner_ticks = 0
    maximum_queue = maximum_approach_queue = 0
    overlap_pair_ticks = 0
    sub_1_5s_ttc_pair_ticks = 0
    minimum_ttc_proxy: float | None = None
    active_tick_ms: dict[int, list[float]] = defaultdict(list)
    tick_times: list[float] = []
    movement_passages: dict[tuple[str, str], dict[str, object]] = {}
    connections, crossing_movements = movement_conflict_catalog(city)

    for tick in range(tick_count):
        started = perf_counter()
        for event in events_by_tick.get(tick, ()):
            attempted += 1
            if sum(car.source_type == "test_traffic" for car in traffic.cars) >= max_cars:
                capped += 1
                continue
            car = traffic.spawn_car(
                city,
                ordered_endpoints[event.source_index],
                ordered_endpoints[event.destination_index],
            )
            if car is None:
                blocked_at_source += 1
                continue
            admitted += 1
            free_flow_seconds = car.total_length / max(car.speed, 1e-9)
            trip_starts[car.id] = (tick * dt, free_flow_seconds)

        active_count = len(traffic.cars)
        finished_cars = traffic.update(city, dt)
        tick_ms = (perf_counter() - started) * 1000.0
        tick_times.append(tick_ms)
        active_tick_ms[active_count].append(tick_ms)
        now = (tick + 1) * dt

        if traffic.deadlock_resolver.hard_gridlock:
            hard_gridlock_seconds += dt
        if traffic.deadlock_resolver.winner_id is not None:
            temporary_winner_ticks += 1

        for car in (*traffic.cars, *finished_cars):
            for start, end, connection in car.controlled_movements:
                key = (car.id, connection.id)
                passage = movement_passages.get(key)
                if passage is None and car.distance + car.length / 2 >= start:
                    passage = {"vehicle_id": car.id, "connection_id": connection.id,
                               "entered_at": now, "cleared_at": None}
                    movement_passages[key] = passage
                if (passage is not None and passage["cleared_at"] is None
                        and car.distance - car.length / 2 >= end):
                    passage["cleared_at"] = now

        for car in finished_cars:
            completed += 1
            started_at, free_flow_seconds = trip_starts.pop(car.id)
            travel_seconds = now - started_at
            trip_times.append(travel_seconds)
            trip_delays.append(max(0.0, travel_seconds - free_flow_seconds))

        queue_by_approach = _queued_cars_by_approach(traffic.cars)
        maximum_queue = max(maximum_queue, sum(queue_by_approach.values()))
        maximum_approach_queue = max(
            maximum_approach_queue, max(queue_by_approach.values(), default=0),
        )
        overlap_pair_ticks += _overlap_pair_count(traffic.cars)
        tick_ttc_count, tick_min_ttc = _conflicting_ttc_proxies(
            traffic.cars, crossing_movements,
        )
        sub_1_5s_ttc_pair_ticks += tick_ttc_count
        if tick_min_ttc is not None:
            minimum_ttc_proxy = (
                tick_min_ttc if minimum_ttc_proxy is None
                else min(minimum_ttc_proxy, tick_min_ttc)
            )

    pet_below_1_5, pet_overlap_pairs, pet_min_gap = _pet_proxy_metrics(
        movement_passages.values(), crossing_movements,
    )
    approach_count = sum(len(events) for events in events_by_tick.values())
    return {
        "mode": mode,
        "seed": seed,
        "interval_seconds_per_approach": interval,
        "seconds": seconds,
        "dt": dt,
        "ticks": tick_count,
        "attempted": attempted,
        "admitted": admitted,
        "admission_rate": round(admitted / attempted, 6) if attempted else 0.0,
        "rejected_at_capacity": capped,
        "rejected_for_source_clearance": blocked_at_source,
        "completed": completed,
        "remaining": len(traffic.cars),
        "throughput_vehicles_per_hour": round(completed * 3600 / seconds, 3),
        "mean_completed_trip_seconds": round(_mean(trip_times), 4),
        "mean_completed_delay_seconds": round(_mean(trip_delays), 4),
        "maximum_total_queue": maximum_queue,
        "maximum_approach_queue": maximum_approach_queue,
        "hard_gridlock_seconds": round(hard_gridlock_seconds, 3),
        "temporary_winner_ticks": temporary_winner_ticks,
        "overlap_pair_ticks": overlap_pair_ticks,
        "sub_1_5s_ttc_proxy_pair_ticks": sub_1_5s_ttc_pair_ticks,
        "minimum_ttc_circle_proxy_seconds": (
            round(minimum_ttc_proxy, 4) if minimum_ttc_proxy is not None else None
        ),
        "pet_proxy_below_1_5s": pet_below_1_5,
        "pet_proxy_overlapping_movement_pairs": pet_overlap_pairs,
        "minimum_pet_movement_clearance_seconds": (
            round(pet_min_gap, 4) if pet_min_gap is not None else None
        ),
        "median_tick_ms": round(median(tick_times), 5),
        "p95_tick_ms": round(_percentile(tick_times, 0.95), 5),
        "p99_tick_ms": round(_percentile(tick_times, 0.99), 5),
        "lane_connection_count": len(connections),
        "conflicting_movement_pairs": sum(map(len, crossing_movements.values())) // 2,
        "_active_tick_ms": dict(active_tick_ms),
        "_schedule_event_count": approach_count,
    }


def compare_intersection_complexity(
    *,
    seeds: Iterable[int] = DEFAULT_SEEDS,
    seconds: float = 90.0,
    dt: float = 0.05,
    max_cars: int = 80,
    demand_levels: Iterable[str] = tuple(DEMAND_LEVELS),
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Run all modes against three demand rates and summarize paired results."""
    seeds = tuple(seeds)
    if not seeds:
        raise ValueError("At least one seed is required")
    if len(set(seeds)) != len(seeds):
        raise ValueError("Seeds must be unique")
    demand_levels = tuple(demand_levels)
    if not demand_levels or len(set(demand_levels)) != len(demand_levels):
        raise ValueError("Choose one or more unique demand levels")
    unknown_levels = set(demand_levels) - set(DEMAND_LEVELS)
    if unknown_levels:
        raise ValueError("Unknown demand level(s): " + ", ".join(sorted(unknown_levels)))

    runs: list[dict[str, object]] = []
    tick_samples = {mode: defaultdict(list) for mode in MODES}
    total_runs = len(seeds) * len(demand_levels) * len(MODES)
    completed_runs = 0
    for level_index, level in enumerate(demand_levels):
        interval = DEMAND_LEVELS[level]
        for seed_index, seed in enumerate(seeds):
            schedule = make_demand_schedule(
                seed=seed, seconds=seconds, interval=interval, dt=dt,
            )
            order_offset = (level_index + seed_index) % len(MODES)
            ordered_modes = MODES[order_offset:] + MODES[:order_offset]
            for mode in ordered_modes:
                report = run_intersection_mode(
                    mode,
                    seed=seed,
                    seconds=seconds,
                    interval=interval,
                    dt=dt,
                    max_cars=max_cars,
                    demand_schedule=schedule,
                )
                samples = report.pop("_active_tick_ms")
                report.pop("_schedule_event_count")
                report["demand_level"] = level
                report["schedule_signature"] = _schedule_signature(schedule)
                for active_count, values in samples.items():
                    tick_samples[mode][active_count].extend(values)
                runs.append(report)
                completed_runs += 1
                if progress is not None:
                    progress(f"{completed_runs}/{total_runs} {level} seed={seed} {mode}")

    aggregates = _aggregate_runs(runs, demand_levels)
    scaling = _scaling_summary(tick_samples)
    return {
        "experiment": "single-four-leg-intersection-complexity",
        "seeds": list(seeds),
        "seconds_per_run": seconds,
        "dt": dt,
        "max_cars": max_cars,
        "demand_levels": {level: DEMAND_LEVELS[level] for level in demand_levels},
        "mode_order_counterbalanced": True,
        "runs": runs,
        "aggregates": aggregates,
        "runtime_scaling": scaling,
        "proxy_definitions": {
            "maximum_approach_queue": (
                "largest per-approach count within 120 distance units of its next "
                "junction movement while waiting or below half cruise speed"
            ),
            "TTC_circle_proxy": (
                "constant-heading, constant-speed circumscribed-circle TTC for "
                "vehicles whose next movements geometrically conflict; not a "
                "calibrated or observed crash TTC"
            ),
            "PET_movement_proxy": (
                "time between one vehicle clearing its full lane-connection movement "
                "and another conflicting movement entering; intervals are broad "
                "movement envelopes, not measured conflict-point PET"
            ),
            "overlap_pair_ticks": (
                "exact oriented vehicle-rectangle overlaps checked after each update"
            ),
        },
    }


def _queued_cars_by_approach(cars) -> dict[str, int]:
    queued: dict[str, int] = defaultdict(int)
    for car in cars:
        movement = next((item for item in car.controlled_movements
                         if item[1] + car.length / 2 >= car.distance), None)
        if movement is None:
            continue
        start, _, connection = movement
        distance_to_line = start - car.distance - car.length / 2
        waiting = bool(car.brain.wait_reason) or car.speed < 0.5 * car.cruise_speed_bound
        if waiting and -car.length <= distance_to_line <= 120.0:
            queued[connection.source_output.road.id] += 1
    return queued


def _conflicting_ttc_proxies(cars, crossing_movements, horizon: float = 5.0):
    candidates = []
    for car in cars:
        movement = next((item for item in car.controlled_movements
                         if item[1] + car.length / 2 >= car.distance), None)
        if movement is None:
            continue
        start, end, connection = movement
        distance_to_line = start - car.distance - car.length / 2
        if distance_to_line <= 120.0 and car.distance - car.length / 2 <= end:
            candidates.append((car, connection))
    critical_count = 0
    minimum: float | None = None
    for index, (car, connection) in enumerate(candidates):
        for other, other_connection in candidates[index + 1:]:
            if other_connection.id not in crossing_movements.get(connection.id, ()):
                continue
            ttc = _circle_ttc(car, other, horizon)
            if ttc is None:
                continue
            minimum = ttc if minimum is None else min(minimum, ttc)
            if ttc < 1.5:
                critical_count += 1
    return critical_count, minimum


def _circle_ttc(a, b, horizon: float) -> float | None:
    px, py = b.position[0] - a.position[0], b.position[1] - a.position[1]
    avx, avy = a.speed * a.heading[0], a.speed * a.heading[1]
    bvx, bvy = b.speed * b.heading[0], b.speed * b.heading[1]
    vx, vy = bvx - avx, bvy - avy
    radius = hypot(a.length / 2, a.width / 2) + hypot(b.length / 2, b.width / 2)
    c = px * px + py * py - radius * radius
    if c <= 0:
        return 0.0
    speed_sq = vx * vx + vy * vy
    if speed_sq <= 1e-12:
        return None
    dot = px * vx + py * vy
    if dot >= 0:
        return None
    discriminant = dot * dot - speed_sq * c
    if discriminant < 0:
        return None
    time = (-dot - sqrt(discriminant)) / speed_sq
    return time if 0 <= time <= horizon else None


def _pet_proxy_metrics(passages, crossing_movements):
    completed = [item for item in passages
                 if item["entered_at"] is not None and item["cleared_at"] is not None]
    close_gaps: list[float] = []
    overlap_count = 0
    for index, first in enumerate(completed):
        for second in completed[index + 1:]:
            if first["vehicle_id"] == second["vehicle_id"]:
                continue
            if second["connection_id"] not in crossing_movements.get(first["connection_id"], ()):
                continue
            start_a, end_a = first["entered_at"], first["cleared_at"]
            start_b, end_b = second["entered_at"], second["cleared_at"]
            if start_a <= end_b and start_b <= end_a:
                gap = 0.0
                overlap_count += 1
            else:
                gap = max(start_a, start_b) - min(end_a, end_b)
            close_gaps.append(gap)
    return (
        sum(gap < 1.5 for gap in close_gaps),
        overlap_count,
        min(close_gaps) if close_gaps else None,
    )


def _overlap_pair_count(cars) -> int:
    if len(cars) < 2:
        return 0
    cell_size = max(32.0, max(hypot(car.length, car.width) for car in cars))
    bins: dict[tuple[int, int], list] = defaultdict(list)
    pairs = 0
    for car in cars:
        cell = (int(car.position[0] // cell_size), int(car.position[1] // cell_size))
        for x in range(cell[0] - 1, cell[0] + 2):
            for y in range(cell[1] - 1, cell[1] + 2):
                for other in bins[(x, y)]:
                    pairs += vehicle_footprints_overlap(other, car)
        bins[cell].append(car)
    return pairs


def _aggregate_runs(runs, demand_levels):
    result = {}
    for level in demand_levels:
        result[level] = {}
        for mode in MODES:
            group = [run for run in runs
                     if run["demand_level"] == level and run["mode"] == mode]
            result[level][mode] = {
                "seeds": len(group),
                "median_seed_median_tick_ms": round(_median_metric(group, "median_tick_ms"), 5),
                "median_tick_ms_ci95": _bootstrap_median_ci(
                    [float(item["median_tick_ms"]) for item in group],
                    seed=1000 + list(DEMAND_LEVELS).index(level) * 10 + MODES.index(mode),
                ),
                "median_seed_p95_tick_ms": round(_median_metric(group, "p95_tick_ms"), 5),
                "mean_completed": round(_mean(float(item["completed"]) for item in group), 3),
                "mean_admission_rate": round(_mean(float(item["admission_rate"]) for item in group), 5),
                "mean_throughput_per_hour": round(_mean(float(item["throughput_vehicles_per_hour"]) for item in group), 3),
                "median_mean_delay_seconds": round(_median_metric(group, "mean_completed_delay_seconds"), 4),
                "median_maximum_total_queue": round(_median_metric(group, "maximum_total_queue"), 3),
                "median_maximum_approach_queue": round(_median_metric(group, "maximum_approach_queue"), 3),
                "total_hard_gridlock_seconds": round(_sum_metric(group, "hard_gridlock_seconds"), 3),
                "total_overlap_pair_ticks": int(_sum_metric(group, "overlap_pair_ticks")),
                "total_sub_1_5s_ttc_proxy_pair_ticks": int(_sum_metric(group, "sub_1_5s_ttc_proxy_pair_ticks")),
                "total_pet_proxy_below_1_5s": int(_sum_metric(group, "pet_proxy_below_1_5s")),
                "total_pet_proxy_overlapping_movement_pairs": int(_sum_metric(
                    group, "pet_proxy_overlapping_movement_pairs",
                )),
                "seeds_with_any_overlap": sum(bool(item["overlap_pair_ticks"]) for item in group),
                "mean_lane_connection_count": round(_mean(float(item["lane_connection_count"]) for item in group), 1),
                "mean_conflicting_movement_pairs": round(_mean(
                    float(item["conflicting_movement_pairs"]) for item in group
                ), 1),
            }
    return result


def _scaling_summary(tick_samples):
    bins = ((1, 10), (11, 20), (21, 30), (31, 40), (41, 50), (51, 60), (61, 80))
    result = {}
    for mode, by_count in tick_samples.items():
        by_bin = []
        for low, high in bins:
            values = [duration for count, samples in by_count.items()
                      if low <= count <= high for duration in samples]
            counts = [(count, len(samples)) for count, samples in by_count.items()
                      if low <= count <= high]
            sample_total = sum(number for _, number in counts)
            mean_active = (
                sum(count * number for count, number in counts) / sample_total
                if sample_total else None
            )
            by_bin.append({
                "active_vehicles": f"{low}-{high}",
                "mean_active_vehicles": round(mean_active, 3) if mean_active is not None else None,
                "ticks": sample_total,
                "median_tick_ms": round(median(values), 5) if values else None,
                "p95_tick_ms": round(_percentile(values, 0.95), 5) if values else None,
            })
        points = [
            (float(item["mean_active_vehicles"]), float(item["median_tick_ms"]))
            for item in by_bin
            if item["mean_active_vehicles"] is not None
            and item["median_tick_ms"] is not None
            and float(item["mean_active_vehicles"]) >= 5.0
        ]
        result[mode] = {
            "runtime_by_active_count": by_bin,
            "log_log_slope_beta": round(_log_log_slope(points), 3) if len(points) >= 2 else None,
        }
    return result


def _log_log_slope(points):
    xs = [log(x) for x, _ in points]
    ys = [log(y) for _, y in points]
    x_mean, y_mean = _mean(xs), _mean(ys)
    variance = sum((x - x_mean) ** 2 for x in xs)
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / variance if variance else 0.0


def _bootstrap_median_ci(values, *, seed: int, replicates: int = 2000):
    if not values:
        return [None, None]
    if len(values) == 1:
        value = round(values[0], 5)
        return [value, value]
    rng = random.Random(seed)
    samples = [median(rng.choices(values, k=len(values))) for _ in range(replicates)]
    return [round(_percentile(samples, 0.025), 5), round(_percentile(samples, 0.975), 5)]


def _schedule_signature(schedule):
    import hashlib
    payload = ";".join(
        f"{event.tick}:{event.source_index}:{event.destination_index}"
        for event in schedule
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _percentile(values, percentile):
    values = sorted(values)
    return values[max(0, ceil(percentile * len(values)) - 1)] if values else 0.0


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _median_metric(group, name):
    return median(float(item[name]) for item in group) if group else 0.0


def _sum_metric(group, name):
    return sum(float(item[name]) for item in group)
