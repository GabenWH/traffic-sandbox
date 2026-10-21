# Arcata traffic scale test

Run status: **complete**. Did not reach 5 updates/s in 5 simulated seconds. The highest observed cap was 40, with 14 active cars.

## Result

- Simulated time: 5.0 / 5 seconds (100 updates at 0.05 seconds each).
- Peak active test cars: 14; active at end: 14.
- Total spawned / completed: 14 / 0.
- Target cap at end: 40; ramp: +40 every 15 simulated seconds from 40.
- Measured update FPS uses the rolling mean wall time of 20 simulator updates; the threshold is 200 ms/update.
- Directed portal routes cached before timing: 30; route setup excluded from the FPS result (6.47 seconds).
- Host: AMD EPYC 9V74 80-Core Processor (9 logical CPUs), Linux-6.18.55-x86_64-with-glibc2.39, Python 3.12.14.
- Benchmark wall time: 0.3 seconds.

## Network

- 681 clipped OSM ways, 1,181 simulation road segments, 971 junctions.
- 88.4 miles of road centerline; 50 city-boundary portals available, 16 selected.
- OSM snapshot: 2026-06-01T08:52:28Z; boundary relation: 112123 (Arcata).

## Update phase timings

These are profiler samples from the final 600 frames (up to the final 30 simulated seconds). Values are milliseconds.

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 3.045 | 19.323 | 25.286 | 25.824 |
| `spawn` | 1.505 | 17.265 | 22.463 | 22.547 |
| `snapshot` | 0.124 | 0.235 | 0.420 | 0.749 |
| `observe` | 0.083 | 0.130 | 0.203 | 0.354 |
| `intent_generation` | 0.722 | 1.211 | 1.322 | 1.400 |
| `conflict_resolution` | 0.042 | 0.065 | 0.181 | 0.258 |
| `movement_apply` | 0.049 | 0.094 | 0.135 | 0.177 |
| `occupancy_rebuild` | 0.514 | 0.842 | 1.034 | 1.081 |

## Method and limits

The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. The target car cap increases on the configured schedule until the rolling threshold is crossed, then remains fixed while the run continues to 900 simulated seconds.

The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.

© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).
