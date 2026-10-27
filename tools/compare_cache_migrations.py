#!/usr/bin/env python3
"""Compare cache migrations with a git revision on the same moving network.

Run from the repository root. Alternating update order reduces host timing bias.
Results describe this host/run; the per-tick state assertions are the behavioral
check. Route discovery and state comparison are outside update timing.
"""

import argparse
from collections import Counter
import json
from math import dist
from pathlib import Path
import random
import subprocess
import sys
from time import perf_counter
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simulation_profiler import SimulationProfiler
from traffic_testbed import RoadVehicleSimulation
from merge_lab import _overlapping_pairs
from tools.run_arcata_scale_test import build_city, choose_portals, profile_statistics


def baseline_module(revision):
    """Load only the old traffic modules; use identical network/model classes."""
    import traffic_occupancy

    def load(name, filename):
        source = subprocess.run(["git", "show", f"{revision}:{filename}"],
                                cwd=ROOT, capture_output=True, text=True, check=True).stdout
        module = types.ModuleType(name)
        sys.modules[name] = module  # dataclass resolves its defining module.
        exec(compile(source, f"{revision}:{filename}", "exec"), module.__dict__)
        return module

    old_index = load("_baseline_occupancy", "traffic_occupancy.py")
    try:
        sys.modules["traffic_occupancy"] = old_index
        return load("_baseline_testbed", "traffic_testbed.py")
    finally:
        sys.modules["traffic_occupancy"] = traffic_occupancy


def car_state(car):
    return (car.id, car.source_id, car.destination_id, car.distance, car.speed,
            tuple(vars(car.brain).items()), car.heading, car._merge_entry_speed,
            car.length, car.width, getattr(car.claimed_movement, "id", None))


def compare(before, after, completed_before, completed_after, frame, reference):
    old = sorted(before.cars, key=lambda car: car.id)
    new = sorted(after.cars, key=lambda car: car.id)
    assert [car_state(car) for car in old] == [car_state(car) for car in new], (
        frame, "vehicle state", [(car_state(a), car_state(b)) for a, b in zip(old, new)
                                  if car_state(a) != car_state(b)][:2])
    assert [car.id for car in completed_before] == [car.id for car in completed_after], frame
    assert before.rng.getstate() == after.rng.getstate(), (frame, "RNG")
    assert before.active_junction_ids == after.active_junction_ids, (frame, "sources")
    assert before._spawn_elapsed == after._spawn_elapsed, (frame, "timers")
    for name in ("claims", "arrivals"):
        assert getattr(before.stop_coordinator, name) == getattr(after.stop_coordinator, name), (frame, name)
    assert vars(before.deadlock_resolver) == vars(after.deadlock_resolver), (frame, "deadlock")
    # The old legacy index can retain a just-completed vehicle until next tick.
    # Rebuild the reference from the completed roster outside update timing.
    reference.rebuild(before.cars)
    for a, b in zip(old, new):
        expected = reference.lead_car_gap(a, 128)
        actual = after.occupancy.lead_car_gap(b, 128)
        assert (None if expected is None else (expected[0].id, expected[1])) == (
            None if actual is None else (actual[0].id, actual[1])), (frame, "occupancy", a.id)
    old_overlaps = {tuple(sorted((a.id, b.id))) for a, b in _overlapping_pairs(old)}
    new_overlaps = {tuple(sorted((a.id, b.id))) for a, b in _overlapping_pairs(new)}
    assert old_overlaps == new_overlaps, (frame, "overlaps")
    error = max((dist(a.position, b.position) for a, b in zip(old, new)), default=0)
    assert error < 1e-8, (frame, "geometry", error)
    return error, len(new_overlaps)


