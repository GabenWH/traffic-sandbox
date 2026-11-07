"""Measure unchanged parked fleets and full-lot queues without traffic/UI work.

Run this same script with --module-root pointing at each checkout to compare
implementations. Setup and one warm-up observation are excluded. State reads
are counted in a separate pass so instrumentation does not inflate timings.
Older full-lot queues may require quadratic work; --max-record-reads bounds
that pass and reports censored cases rather than inventing a timing estimate.
"""
import argparse
from collections import deque
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter_ns, process_time_ns
from types import SimpleNamespace


class ReadBudgetExceeded(RuntimeError):
    pass


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def instrumented_vehicle(base, budget):
    class CountedVehicle(base):
        reads = 0
        read_budget = budget
        tracked_fields = frozenset(('phase', 'site', 'parking_space_id', 'reserved_space_id',
                                    'road_stop_lane_id', 'reserved_road_stop_lane_id'))

        def __getattribute__(self, name):
            if name in type(self).tracked_fields:
                cls = type(self)
                cls.reads += 1
                if cls.read_budget and cls.reads > cls.read_budget:
                    raise ReadBudgetExceeded
            return super().__getattribute__(name)

    return CountedVehicle


def fixture(fleet_class, vehicle_class, case, population):
    # Direct bulk construction keeps the old add() algorithm out of the
    # experiment. Both versions receive valid count-only parking records.
    fleet = fleet_class(SimpleNamespace(vehicle_arrivals=deque()), {
        'home': {'parking_capacity': population}, 'full': {'parking_capacity': 1}})
    if case == 'parked':
        fleet.vehicles.update((str(index), vehicle_class(str(index), 'car', 'home'))
                              for index in range(population))
    else:
        fleet.vehicles['occupant'] = vehicle_class('occupant', 'car', 'full')
        fleet.vehicles.update((str(index), vehicle_class(str(index), 'car', 'full',
                              phase='waiting_for_parking')) for index in range(population))
    return fleet


def measure(fleet_class, vehicle_class, case, population, repetitions, repeats, read_budget):
    counted = instrumented_vehicle(vehicle_class, read_budget)
    fleet = fixture(fleet_class, counted, case, population)
    result = dict(case=case, population=population,
                  persistent_records=population+(case == 'waiters'),
                  repetitions=repetitions, repeats=repeats)
    completed = 0
    stage = 'warmup'
    counted.reads = 0
    try:
        fleet.observe()
        result['warmup_record_reads'] = counted.reads
        stage = 'measured'
        counted.reads = 0
        for _ in range(repetitions):
            fleet.observe()
            completed += 1
    except ReadBudgetExceeded:
        result.update(status='read_budget_exceeded', budget_stage=stage,
                      record_reads=counted.reads, completed_observations=completed,
                      timing_skipped=True)
        return result
    result.update(status='measured', record_reads=counted.reads,
                  record_reads_per_observation=counted.reads/repetitions,
                  completed_observations=completed)

    plain = fixture(fleet_class, vehicle_class, case, population)
    plain.observe()
    wall, cpu = [], []
    for _ in range(repeats):
        started_wall, started_cpu = perf_counter_ns(), process_time_ns()
        for _ in range(repetitions):
            plain.observe()
        cpu.append((process_time_ns()-started_cpu)/repetitions)
        wall.append((perf_counter_ns()-started_wall)/repetitions)
    result.update(wall_ns_per_observation=median(wall), cpu_ns_per_observation=median(cpu),
                  wall_ns_samples=wall, cpu_ns_samples=cpu)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='checkout providing persistent_fleet.py and its dependencies')
    parser.add_argument('--sizes', type=positive_integer, nargs='+', default=[100, 1000, 16000])
    parser.add_argument('--cases', choices=('parked', 'waiters'), nargs='+', default=['parked', 'waiters'])
    parser.add_argument('--repetitions', type=positive_integer, default=100)
    parser.add_argument('--repeats', type=positive_integer, default=5)
    parser.add_argument('--max-record-reads', type=int, default=20_000_000,
                        help='read budget for each warmup/measured counting pass; 0 disables the guard')
    parser.add_argument('--label', default=None)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    root = args.module_root.resolve()
    if not (root/'persistent_fleet.py').is_file():
        parser.error('--module-root must contain persistent_fleet.py')
    if args.max_record_reads < 0:
        parser.error('--max-record-reads must be nonnegative')
    sys.path.insert(0, str(root))
    from persistent_fleet import FleetVehicle, PersistentFleet
    report = dict(label=args.label, module_root=str(root), python=platform.python_version(),
                  method='One warmup; independent state-read and uninstrumented timing passes; '
                         'median of fixed-length repeats; setup, routing, native traffic and UI excluded.',
                  max_record_reads=args.max_record_reads,
                  cases=[measure(PersistentFleet, FleetVehicle, case, population,
                                 args.repetitions, args.repeats, args.max_record_reads)
                         for case in args.cases for population in args.sizes])
    rendered = json.dumps(report, indent=2)+'\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
