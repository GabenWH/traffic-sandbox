# Arcata traffic scale test

Run status: **complete**. Reached the 5 updates/s threshold at 341.1 simulated seconds (4.94 FPS rolling). The spawn cap was then held at 920.

## Result

- Simulated time: 900.0 / 900 seconds (18,000 updates at 0.05 seconds each).
- Concurrent cars at the threshold: approximately 460; its 5-second time-series bin averaged 460.44 and peaked at 461 (the exact threshold-frame count was not retained).
- Peak active test cars: 726; active at end: 726.
- Total spawned / completed: 1,070 / 344.
- Target cap at end: 920; ramp: +40 every 15 simulated seconds from 40.
- Measured update FPS uses the rolling mean wall time of 20 simulator updates; the threshold is 200 ms/update.
- Directed portal routes cached before timing: 30; route setup excluded from the FPS result (6.90 seconds).
- Host: AMD EPYC 9V74 80-Core Processor (9 logical CPUs), Linux-6.18.55-x86_64-with-glibc2.39, Python 3.12.14.
- Benchmark wall time: 3471.2 seconds.

## Network

- 681 clipped OSM ways, 1,181 simulation road segments, 971 junctions.
- 88.4 miles of road centerline; 50 city-boundary portals available, 16 selected.
- OSM snapshot: 2026-06-01T08:52:28Z; boundary relation: 112123 (Arcata).

## Update phase timings

These are profiler samples from the final 600 frames (up to the final 30 simulated seconds). Values are milliseconds.

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 319.458 | 411.076 | 454.978 | 536.383 |
| `spawn` | 10.062 | 86.950 | 136.128 | 193.772 |
| `snapshot` | 45.224 | 56.747 | 102.257 | 138.876 |
| `observe` | 23.795 | 29.011 | 34.555 | 46.236 |
| `intent_generation` | 98.343 | 116.019 | 156.621 | 210.779 |
| `conflict_resolution` | 4.458 | 5.048 | 58.028 | 70.249 |
| `movement_apply` | 33.766 | 38.365 | 48.536 | 56.609 |
| `occupancy_rebuild` | 103.436 | 120.874 | 151.978 | 199.037 |

## Method and limits

The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. The target car cap increases on the configured schedule until the rolling threshold is crossed, then remains fixed while the run continues to 900 simulated seconds.

The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.

© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).