def run(args):
    baseline = baseline_module(args.base)
    if args.network == "arcata":
        city, ids, _ = build_city([ROOT / "benchmarks/arcata/arcata-roads-2026-06-01.json"],
                                 ROOT / "benchmarks/arcata/arcata-city-boundary.osm")
        sources = choose_portals(city, ids, 16)
    elif args.network == "gauntlet":
        from merge_lab import _dense_network_gauntlet
        city, _template = _dense_network_gauntlet(20261017)
        sources = list(city.cul_de_sacs)
    else:
        from persistence import world_from_dict
        city = world_from_dict(json.loads((ROOT / "tests/fixtures/slip_lanes.json").read_text())).city_map
        sources = list(city.cul_de_sacs)
    steps = round(args.seconds / .05)
    interval = .12 if args.network == "gauntlet" else .5
    before = baseline.RoadVehicleSimulation(update_mode="data_first", spawn_interval=interval,
                                           max_cars=100, rng=random.Random(20261017))
    after = RoadVehicleSimulation(update_mode=args.mode, spawn_interval=interval,
                                  max_cars=100, rng=random.Random(20261017))
    for traffic in (before, after):
        for source in sources:
            traffic.toggle_junction(source)
        traffic.sync_network(city)
        if args.network == "gauntlet":
            for index, source in enumerate(sources):
                traffic._spawn_elapsed[source.id] = index * interval / len(sources)
        traffic.profiler = SimulationProfiler(max_samples=steps + 1)
        traffic.occupancy.profile_internal_timings = True
    for source in sources:
        for destination in sources:
            if source is not destination:
                route = city.find_vehicle_route_between(source, destination)
                for traffic in (before, after):
                    traffic._spawn_routes[id(source), id(destination)] = route
    counts = Counter()
    original_rebuild = after.occupancy.rebuild
    original_sort = after.occupancy._sort_lane
    def rebuild(cars):
        counts["full_rebuilds"] += 1
        return original_rebuild(cars)
    def sort(entries):
        counts["lane_sorts"] += 1
        return original_sort(entries)
    after.occupancy.rebuild = rebuild
    after.occupancy._sort_lane = sort
    costs = {"before": [], "after": []}
    completed_total = peak = overlap_pair_ticks = 0
    geometry_error = 0
    reference = baseline.TrafficOccupancyIndex()
    heartbeat = perf_counter()
    for frame in range(steps):
        cap = 100 if frame < steps // 2 else 200
        before.max_cars = after.max_cars = cap
        order = (("before", before), ("after", after))
        completed = {}
        for name, traffic in (order if frame % 2 else reversed(order)):
            start = perf_counter()
            completed[name] = traffic.update(city, .05)
            costs[name].append((perf_counter() - start) * 1000)
        error, overlaps = compare(before, after, completed["before"],
                                  completed["after"], frame, reference)
        geometry_error = max(geometry_error, error)
        overlap_pair_ticks += overlaps
        completed_total += len(completed["after"])
        peak = max(peak, len(after.cars))
        if perf_counter() - heartbeat > 20:
            print(f"{args.mode}/{args.network}: {(frame + 1)*.05:.1f}/{args.seconds}s; {len(after.cars)} cars; exact state", flush=True)
            heartbeat = perf_counter()
    result = {
        "base": args.base, "mode": args.mode, "network": args.network,
        "seconds": args.seconds, "ticks": steps, "exact_state_every_tick": True,
        "maximum_geometry_error_feet": geometry_error,
        "spawned": after._spawned_count, "completed": completed_total, "peak_cars": peak,
        "remaining": len(after.cars), "overlap_pair_ticks": overlap_pair_ticks,
        "incremental_counts": {"full_rebuilds": counts["full_rebuilds"],
                               "lane_sorts": counts["lane_sorts"]},
    }
    for name, traffic in (("before", before), ("after", after)):
        all_samples = list(traffic.profiler.samples)
        stage_samples = all_samples[steps // 2:]
        result[name] = {
            "stage_one_phases": profile_statistics(all_samples[:steps // 2]),
            "all_phases": profile_statistics(all_samples),
            "stage_two_mean_cars": sum(s.entity_counts["cars"] for s in stage_samples) / len(stage_samples),
            "stage_two_phases": profile_statistics(stage_samples),
            "stage_two_wall_mean_ms": sum(costs[name][steps // 2:]) / len(costs[name][steps // 2:]),
        }
    print(json.dumps(result, indent=2), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="6fe1084")
    parser.add_argument("--mode", choices=("cpp",), default="cpp")
    parser.add_argument("--network", choices=("arcata", "slip_lanes", "gauntlet"), default="arcata")
    parser.add_argument("--seconds", type=float, default=300)
    parser.add_argument("--output", type=Path)
    run(parser.parse_args())
