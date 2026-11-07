#!/usr/bin/env python3
"""Compare eager/lazy parking admission on the real Arcata benchmark map.

The baseline flag loads only parking_trips.py from the recorded starting commit.
All other code, scenario parameters, and instrumentation stay the same. Probe
timings are controlled cold admissions, not whole-city tick measurements.
"""
import argparse
from collections import Counter
import gc
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import city_simulation
from native_walking import NativeWalkingGraph
from persistent_fleet import FleetVehicle
from tools.run_arcata_city_workday import build_city, build_scenario, CommutePolicy, run_workday

BASELINE = '9e8d39218837ab68c757fa9f806aba1f410ee03d'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('probes', 'commute'), required=True)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    variant = 'eager' if args.baseline else 'bounded-lazy'
    parking_source = (ROOT/'parking_trips.py').read_text()
    if args.baseline:
        module = types.ModuleType('benchmark_baseline_parking')
        code = subprocess.check_output(['git', 'show', BASELINE+':parking_trips.py'], cwd=ROOT, text=True)
        exec(compile(code, BASELINE+':parking_trips.py', 'exec'), module.__dict__)
        city_simulation.ParkingTrips = module.ParkingTrips
        parking_source = code
    started = time.perf_counter()
    queries = 0
    original_route = NativeWalkingGraph.route

    def route(graph, *points):
        nonlocal queries
        queries += 1
        return original_route(graph, *points)

    NativeWalkingGraph.route = route

    def emit(row):
        row = dict(elapsed_wall=time.perf_counter()-started, variant=variant, **row)
        with (args.output/'metrics.jsonl').open('a') as stream:
            stream.write(json.dumps(row, allow_nan=False)+'\n')
        keys = ('stage', 'variant', 'elapsed_wall', 'clock_hour', 'ticks', 'tick_mean_ms',
                'run_max_tick_ms', 'walking_queries', 'walk_cache_size', 'max_gc_ms')
        print(json.dumps({k:row[k] for k in keys if k in row}), flush=True)

    runtime = None
    try:
        emit(dict(stage='loading'))
        city, _, source = build_city(
            [ROOT/'benchmarks/arcata/arcata-roads-2026-06-01.json'],
            ROOT/'benchmarks/arcata/arcata-city-boundary.osm',
            building_paths=[ROOT/'benchmarks/arcata/arcata-buildings-citywide-2026-11-04.json.gz'])
        runtime, config = build_scenario(city, cars=1000, seed=42, start_hour=7,
                                         population=16000, commute_policy=CommutePolicy())
        config.update(source=source, variant=variant, parking_baseline=BASELINE,
                      working_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      parking_source_sha256=hashlib.sha256(parking_source.encode()).hexdigest(),
                      runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        (args.output/'configuration.json').write_text(json.dumps(config, indent=2))
        emit(dict(stage='ready', walking_queries=queries, walk_cache_size=len(runtime.transit._walk_cache)))
        if args.mode == 'probes':
            drivers = [p for p in runtime.residents.values() if p.car_id and p.workplace
                       and runtime.sites[p.workplace]['road_position'] is not None
                       and runtime.fleet._lot_key(p.home) != runtime.fleet._lot_key(p.workplace)]
            drivers.sort(key=lambda p:(-len(runtime.parking_trips.access.candidates(
                p.workplace, max_distance=runtime.commute_policy.parking_walk_seconds*4.4)), p.id))
            selected, seen = [], set()
            for person in drivers:
                if person.workplace not in seen:
                    selected.append(person)
                    seen.add(person.workplace)
                if len(selected) == 12:
                    break
            rows = []
            for index, person in enumerate(selected):
                vehicle = runtime.fleet.vehicles[person.car_id]
                target = person.workplace
                full = index % 2 == 1
                if full:
                    serial = 0
                    while runtime.fleet._available_space(vehicle, target) is not False:
                        runtime.fleet.add(FleetVehicle(f'probe-occupant-{index}-{serial}', 'car', target))
                        serial += 1
                available = runtime.fleet._available_space(vehicle, target) is not False
                before_queries, before_cache = queries, len(runtime.transit._walk_cache)
                before = time.perf_counter_ns()
                admitted = runtime._safe_depart(person)
                ms = (time.perf_counter_ns()-before)/1e6
                row = dict(person=person.id, destination=target, primary_available=available,
                           primary_forced_full=full, admitted=admitted, status=runtime.fleet.last_dispatch_status,
                           chosen=vehicle.destination, wall_ms=ms, walking_queries=queries-before_queries,
                           new_cache_entries=len(runtime.transit._walk_cache)-before_cache)
                rows.append(row)
                emit(dict(stage='probe', **row))
            # Query actual indexed capacity on real lots, not a nearby-car scan.
            before = time.perf_counter_ns()
            checks = 10000
            for i in range(checks):
                person = selected[i % len(selected)]
                runtime.fleet._available_space(runtime.fleet.vehicles[person.car_id], person.workplace)
            occupancy_ns = (time.perf_counter_ns()-before)/checks
            admission_cache = len(runtime.transit._walk_cache)
            tracked_objects = len(gc.get_objects())
            # This is deliberately after timing: compare complete eligibility/order.
            validation = {}
            for person in selected:
                options = tuple(runtime.parking_trips.options(person.workplace))
                validation[person.workplace] = dict(count=len(options), sha256=hashlib.sha256(
                    json.dumps(options).encode()).hexdigest())
            result = dict(variant=variant, probes=rows, availability_check_mean_us=occupancy_ns/1000,
                          admission_walk_cache=admission_cache, tracked_objects_after_admissions=tracked_objects,
                          complete_options=validation, scenario=config,
                          note='No simulation updates in probes; synchronous route admission. Timings include Python path materialization and any automatic GC.')
        else:
            tick = 0
            all_ms = []
            events = []
            current_gc = []
            gc_starts = {}
            generations = Counter()
            max_gc = 0.

            def collector(phase, info):
                nonlocal max_gc
                generation = info['generation']
                if phase == 'start':
                    gc_starts[generation] = time.perf_counter_ns()
                elif generation in gc_starts:
                    ms = (time.perf_counter_ns()-gc_starts.pop(generation))/1e6
                    generations[generation] += 1
                    max_gc = max(max_gc, ms)
                    current_gc.append(dict(generation=generation, wall_ms=ms, collected=info['collected']))

            gc.callbacks.append(collector)
            original_update = runtime.update

            def update(seconds):
                nonlocal tick
                current_gc.clear()
                before_queries = queries
                clock = runtime.time
                before = time.perf_counter_ns()
                cpu = time.thread_time_ns()
                original_update(seconds)
                ms = (time.perf_counter_ns()-before)/1e6
                cpu_ms = (time.thread_time_ns()-cpu)/1e6
                all_ms.append(ms)
                tick += 1
                if ms >= 50 or current_gc and any(g['generation'] == 2 for g in current_gc):
                    row = dict(tick=tick, clock_before=clock, step_seconds=seconds, wall_ms=ms,
                               main_cpu_ms=cpu_ms, gc=current_gc.copy(), walking_queries=queries-before_queries,
                               walk_cache_size=len(runtime.transit._walk_cache))
                    events.append(row)

            runtime.update = update

            def progress(row):
                emit(dict(**row, walking_queries=queries, walk_cache_size=len(runtime.transit._walk_cache),
                          max_gc_ms=max_gc, gc_collections=dict(generations)))
                # Persist diagnostics outside the timed update. An interrupted
                # execution session must not erase the captured slow ticks.
                checkpoint = dict(ticks=tick, clock=runtime.time, walking_queries=queries,
                                  walk_cache_size=len(runtime.transit._walk_cache),
                                  inner_step_wall_seconds=sum(all_ms)/1000,
                                  largest_ticks=sorted(events, key=lambda r:r['wall_ms'], reverse=True)[:10])
                temporary = args.output/'checkpoint.json.tmp'
                temporary.write_text(json.dumps(checkpoint, indent=2))
                temporary.replace(args.output/'checkpoint.json')
                (args.output/'slow-ticks.jsonl').write_text(''.join(json.dumps(event)+'\n' for event in events))

            try:
                result = run_workday(runtime, hours=2, report_every=300, emit=progress)
            finally:
                gc.callbacks.remove(collector)
                runtime.update = original_update
            ordered = sorted(all_ms)
            (args.output/'slow-ticks.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in events))
            # Keep the outer wrapper measurements for audit, and consistently
            # compare inner simulation timings (without diagnostic bookkeeping).
            outer = {k:result[k] for k in ('step_wall_seconds', 'mean_tick_ms', 'max_tick_ms',
                                         'ticks_over_50ms', 'ticks_over_100ms')}
            result.update(variant=variant, scenario=config, walking_queries=queries,
                          walk_cache_size=len(runtime.transit._walk_cache), max_gc_ms=max_gc,
                          gc_collections=dict(generations),
                          p95_tick_ms=ordered[math.ceil(len(ordered)*.95)-1],
                          p99_tick_ms=ordered[math.ceil(len(ordered)*.99)-1],
                          step_wall_seconds=sum(all_ms)/1000, mean_tick_ms=sum(all_ms)/len(all_ms),
                          max_tick_ms=max(all_ms), ticks_over_50ms=sum(ms>50 for ms in all_ms),
                          ticks_over_100ms=sum(ms>100 for ms in all_ms), outer_update_timing=outer,
                          largest_ticks=sorted(events, key=lambda r:r['wall_ms'], reverse=True)[:10],
                          note='50 ms headless city updates, including CPU/GC instrumentation; report construction excluded. Background routing makes repeated city histories timing-sensitive.')
            assert result['stop_reason'] == 'duration'
            assert result['simulated_seconds'] == 7200.
            assert sum(result['final']['states'].values()) == 16000
            assert abs(result['final']['resource_balance_error']) < 1e-3
        (args.output/'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False))
        emit(dict(stage='complete', walking_queries=queries, walk_cache_size=len(runtime.transit._walk_cache)))
    finally:
        NativeWalkingGraph.route = original_route
        if runtime is not None:
            runtime.close()


if __name__ == '__main__':
    main()
