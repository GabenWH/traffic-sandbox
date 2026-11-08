# Traffic performance handoff — November 7, 2026

Repository: GabenWH/traffic-sandbox
Branch: fix/parking-cache-preference-scaffold

## Current runtime after shared-state promotion

Shared state is now the sole application path. Copy requests are rejected;
eager vehicle/brain mirroring and the copy/shared runtime comparison have been
removed. Use `python tools/benchmark_dense_vehicles.py --seconds 300 --output
/tmp/dense-shared-new.json` for current measurements. The results and commands
below are historical evidence for commit 091eab9 and should be reproduced from
that commit when a copy-mode comparison is needed. Current coverage includes
live field reads, retained completions, removal, brain replacement, engine close,
road rebuilds, transport save/load and actual scene position consumption.
See [production shared state](shared-vehicle-state.md) for the migration,
fresh measurements, validation and visual viewer command.

## Goal and current changes

Reduce simulation update CPU toward 0.20 ms, measuring the actual active workload.
Do not equate population, owned cars, active vehicles and moving vehicles.

Current local work made NativeRoadSimulation.update/configure readable; replaced
per-step connection-control scans with edit notifications; cached unchanged signal
permissions, speed and tracing settings; avoided resending unchanged RNG state;
and skipped Python RNG tuple reconstruction when native state bytes are unchanged.
This is not complete native RNG ownership: the raw state is still read each step,
and source timers/counts still synchronize. Preserve external Python RNG draws,
reseed/gaussian state, save/load, and engine recreation semantics.

Parking searches the destination lot, then overflow within 50 m before bus fallback.
Map geometry is feet: 50 / 0.3048 feet. Real walking access and space fit are checked.
If no viable bus trip exists, the older wider parking/walking recovery remains.
Bus-only fallback must traverse a real ride edge; boarding/alighting at the same
stop cannot satisfy it. The car remains physically parked and is retrieved later.

The benchmark can add synthetic bus service: 3 lines, 10 connected stops, 12 buses,
60 seats per bus, 300-second planned headway. Stops are chosen from the road component
with the most round-trip-accessible building sites, then spread geographically.
This is not a real timetable or demand-designed network. Setup uses the existing
native route finder. Riders were sparse in the measured morning interval.

## Test A: Arcata population / commute workload

16,000 residents, 8,000 workers, 1,000 household cars, seed 42, 07:00–08:25,
102,000 updates at dt=0.05 s. Cars are mostly parked; prior no-bus run ended with
62 active road vehicles. Bus run ended with 72 active road vehicles including buses.
No rendering. Full update timings include gameplay and diagnostic overhead.

Run from the repository root with a fresh output directory:

```bash
python tools/profile_ordinary_ticks.py --hours 1.4166666666666667 --start-hour 7 --population 16000 --cars 1000 --seed 42 --stack-every 0 --report-every 300 --output /tmp/arcata-no-buses
python tools/profile_ordinary_ticks.py --hours 1.4166666666666667 --start-hour 7 --population 16000 --cars 1000 --seed 42 --stack-every 0 --report-every 300 --with-buses --output /tmp/arcata-with-buses
```

The profiler times one tick in 17 and reports exclusive costs in
ordinary_tick_profile.json. It excludes ticks >=50 ms from its ordinary-tick
averages. baseline_mean_ms means timing wrappers installed but detailed phase
clocks inactive, NOT completely uninstrumented execution. summary.json includes
all ticks and pauses; metrics.jsonl contains interval statistics. Detailed timing
has measurable overhead. Do not add nested inclusive times together.
For an uninstrumented run, substitute tools/run_arcata_city_workday.py.

Historical measured means (single runs, same morning interval):
- Before configuration cleanup: 1.548 ms all ticks; ordinary inactive-clock ticks 1.534 ms.
- Before RNG skip, detailed transit profile: 0.590 ms all ticks, 0.575 ms ordinary.
- After RNG skip: 0.544 ms all ticks, 0.527 ms ordinary; RNG/source publication
  0.0624 -> 0.0067 ms per sampled ordinary tick.
