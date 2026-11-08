"""Run the Arcata commute with a live map; visual runs are not benchmarks."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import run_arcata_city_workday as runner

viewer = subprocess.Popen([sys.executable, str(ROOT / 'tools/arcata_workday_view.py')],
                          stdin=subprocess.PIPE, text=True, bufsize=1)

def send(message):
    if viewer.poll() is not None:
        return
    try:
        viewer.stdin.write(json.dumps(message) + '\n')
        viewer.stdin.flush()
    except BrokenPipeError:
        pass

build_city = runner.build_city
def visual_build_city(*args, **kwargs):
    progress = kwargs.get('building_progress')
    def report(record):
        send({'kind': 'progress', 'stage': record.get('stage', 'building map')})
        if progress:
            progress(record)
    kwargs['building_progress'] = report
    city, *rest = build_city(*args, **kwargs)
    buildings = [(b.parcel.x + b.parcel.width / 2, b.parcel.y + b.parcel.height / 2,
                  'home' if b.residents else 'work') for b in city.buildings]
    roads = [[[float(p[0]), float(p[1])] for p in r.centerline] for r in city.roads]
    send({'kind': 'map', 'roads': roads, 'buildings': buildings})
    send({'kind': 'progress', 'stage': 'preparing population and bus service'})
    return city, *rest

run_workday = runner.run_workday
def visual_workday(runtime, **kwargs):
    update = runtime.update
    last_frame = 0.0
    def visual_update(dt):
        nonlocal last_frame
        result = update(dt)
        if time.monotonic() - last_frame >= .5:
            full_report = runtime.report()
            report = {key: full_report[key] for key in ('population', 'at_home', 'at_work', 'commuting')}
            vehicles = [(c.position[0], c.position[1], 'bus' if c.id in runtime.transit.buses else 'car')
                        for c in runtime.transit.traffic.cars]
            send({'kind': 'snapshot', 'time': runtime.time, 'report': report, 'vehicles': vehicles})
            last_frame = time.monotonic()
        return result
    runtime.update = visual_update
    try:
        return run_workday(runtime, **kwargs)
    finally:
        runtime.update = update

runner.build_city = visual_build_city
runner.run_workday = visual_workday
try:
    raise SystemExit(runner.main())
finally:
    if viewer.stdin:
        viewer.stdin.close()
