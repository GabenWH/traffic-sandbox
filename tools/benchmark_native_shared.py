"""Compare eager Python mirrors with live reads of C++ vehicle memory.

Includes the original generated crossing and fixed fleets on a longer crossing.
All modes retain Python occupancy, bookkeeping, RNG and source publication.
Display consumption reads every car's position, heading and signal per update;
this models state access, not window drawing or GPU rendering.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mobility import vehicle_route_points
from tools.benchmark_native_spawning import make_city, summarize
from traffic_testbed import RoadVehicleSimulation, RoutedRoadVehicle


def setup(city, controllers, mode, fleet, seed):
    cars = []
    if fleet:
        ends = city.cul_de_sacs
        routes = []
        for source in ends:
            destination = max(ends, key=lambda e: sum((a-b)**2 for a, b in zip(source.position, e.position)))
            route = city.find_vehicle_route_between(source, destination)
            routes.append((source, destination, route, vehicle_route_points(route)))
        for i in range(fleet):
            source, destination, route, points = routes[i % len(routes)]
            car = RoutedRoadVehicle(source.id, destination.id, route, points, 25*22/15,
                                    '#37e6ff', id=f'fleet-{i:06d}')
            car.place(car.controlled_movements[0][0] - 60 - (i//len(routes))*36)
            cars.append(car)
    traffic = RoadVehicleSimulation(update_mode='cpp', native_output_mode=mode,
                                    rng=random.Random(seed), spawn_interval=.8,
                                    max_cars=max(60, fleet), cars=cars)
    traffic.signal_controllers.update(controllers)
    if not fleet:
        for i, junction in enumerate(city.cul_de_sacs):
            traffic.toggle_junction(junction)
            traffic._spawn_elapsed[junction.id] = i*.8/len(city.cul_de_sacs)
    traffic._native_backend(city)
    traffic.update(city, 0)
    return traffic


def display_read(traffic):
    checksum = 0.0
    for car in traffic.cars:
        x, y = car.position
        hx, hy = car.heading
        checksum += x + y + hx + hy + len(car.brain.signal_intent.value)
    return checksum


def fingerprint(traffic, completed):
    rows = [(c.id, c.distance, c.speed, c.position, c.heading, c.brain.state.value,
             c.brain.signal_intent.value, c.brain.wait_reason, c.brain.phantom_target,
             c.brain.desired_speed, c.brain.stopped_elapsed,
             getattr(c.claimed_movement, 'id', None)) for c in traffic.cars]
    payload = (rows, completed, traffic.rng.getstate(), traffic._spawned_count, traffic._spawn_elapsed)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run(city, controllers, mode, fleet, reads, args):
    traffic = setup(city, controllers, mode, fleet, args.seed)
    try:
        for _ in range(round(args.warmup / args.dt)):
            traffic.update(city, args.dt)
            if reads:
                display_read(traffic)
        e = traffic._native_controller.engine
        e.enable_profile(True)
        samples, completed = [], []
        checksum = 0.0
        for _ in range(round(args.seconds / args.dt)):
            cpu_start, wall_start = process_time(), perf_counter()
            done = traffic.update(city, args.dt)
            after_update = perf_counter()
            if reads:
                checksum += display_read(traffic)
            wall_ms = (perf_counter() - wall_start)*1000
            cpu_ms = (process_time() - cpu_start)*1000
            completed.extend(c.id for c in done)
            samples.append({'cpu_ms': cpu_ms, 'wall_ms': wall_ms,
                            'update_wall_ms': (after_update-wall_start)*1000,
                            'active_cars': len(traffic.cars),
                            'phases_ms': dict(traffic.profiler.samples[-1].timings_ms)})
        phases = {k: summarize([s['phases_ms'][k] for s in samples])
                  for k in samples[0]['phases_ms']}
        return {'mode': mode, 'fleet': fleet, 'display_reads': reads,
                'mean_active': statistics.fmean(s['active_cars'] for s in samples),
                'peak_active': max(s['active_cars'] for s in samples),
                'spawned': traffic._spawned_count, 'completed': len(completed),
                'cpu_ms': summarize([s['cpu_ms'] for s in samples]),
                'wall_ms': summarize([s['wall_ms'] for s in samples]),
                'phases_ms': phases, 'native_profile': e.profile_snapshot(),
                'final_fingerprint': fingerprint(traffic, completed),
                'display_checksum': checksum, 'samples': samples}
    finally:
        traffic._discard_native()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fleet-sizes', type=int, nargs='*', default=[60, 250, 1000])
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--warmup', type=float, default=5)
    p.add_argument('--dt', type=float, default=.05)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.seconds < args.dt or args.dt <= 0 or args.warmup < 0 or args.repeats < 1 or any(n < 1 for n in args.fleet_sizes):
        p.error('positive fleet sizes, repeats, dt and seconds >= dt required; warmup >= 0')
    runs, comparisons = [], []
    for fleet in [0, *args.fleet_sizes]:
        road_length = 600 if not fleet else max(1200, 2*((fleet+3)//4*36+150))
        city, controllers = make_city('signalized-crossing', args.seed, road_length)
        for reads in (False, True):
            selected = []
            for repeat in range(args.repeats):
                order = ('copy', 'shared') if repeat % 2 == 0 else ('shared', 'copy')
                pair = [run(city, controllers, mode, fleet, reads, args) for mode in order]
                if (pair[0]['final_fingerprint'] != pair[1]['final_fingerprint'] or
                        pair[0]['display_checksum'] != pair[1]['display_checksum'] or
                        [s['active_cars'] for s in pair[0]['samples']] != [s['active_cars'] for s in pair[1]['samples']]):
                    raise RuntimeError(f'Behavior differs: fleet={fleet}, reads={reads}, repeat={repeat}')
                for r in pair:
                    r['repeat'] = repeat + 1
                    r['road_length'] = road_length
                runs.extend(pair)
                selected.extend(pair)
            means = {mode: statistics.fmean(r['cpu_ms']['mean'] for r in selected if r['mode'] == mode)
                     for mode in ('copy', 'shared')}
            comparison = {'fleet': fleet, 'display_reads': reads, 'cpu_ms': means,
                          'shared_cpu_reduction': 1-means['shared']/means['copy'],
                          'parity': True,
                          'mean_active': statistics.fmean(r['mean_active'] for r in selected)}
            comparisons.append(comparison)
            print(json.dumps(comparison), flush=True)
    report = {'method': 'Counterbalanced paired C++ runs; only output representation changes; phase timers enabled in both.',
              'sources_sha256': hashlib.sha256(b''.join((ROOT/path).read_bytes() for path in ('native/traffic/engine.cpp', 'native/traffic/engine.h', 'native_traffic.py', 'native_shared.py', 'native_spawning.py', 'tools/benchmark_native_shared.py'))).hexdigest(),
              'python': sys.version, 'platform': platform.platform(), 'arguments': vars(args) | {'output': str(args.output)},
              'comparisons': comparisons, 'runs': runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
