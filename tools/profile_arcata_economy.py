#!/usr/bin/env python3
"""Profile coarse economy phases in the unchanged, seeded Arcata runner.

Pass normal run_arcata_city_workday.py arguments. Add --cprofile for a separate
diagnostic run; do not compare those times with unprofiled runs. Setup, reports,
and serialization are excluded from phase timers. Exclusive seconds partition
the instrumented update time; nested inclusive seconds must not be added.
"""
from collections import Counter
from functools import wraps
import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import run_arcata_city_workday as runner
from city_simulation import CitySimulation
from town_services import ServiceTown


class EconomyClock:
    def __init__(self):
        self.active = False
        self.stack = []
        self.rows = {}
        self.callers = Counter()
        self.elapsed = Counter()
        self.scan_rows = Counter()

    def wrap(self, method, name):
        @wraps(method)
        def timed(*args, **kwargs):
            if not self.active:
                return method(*args, **kwargs)
            owner = args[0]
            if name == 'city._settle_economy':
                caller = sys._getframe(1)
                label = caller.f_code.co_name
                if label == '_run_event':
                    label += ':' + str(caller.f_locals.get('kind'))
                self.callers[label] += 1
                self.elapsed[round(max(0, args[1] - owner._last_economy), 6)] += 1
                del caller
            if name == 'services.incoming':
                self.scan_rows['job_rows'] += len(owner.jobs)
                self.scan_rows['visit_rows'] += len(owner.visits)
            frame = [name, time.perf_counter(), 0.0]
            self.stack.append(frame)
            try:
                return method(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - frame[1]
                self.stack.pop()
                if self.stack:
                    self.stack[-1][2] += elapsed
                row = self.rows.setdefault(name, dict(calls=0, inclusive_seconds=0., exclusive_seconds=0.))
                row['calls'] += 1
                row['inclusive_seconds'] += elapsed
                row['exclusive_seconds'] += elapsed - frame[2]
        return timed


def profile_run(runtime, original, out, use_cprofile, **kwargs):
    clock = EconomyClock()
    patches = []
    for cls, prefix, names in (
        (CitySimulation, 'city', ('update', '_settle_economy', '_economy', '_choose_shoppers', '_settle_households')),
        (ServiceTown, 'services', ('_economy', '_consume_households', '_logistics', 'incoming', '_incoming_totals')),
    ):
        for name in names:
            if name not in cls.__dict__:
                continue
            method = getattr(cls, name)
            patches.append((cls, name, method))
            setattr(cls, name, clock.wrap(method, prefix + '.' + name))
    update = runtime.update
    def active_update(dt):
        clock.active = True
        try:
            return update(dt)
        finally:
            clock.active = False
    runtime.update = active_update
    profiler = cProfile.Profile() if use_cprofile else None
    try:
        if profiler:
            profiler.enable()
        return original(runtime, **kwargs)
    finally:
        if profiler:
            profiler.disable()
            profiler.dump_stats(str(out / 'economy.pstats'))
            with (out / 'economy-cprofile.txt').open('w') as stream:
                pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(65)
        runtime.update = update
        for cls, name, method in reversed(patches):
            setattr(cls, name, method)
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
        data = dict(phases=clock.rows, settlement_callers=dict(clock.callers),
                    settlement_elapsed_seconds=dict(clock.elapsed), incoming_scan_rows=dict(clock.scan_rows),
                    git_head=git('rev-parse', 'HEAD'), git_tree=git('rev-parse', 'HEAD^{tree}'),
                    tracked_diff_sha256=hashlib.sha256(git('diff', 'HEAD').encode()).hexdigest(),
                    cprofile=use_cprofile, scope='runtime.update only; setup/reports excluded',
                    notes='Inclusive times overlap. Exclusive times partition timed update work. Instrumented timings include wrapper overhead; use plain runner for speedups.')
        (out / 'economy-phases.json').write_text(json.dumps(data, indent=2))


def main(argv=None):
    parser=argparse.ArgumentParser(add_help=False)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--cprofile',action='store_true')
    modes.add_argument('--plain',action='store_true',help='no timing wrappers')
    caches=parser.add_mutually_exclusive_group()
    caches.add_argument('--world-cache',type=Path)
    caches.add_argument('--write-world-cache',type=Path)
    options,args=parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    parsed = runner.parse_args(args)
    if parsed.output is None:
        raise ValueError('An explicit new --output directory is required')
    original = runner.run_workday
    build=runner.build_city
    # Cache only the initial map, before population or transport is constructed.
    # Loading it is setup work, outside update timers, for both variants.
    if options.world_cache or options.write_world_cache:
        from persistence import world_to_dict,world_from_dict
        def cached_build(*a,**kw):
            if options.world_cache:
                data=json.loads(options.world_cache.read_text())
                if data['world'].get('gameplay') is not None:
                    raise ValueError('Expected an unpopulated map cache')
                city=world_from_dict(data['world']).city_map
                return city,None,data['source']
            city,extra,source=build(*a,**kw)
            data=dict(source=source,world=world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1))
            with options.write_world_cache.open('x') as stream:
                json.dump(data,stream)
            return city,extra,source
        runner.build_city=cached_build
    if not options.plain:
        runner.run_workday = lambda runtime, **kwargs: profile_run(runtime, original, parsed.output, options.cprofile, **kwargs)
    try:
        return runner.main(args)
    finally:
        runner.run_workday = original
        runner.build_city=build


if __name__ == '__main__':
    raise SystemExit(main())
