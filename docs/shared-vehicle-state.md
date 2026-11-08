# Production shared vehicle state

`RoadVehicleSimulation` now always uses live C++ vehicle and brain fields.
`native_output_mode='shared'` remains accepted for explicit callers;
`native_output_mode='copy'` raises a migration error. There is no eager vehicle
mirror or copy-mode runtime branch. Owned `NativeTrafficEngine.snapshot()` values
remain available for diagnostics and independent reference comparisons.

Every actor imported from a save or admitted through the traffic APIs gets edit
ownership callbacks. Writes first materialize the current native state, then
invalidate the backend for reimport. Completion, removal and engine close detach
views before native storage is released. Road rebuilds continue using the existing
transport rebind behavior. Generated test-traffic route endpoints can now be saved
and resolved against a newly loaded city's intersection IDs.

The `completion_views` profiler phase replaces `vehicle_state_sync`: it retrieves
completion events and materializes completed actors, rather than copying the fleet.
The C++ movement algorithms and engine.cpp are unchanged (1,282 lines).

## Reproduction

Fresh single runs on a Ryzen 5 5600 with system Python 3.14, diagnostic timers
enabled and rendering excluded. Visual runs and full-suite verification were separate.
The runs are not counterbalanced trials and do not establish a causal speedup.
Raw dense results are in `benchmarks/performance-2026-11-07/shared-production-dense.json`;
Arcata summaries and interval quantiles are in `shared-production-arcata.json`.

| Dense workload | Mean | p95 | p99 | Maximum | Mean active | Sampled moving | Sampled mph | Completed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Packed roads | 0.534 ms | 0.661 | 0.755 | 1.835 | 1,000 | 1,000 | 22.442 | 0 |
| Signalized crossing | 1.131 ms | 1.863 | 2.133 | 3.876 | 998.331 | 892.5 | 6.800 | 20 |

Five-second warmup then 300 measured seconds at dt=0.05. Native movement averaged
0.454 / 1.007 ms, completion handling 0.003 / 0.004 ms. Counts and speeds match
the earlier recorded sampled workload outcomes; this is not exhaustive state or
collision equivalence. Moving means speed above 1 ft/s, sampled every five seconds.

| Arcata workload | All-tick mean | Maximum | Ticks >50 ms | Final active road vehicles | Departures | At work |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No buses | 0.650 ms | 419.818 ms | 1 | 62 | 3,368 | 1,241 |
| Twelve buses | 0.813 ms | 423.885 ms | 1 | 72 | 3,368 | 1,239 |

16,000 residents, 8,000 workers, 1,000 household cars, seed 42, 07:00–08:25,
102,000 ticks. Most cars are parked. Arcata's runner records p95/p99 per interval,
not whole-run quantiles; the artifact retains those interval values. It does not
record moving counts, vehicle speeds or vehicle route completions. Ordinary
profiling samples one tick in 17 and excludes ticks at or above 50 ms; all-tick
summary means/maxima above retain pauses. Wrappers remain installed on inactive
clock ticks. Neither workload establishes the 0.20 ms goal or 500,000-car capacity.

## Visual inspection

Run the same Arcata scenario with a live diagnostic map:

```bash
python tools/watch_arcata_commute.py --hours 1.4166666666666667 --start-hour 7 \
  --population 16000 --cars 1000 --seed 42 --stack-every 0 --report-every 300 \
  --with-buses --output /tmp/arcata-visual-new
```

The viewer shows preparation progress, then live positions. Drag to pan and use
the wheel to zoom. Zoom preserves the location under the pointer after panning,
which fixes the map sliding sideways. The final frame stays open for inspection.
Visual runs include snapshot collection and must not be used as benchmark results.

## Verification

The complete `python -m unittest discover -s tests -v` suite passed: 869 tests,
including real Tk/Panda3D window tests with desktop access. Verification used an
isolated Python 3.14 environment with the requirements-compatible Panda3D 1.10.16
wheel because the machine's system package could not load its OpenEXR dependency.
The existing 3D create/reset test was corrected to account for the default
land-port road; its original assertion failed on the untouched baseline as well.

An independent code review identified restored-actor ownership and an outdated
benchmark caller. Both received reproducing regression tests and fixes. Coverage
includes live field reads, Python-reference trajectory comparisons, completion and
removal, retained brains, brain replacement after save/load, length edits, rebuilds,
owned diagnostic snapshots, renderer consumption and cursor-anchored zoom.
