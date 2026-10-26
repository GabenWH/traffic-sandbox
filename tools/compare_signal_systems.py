"""Compare two source trees in isolated processes with identical traffic demand.

python tools/compare_signal_systems.py --compare /path/to/old /path/to/new \
    --output docs/analysis/signal-rewrite-comparison.json

CPU timing covers only update(); demand admission, state restoration and safety
checks are outside that region. Frozen-state timings isolate algorithm cost
from the different car counts caused by better throughput.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import hashlib
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
from time import perf_counter_ns, process_time_ns


def worker(root, mode, seed, seconds, counts, samples):
    sys.path.insert(0, str(Path(root).resolve()))
    from city import CityMap, Terrain
    from intersection_complexity import APPROACHES, make_demand_schedule, _overlap_pair_count
    from intersection_controls import FixedTimeSignalController, SignalPhase, SignalPlan
    from models import ControlDefinition, ControlType
    from traffic_testbed import RoadVehicleSimulation

    def build(case, scale=1):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300*scale), (600*scale, 300*scale)])
        city.add_road([(300*scale, 0), (300*scale, 600*scale)])
        ends = {j.position: j for j in city.cul_de_sacs}
        endpoints = [ends[(x*scale, y*scale)] for x, y in APPROACHES]
        groups = [set() for _ in range(4)]
        for source in range(4):
            for destination in range(4):
                if source == destination:
                    continue
                route = city.find_vehicle_route_between(endpoints[source], endpoints[destination])
                for link in route.edges:
                    if link.kind == 'lane_connection' and link.value.intersection_id == city.standard_intersections[0].id:
                        link.value.control = ControlDefinition(ControlType.SIGNAL, 'benchmark')
                        if case != 'straight' or destination == (source + 2) % 4:
                            groups[source].add(link.value.id)
        phases = ([SignalPhase(18., groups[0] | groups[2]),
                   SignalPhase(18., groups[1] | groups[3])] if case == 'straight' else
                  [SignalPhase(12., group) for group in groups])
        t = RoadVehicleSimulation(spawn_interval=10000, max_cars=256,
                                  update_mode=mode, rng=random.Random(seed))
        t.signal_controllers['benchmark'] = FixedTimeSignalController(SignalPlan(tuple(phases)))
        return city, t, endpoints

    def percentile(values, fraction):
        return sorted(values)[min(len(values)-1, int(fraction*len(values)))]

    frozen = []
    for count in counts:
        city, t, ends = build('straight', 10)
        saved = []
        for index in range(count):
            source, row = index % 4, index // 4
            car = t.spawn_car(city, ends[source], ends[(source+2) % 4])
            assert car is not None
            car.id = f'bench-{index:05d}'
            start, end, connection = next(x for x in car.controlled_movements
                                         if x[2].maneuver.kind.value != 'u_turn')
            offset = 20. if source in (0, 2) and row == 0 else -car.length/2 - 22.*(row-1 if source in (0, 2) else row)
            car.distance, car.speed = start + offset, 0.
            car.advance(0)
            saved.append((car, car.distance, connection, row == 0 and source in (0, 2), vars(car.brain).copy()))
        wall, cpu = [], []
        for iteration in range(samples + 20):
            t.elapsed_time = 8.
            t.stop_coordinator.claims.clear()
            t.stop_coordinator.arrivals.clear()
            t.deadlock_resolver.reset()
            for car, distance, connection, inside, brain in saved:
                car.distance, car.speed = distance, 0.
                car._claimed_movement = None
                vars(car.brain).update(brain)
                car.advance(0)
                if inside and hasattr(t.stop_coordinator, 'claim_signal'):
                    assert t.stop_coordinator.claim_signal(car.id, connection)
                    car._claimed_movement = connection
            c0, w0 = process_time_ns(), perf_counter_ns()
            t.update(city, .05)
            w1, c1 = perf_counter_ns(), process_time_ns()
            if iteration >= 20:
                wall.append((w1-w0)/1e6)
                cpu.append((c1-c0)/1e6)
        frozen.append(dict(cars=count, median_ms=median(wall), p95_ms=percentile(wall,.95),
                           median_cpu_ms=median(cpu), samples=samples))

    flow = []
    for case in ('straight', 'turns'):
        city, t, ends = build(case)
        schedule = make_demand_schedule(seed=seed, seconds=seconds, interval=1.6)
        events = {}
        for event in schedule:
            events.setdefault(event.tick, []).append(event)
        waiting = [deque() for _ in range(4)]
        arrivals, starts, passages = {}, {}, set()
        attempted = admitted = completed = overlap_ticks = red_entries = yellow_entries = max_queue = 0
        trip_seconds, tick_ms, tick_cpu_ms, active_counts = [], [], [], []
        blocked_signal_seconds = 0.
        for tick in range(round(seconds/.05)):
            for event in events.get(tick, ()):
                destination = (event.source_index+2)%4 if case == 'straight' else event.destination_index
                waiting[event.source_index].append((destination, tick*.05))
                attempted += 1
            for source, queue in enumerate(waiting):
                if not queue or len(t.cars) >= 128:
                    continue
                destination, requested = queue[0]
                car = t.spawn_car(city, ends[source], ends[destination])
                if car is not None:
                    queue.popleft()
                    car.id = f'flow-{admitted:06d}'
                    arrivals[car.id] = requested
                    admitted += 1
            active_counts.append(len(t.cars))
            before = {car.id: car.distance + car.length/2 for car in t.cars}
            c0, w0 = process_time_ns(), perf_counter_ns()
            finished = t.update(city, .05)
            w1, c1 = perf_counter_ns(), process_time_ns()
            tick_ms.append((w1-w0)/1e6)
            tick_cpu_ms.append((c1-c0)/1e6)
            if t.deadlock_resolver.hard_gridlock:
                blocked_signal_seconds += .05
            for car in (*t.cars, *finished):
                for start, end, connection in car.controlled_movements:
                    if connection.control.kind is not ControlType.SIGNAL:
                        continue
                    key = (car.id, connection.id)
                    if key not in passages and before.get(car.id, -1) <= start and car.distance+car.length/2 > start+1e-8:
                        passages.add(key)
                        # Entry belongs to the interval's start; legal yellow
                        # admissions are distinguished from red violations.
                        state = t.signal_controllers['benchmark'].state_at(tick*.05)
                        if connection.id not in state.movement_ids or state.aspect.value == 'all_red':
                            red_entries += 1
                        elif state.aspect.value == 'yellow':
                            yellow_entries += 1
            for car in finished:
                completed += 1
                trip_seconds.append((tick+1)*.05-arrivals.pop(car.id))
            overlap_ticks += _overlap_pair_count(t.cars)
            max_queue = max(max_queue, sum(car.speed <= .1 for car in t.cars) + sum(map(len, waiting)))
        flow.append(dict(case=case, seconds=seconds, attempted=attempted, admitted=admitted,
                         completed=completed, remaining=len(t.cars), external_backlog=sum(map(len,waiting)),
                         completed_per_hour=completed*3600/seconds,
                         mean_completed_trip_seconds=sum(trip_seconds)/len(trip_seconds) if trip_seconds else None,
                         max_queue=max_queue, mean_active=sum(active_counts)/len(active_counts),
                         median_ms=median(tick_ms), p95_ms=percentile(tick_ms,.95),
                         median_cpu_ms=median(tick_cpu_ms), total_update_cpu_seconds=sum(tick_cpu_ms)/1000,
                         overlap_pair_ticks=overlap_ticks, red_entries=red_entries,
                         yellow_entries=yellow_entries, hard_gridlock_seconds=blocked_signal_seconds))
    return dict(mode=mode, seed=seed, frozen=frozen, flow=flow)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root')
    parser.add_argument('--mode', choices=('legacy','data_first'), default='data_first')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--seconds', type=float, default=180.)
    parser.add_argument('--counts', default='32,128,256')
    parser.add_argument('--samples', type=int, default=100)
    parser.add_argument('--compare', nargs=2, metavar=('OLD','NEW'))
    parser.add_argument('--seeds', default='0,1,2')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    counts = tuple(map(int,args.counts.split(',')))
    if args.root:
        print(json.dumps(worker(args.root,args.mode,args.seed,args.seconds,counts,args.samples)))
        return
    if not args.compare or not args.output:
        parser.error('--compare OLD NEW and --output are required')
    runs = []
    seeds = tuple(map(int,args.seeds.split(',')))
    for mode_index, mode in enumerate(('legacy','data_first')):
        for seed in seeds:
            order = ('old','new') if (mode_index+seed)%2 == 0 else ('new','old')
            for system in order:
                root = args.compare[0 if system == 'old' else 1]
                command = [sys.executable,str(Path(__file__).resolve()),'--root',str(Path(root).resolve()),
                           '--mode',mode,'--seed',str(seed),'--seconds',str(args.seconds),
                           '--counts',args.counts,'--samples',str(args.samples)]
                result = subprocess.run(command,check=True,capture_output=True,text=True)
                run = json.loads(result.stdout)
                run['system'] = system
                runs.append(run)
                completed = ', '.join(f"{item['case']}={item['completed']}" for item in run['flow'])
                print(f'{len(runs)}/{len(seeds)*4}: {system} {mode} seed={seed} completed: {completed}',flush=True)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(dict(complete=False, runs=runs), indent=2)+'\n')
    hashes = {}
    for label, root in zip(('old', 'new'), args.compare):
        digest = hashlib.sha256()
        for name in ('car_brain.py','intersection_controls.py','traffic_testbed.py','traffic_occupancy.py'):
            digest.update(name.encode())
            digest.update((Path(root)/name).read_bytes())
        hashes[label] = digest.hexdigest()
    report = dict(complete=True, source_sha256=hashes, frozen_counts=counts, frozen_samples=args.samples, baseline_commit='fa6fe8203ddf9f1c982d4e8e87b18c1b090a6c50',
                  python=sys.version,platform=platform.platform(),
                  methodology='Counterbalanced isolated processes; fixed external demand retained in FIFO backlogs; '
                  'CPU region is update only. Frozen-state restoration, source admissions and overlap/entry checks excluded. '
                  '20 frozen warmup ticks excluded. Flow figures include initial startup and end-of-run backlog.',
                  seconds=args.seconds,seeds=seeds,runs=runs)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(args.output)


if __name__ == '__main__': main()
