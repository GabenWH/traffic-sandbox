"""Count direct calls into Python's occupancy index during a crossing run."""
from collections import Counter
import inspect, json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.benchmark_native_spawning import make_city
from traffic_occupancy import TrafficOccupancyIndex
from traffic_testbed import RoadVehicleSimulation

METHODS = ('rebuild', 'publish_changes', 'is_current', 'gap_from', 'lead_from', 'lead_gap', 'lead_car_gap')
original = {name: getattr(TrafficOccupancyIndex, name) for name in METHODS}
counts = Counter()
def wrapper(name, fn):
    def traced(self, *args, **kwargs):
        frame = inspect.currentframe().f_back
        filename = Path(frame.f_code.co_filename)
        try: filename = filename.relative_to(ROOT)
        except ValueError: pass
        counts[(name, str(filename), frame.f_code.co_name, frame.f_lineno)] += 1
        return fn(self, *args, **kwargs)
    return traced
for name, fn in original.items(): setattr(TrafficOccupancyIndex, name, wrapper(name, fn))
results = {}
for mode in ('cpp', 'reference_data_first'):
    city, controllers = make_city('signalized-crossing', 42)
    if mode == 'cpp':
        factory, selection = RoadVehicleSimulation, 'cpp'
    else:
        from tests.reference_traffic import RoadVehicleSimulation as factory
        selection = 'data_first'
    sim = factory(update_mode=selection, rng=random.Random(42), spawn_interval=.8, max_cars=60)
    sim.signal_controllers.update(controllers)
    for junction in city.cul_de_sacs: sim.toggle_junction(junction)
    counts.clear()
    peak = 0
    for _ in range(600):
        sim.update(city, .05)
        peak = max(peak, len(sim.cars))
    results[mode] = {'ticks': 600, 'peak_cars': peak, 'calls': [
        {'method': method, 'file': filename, 'function': function, 'line': line, 'count': count}
        for (method, filename, function, line), count in counts.most_common()]}
    sim._discard_native()
print(json.dumps(results, indent=2))
