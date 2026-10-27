"""Profile full Python and native traffic updates on repeatable road scenarios.

Examples:
    python tools/benchmark_native_spawning.py --scenario signalized-crossing \
        --seconds 60 --warmup 10 --output build/native-spawning/signals.json
    python tools/benchmark_native_spawning.py --scenario roundabout-clear-entry \
        --seconds 30 --warmup 5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import statistics
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from city import CityMap, Terrain
from intersection_controls import (
    FixedTimeSignalController, SignalPhase, SignalPlan, movements_conflict,
)
from merge_lab import scenario_catalog
from models import ControlDefinition, ControlType
from traffic_testbed import RoadVehicleSimulation


def make_city(scenario: str, seed: int, road_length: float = 600) -> tuple[CityMap, dict[str, FixedTimeSignalController]]:
    if scenario == "signalized-crossing":
        city = CityMap(terrain=Terrain(trees=[]))
        middle = road_length / 2
        city.add_road([(0, middle), (road_length, middle)])
        city.add_road([(middle, 0), (middle, road_length)])
    else:
        matches = {item.name: item for item in scenario_catalog()}
        if scenario not in matches:
            raise ValueError(f"Unknown scenario: {scenario}")
        city, _ = matches[scenario].build(seed)

    controllers = {}
    if scenario == "signalized-crossing":
        junction = city.standard_intersections[0]
        connections = {}
        layer = city.mobility.layers['vehicles']
        for node in layer.graph.nodes:
            for transition in layer.graph.transitions_from(node):
                if transition.edge.kind != 'lane_connection':
                    continue
                connection = transition.edge.value
                if connection.intersection_id == junction.id:
                    connections[connection.id] = connection

        groups: list[list[object]] = []
        for connection in sorted(connections.values(), key=lambda item: item.id):
            for group in groups:
                if all(other.source_output == connection.source_output
                       or not movements_conflict(connection, other) for other in group):
                    group.append(connection)
                    break
            else:
                groups.append([connection])

        phases = []
        for index, group in enumerate(groups):
            for connection in group:
                connection.control = ControlDefinition(ControlType.SIGNAL, "profile-signal")
            phases.append(SignalPhase(
                8.0, {connection.id for connection in group},
                yellow_seconds=1.5, all_red_seconds=0.5,
                name=f"movement-group-{index + 1}",
            ))
        if not phases:
            raise RuntimeError("Signal benchmark found no movements at the crossing")
        controllers["profile-signal"] = FixedTimeSignalController(SignalPlan(tuple(phases)))
    return city, controllers


def percentile(values: list[float], rank: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * rank + 0.999999)))
    return ordered[index]


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {key: 0.0 for key in ("mean", "median", "p95", "p99", "max")}
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def run_engine(city, controllers, engine: str, *, seed: int, seconds: float,
               warmup: float, dt: float, max_cars: int) -> dict[str, object]:
    if engine == "cpp":
        factory = RoadVehicleSimulation
    else:
        from tests.reference_traffic import RoadVehicleSimulation as factory
    traffic = factory(
        update_mode="cpp" if engine == "cpp" else "data_first", rng=random.Random(seed), spawn_interval=0.8,
        max_cars=max_cars,
    )
    traffic.signal_controllers.update(controllers)
    for junction in city.cul_de_sacs:
        traffic.toggle_junction(junction)
    for index, junction in enumerate(city.cul_de_sacs):
        traffic._spawn_elapsed[junction.id] = index * traffic.spawn_interval / max(1, len(city.cul_de_sacs))

    if engine == "cpp":
        # Build/compile before measurement so the report describes update CPU.
        traffic._native_backend(city)
    traffic.update(city, 0.0)
    if engine == "cpp":
        traffic._native_controller.engine.enable_profile(True)

    warmup_ticks = round(warmup / dt)
    for _ in range(warmup_ticks):
        traffic.update(city, dt)
    if engine == "cpp":
        traffic._native_controller.engine.enable_profile(True)

    sample_count = round(seconds / dt)
    samples = []
    peak_active = len(traffic.cars)
    completed = 0
    spawned_before = traffic._spawned_count
    for tick in range(sample_count):
        cpu_start = process_time()
        wall_start = perf_counter()
        done = traffic.update(city, dt)
        wall_ms = (perf_counter() - wall_start) * 1000
        cpu_ms = (process_time() - cpu_start) * 1000
        completed += len(done)
        peak_active = max(peak_active, len(traffic.cars))
        timings = dict(traffic.profiler.samples[-1].timings_ms)
        samples.append({
            "tick": tick + 1,
            "simulated_time": traffic.elapsed_time,
            "active_cars": len(traffic.cars),
            "spawned": traffic._spawned_count - spawned_before,
            "completed": completed,
            "cpu_ms": cpu_ms,
            "wall_ms": wall_ms,
            "timings_ms": timings,
        })
    native_profile = (
        traffic._native_controller.engine.profile_snapshot()
        if engine == "cpp" else None
    )
    native_summary = {}
    if engine == "cpp":
        phase_names = sorted({key for sample in samples for key in sample["timings_ms"]})
        native_summary = {
            name: summarize([sample["timings_ms"].get(name, 0.0) for sample in samples])
            for name in phase_names
        }
    report = {
        "engine": engine,
        "seed": seed,
        "seconds": seconds,
        "warmup_seconds": warmup,
        "dt": dt,
        "sample_count": len(samples),
        "peak_active": peak_active,
        "final_active": len(traffic.cars),
        "spawned": traffic._spawned_count - spawned_before,
        "completed": completed,
        "samples": samples,
        "summary": {
            "cpu_ms": summarize([sample["cpu_ms"] for sample in samples]),
            "wall_ms": summarize([sample["wall_ms"] for sample in samples]),
            "native_spawning": native_summary,
            "native_engine": native_profile,
        },
    }
    traffic._discard_native()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="signalized-crossing")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--dt", type=float, default=0.05)
    parser.add_argument("--max-cars", type=int, default=80)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (args.seconds <= 0 or args.warmup < 0 or args.dt <= 0
            or args.max_cars <= 0 or args.repeats < 1):
        parser.error("seconds, dt, and repeats must be positive; warmup must be nonnegative; max-cars must be positive")

    runs = []
    run_order = []
    for repeat in range(args.repeats):
        city, controllers = make_city(args.scenario, args.seed)
        engines = ("cpp", "reference_data_first") if repeat % 2 == 0 else ("reference_data_first", "cpp")
        run_order.append({"repeat": repeat + 1, "engines": list(engines)})
        for engine in engines:
            run = run_engine(
                city, controllers, engine, seed=args.seed, seconds=args.seconds,
                warmup=args.warmup, dt=args.dt, max_cars=args.max_cars,
            )
            run["repeat"] = repeat + 1
            runs.append(run)
    aggregate = {}
    for engine in ("cpp", "reference_data_first"):
        selected = [run for run in runs if run["engine"] == engine]
        aggregate[engine] = {
            "runs": len(selected),
            "cpu_ms_per_update": summarize([run["summary"]["cpu_ms"]["mean"] for run in selected]),
            "wall_ms_per_update": summarize([run["summary"]["wall_ms"]["mean"] for run in selected]),
            "mean_spawned": statistics.fmean(run["spawned"] for run in selected),
            "mean_completed": statistics.fmean(run["completed"] for run in selected),
            "mean_peak_active": statistics.fmean(run["peak_active"] for run in selected),
        }
    native_cpu = aggregate["cpp"]["cpu_ms_per_update"]["mean"]
    data_first_cpu = aggregate["reference_data_first"]["cpu_ms_per_update"]["mean"]
    report = {
        "scenario": args.scenario,
        "seed": args.seed,
        "repeats": args.repeats,
        "run_order": run_order,
        "method": "per-update process CPU and wall time; optional native C++ phase timers",
        "runs": runs,
        "aggregate": aggregate,
        "comparison": {
            "native_cpu_reduction": (
                1.0 - native_cpu / data_first_cpu if data_first_cpu else 0.0
            ),
            "native_cpu_speedup": (
                data_first_cpu / native_cpu if native_cpu else 0.0
            ),
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
