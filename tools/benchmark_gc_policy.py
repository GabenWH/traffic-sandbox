#!/usr/bin/env python3
"""Instrument a workday run; configure GC with TRAFFIC_GC_THRESHOLDS=a,b,c."""
import gc
import json
import os
from collections import Counter
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import run_arcata_city_workday as runner

thresholds = tuple(map(int, os.environ.get('TRAFFIC_GC_THRESHOLDS', '700,10,10').split(',')))
if len(thresholds) != 3 or any(x < 1 for x in thresholds):
    raise ValueError('TRAFFIC_GC_THRESHOLDS must contain three positive integers')
gc.set_threshold(*thresholds)
out = Path(sys.argv[sys.argv.index('--output') + 1])
original = runner.run_workday

def instrument(runtime, **kwargs):
    events, active, slow = [], {}, []
    start = time.perf_counter()
    def snapshot():
        counts = Counter(f'{type(o).__module__}.{type(o).__qualname__}' for o in gc.get_objects())
        return {'tracked_objects': sum(counts.values()), 'top_types': counts.most_common(30),
                'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'gc_counts': gc.get_count()}
    def callback(phase, info):
        now = time.perf_counter() - start
        gen = info['generation']
        if phase == 'start': active[gen] = now
        elif gen in active: events.append([gen, active.pop(gen), now, info['collected'], info['uncollectable']])
    initial = snapshot()
    update = runtime.update
    def timed(dt):
        begin = time.perf_counter() - start
        try: return update(dt)
        finally:
            end = time.perf_counter() - start
            if end-begin > .05: slow.append([runtime.time-dt, begin, end])
    gc.callbacks.append(callback)
    runtime.update = timed
    try:
        return original(runtime, **kwargs)
    finally:
        runtime.update = update
        gc.callbacks.remove(callback)
        final = snapshot()
        (out/'gc_policy.json').write_text(json.dumps({'thresholds': thresholds, 'initial': initial, 'final': final,
            'gc_columns': ['generation','start_s','end_s','collected','uncollectable'], 'collections': events,
            'slow_tick_columns': ['sim_start','start_s','end_s'], 'slow_ticks': slow}, indent=2))

runner.run_workday = instrument
raise SystemExit(runner.main(sys.argv[1:]))