- With buses and the new parking order: 0.708 ms all ticks; max 378.6 ms; three
  ticks >50 ms. This changes the workload and is not an isolated speedup comparison.
- Bus journey planning rose from ~0.041 to ~0.120 ms exclusive per sampled tick.
  The bus routing graph is rebuilt per query; no graph-cache optimization was added.

## Test B: dense active vehicles

```bash
python tools/benchmark_dense_vehicles.py --mode copy --seconds 300 --output /tmp/dense-copy.json
python tools/benchmark_dense_vehicles.py --mode shared --seconds 300 --output /tmp/dense-shared.json
```

5-second warmup followed by 300 measured seconds at dt=0.05 s (6,000 ticks).
Traffic-only Python/native updates, diagnostic timers enabled; no city economy,
parking, buses, pedestrians, renderer or display reads. Sources are disabled:
vehicles are a fixed initial fleet, not replenished as they finish.

- Packed roads: 20 separate, parallel 24,000-foot roads; 50 cars per road, initially
  spaced 36 feet apart. All 1,000 remained active and moving; average 22.44 mph.
  Long routes intentionally avoid completions during measurement.
- Signalized crossing: the existing signalized-crossing builder and fixed-fleet
  initializer; 250 and 1,000 initial cars in copy mode, 1,000 in shared mode.
  Approach lengths grow with fleet size to avoid placing cars before route start.
  Do not compare completed-route counts across fleet sizes as intersection throughput.
- Moving means speed >1 ft/s, including creeping; speed/flow sampled every five
  simulated seconds outside the timed update. Mean active count uses every tick.

Measured mean / p99 tick time:

| Scenario | Copy | Shared |
| --- | --- | --- |
| 1,000 packed-road cars | 1.925 / 2.493 ms | 0.521 / 0.785 ms |
| 1,000 signal-queue cars | 2.993 / 4.649 ms | 1.339 / 2.585 ms |

Signal case averaged 998.3 active and 892.5 moving cars, 6.80 mph; 980 remained and
20 finished measured routes. No measured dense-test tick exceeded 50 ms.
Vehicle state copies cost ~1.37–1.55 ms; shared result handling ~0.002–0.003 ms.
Shared native movement was ~0.463 ms on packed roads and ~1.241 ms at signals.

These are single runs, copy before shared, not counterbalanced repeated trials.
Sampled active/moving/stopped counts, completions and mean speeds matched between
modes. This is not an exhaustive collision check or full-state equivalence proof.
Shared state is already supported but remains opt-in; no default was switched.
The 0.20 ms goal for 1,000 active cars requires native optimization as well.
No evidence here establishes 500,000-car capacity.

## Source and evidence

Read native_spawning.py, native_shared.py, native_traffic.py, models.py,
traffic_testbed.py, parking_trips.py, transit.py, tools/arcata_buses.py and
native/traffic/engine.cpp. Keep the existing C++ human-readable; engine.cpp is
1,282 lines and the user's limit is under 2,000 lines for that engine file.

Committed original observations:
- benchmarks/performance-2026-11-07/dense-vehicles.json
- benchmarks/performance-2026-11-07/arcata-summary.json

## Verification and next investigation

```bash
PYTHONPATH=.:tests python -m unittest test_native_configuration_changes test_native_spawning test_native_spawn_admission test_native_spawn_scenarios test_arcata_benchmark_buses test_blocked_driver_bus test_lazy_parking_options test_parking_fallback test_cold_parking_wait_budget test_transit_transfers test_parking_persistence -q
```

Inspect evidence before optimizing. The dense result points first to eliminating
unneeded eager vehicle mirrors using the existing shared mode. Verify view lifetime,
manual edits, road rebuilds, completion handling, save/load and actual display reads
before making it the default. Separately inspect native arbitration in the congested
signal case. For bus planning, cache reusable network/stop-access work and measure
actual mode substitution before adding more service. Report mean/p95/p99/max,
active/moving counts and traffic outcomes together; retain GC/cold-start pauses.
