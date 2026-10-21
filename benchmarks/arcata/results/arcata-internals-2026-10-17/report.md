# Arcata traffic scale test

Run status: **complete**. Did not reach 5 updates/s in 300 simulated seconds. The highest observed cap was 200, with 200 active cars.

## Result

- Simulated time: 300.0 / 300 seconds (6,000 updates at 0.05 seconds each).
- Peak active test cars: 200; active at end: 200.
- Total spawned / completed: 213 / 13.
- Target cap at end: 200; schedule: 100 cars for 150s, then 200 cars for 150s.
- Measured update FPS uses the rolling mean wall time of 20 simulator updates; the threshold is 200 ms/update.
- Directed portal routes cached before timing: 30; route setup excluded from the FPS result (6.42 seconds).
- Host: AMD EPYC 9V74 80-Core Processor (9 logical CPUs), Linux-6.18.55-x86_64-with-glibc2.39, Python 3.12.14.
- Benchmark wall time: 188.5 seconds.

## Network

- 681 clipped OSM ways, 1,181 simulation road segments, 971 junctions.
- 88.4 miles of road centerline; 50 city-boundary portals available, 16 selected.
- OSM snapshot: 2026-06-01T08:52:28Z; boundary relation: 112123 (Arcata).

## Update phase timings

These are profiler samples across the full 300-second run. Values are milliseconds.

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 31.053 | 58.275 | 74.219 | 151.240 |
| `spawn` | 0.904 | 0.189 | 26.504 | 34.250 |
| `snapshot` | 2.850 | 6.364 | 8.728 | 44.981 |
| `observe` | 1.408 | 3.212 | 4.702 | 18.345 |
| `intent_generation` | 11.405 | 19.930 | 25.545 | 78.650 |
| `conflict_resolution` | 0.542 | 0.870 | 1.081 | 44.162 |
| `movement_apply` | 3.301 | 7.708 | 9.140 | 21.102 |
| `occupancy_rebuild` | 10.616 | 19.675 | 23.802 | 74.609 |

## Internal phase timings across all stages

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.728 | 1.185 | 1.518 | 8.208 |
| `intent_chain_check` | 0.059 | 0.113 | 0.160 | 1.240 |
| `intent_control_state` | 5.891 | 9.695 | 12.443 | 41.008 |
| `intent_exit_gap` | 1.679 | 3.719 | 4.745 | 16.793 |
| `intent_generation` | 11.405 | 19.930 | 25.545 | 78.650 |
| `intent_leader_lookup` | 1.027 | 1.638 | 2.035 | 31.322 |
| `intent_merge_observation` | 0.018 | 0.027 | 0.045 | 0.882 |
| `intent_packaging` | 0.248 | 0.396 | 0.525 | 4.692 |
| `intent_priority_query` | 0.555 | 1.181 | 1.449 | 33.921 |
| `intent_route_lookup` | 0.575 | 1.090 | 1.491 | 63.384 |
| `intent_speed_target` | 0.495 | 0.816 | 1.006 | 2.802 |
| `occupancy_bin_build` | 0.259 | 0.410 | 0.560 | 45.620 |
| `occupancy_finalize` | 0.097 | 0.212 | 0.297 | 2.989 |
| `occupancy_position_lookup` | 0.756 | 1.950 | 2.588 | 15.970 |
| `occupancy_rebuild` | 10.616 | 19.675 | 23.802 | 74.609 |
| `occupancy_section_mapping` | 3.870 | 7.675 | 9.979 | 64.430 |

### Stage 1: cap 100 (0–150 simulated seconds)

Mean active cars: 84.96; profiler samples: 3000.

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.465 | 0.658 | 0.922 | 4.411 |
| `intent_chain_check` | 0.029 | 0.042 | 0.086 | 0.443 |
| `intent_control_state` | 3.599 | 4.849 | 6.242 | 39.396 |
| `intent_exit_gap` | 0.826 | 1.305 | 1.795 | 4.048 |
| `intent_generation` | 6.653 | 9.089 | 11.604 | 45.972 |
| `intent_leader_lookup` | 0.660 | 0.906 | 1.166 | 31.322 |
| `intent_merge_observation` | 0.012 | 0.014 | 0.032 | 0.882 |
| `intent_packaging` | 0.157 | 0.224 | 0.327 | 2.212 |
| `intent_priority_query` | 0.227 | 0.341 | 0.495 | 5.310 |
| `intent_route_lookup` | 0.287 | 0.421 | 0.562 | 2.630 |
| `intent_speed_target` | 0.307 | 0.439 | 0.571 | 2.617 |
| `occupancy_bin_build` | 0.169 | 0.318 | 0.439 | 36.294 |
| `occupancy_finalize` | 0.051 | 0.096 | 0.146 | 2.989 |
| `occupancy_position_lookup` | 0.233 | 0.456 | 0.613 | 3.319 |
| `occupancy_rebuild` | 5.566 | 8.039 | 9.999 | 44.353 |
| `occupancy_section_mapping` | 1.860 | 3.039 | 3.913 | 7.534 |

### Stage 2: cap 200 (150–300 simulated seconds)

Mean active cars: 184.76; profiler samples: 3000.

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.990 | 1.271 | 1.690 | 8.208 |
| `intent_chain_check` | 0.088 | 0.124 | 0.185 | 1.240 |
| `intent_control_state` | 8.184 | 10.408 | 13.864 | 41.008 |
| `intent_exit_gap` | 2.532 | 4.147 | 5.719 | 16.793 |
| `intent_generation` | 16.156 | 21.408 | 28.343 | 78.650 |
| `intent_leader_lookup` | 1.394 | 1.758 | 2.583 | 14.097 |
| `intent_merge_observation` | 0.024 | 0.029 | 0.052 | 0.406 |
| `intent_packaging` | 0.339 | 0.431 | 0.580 | 4.692 |
| `intent_priority_query` | 0.884 | 1.269 | 1.618 | 33.921 |
| `intent_route_lookup` | 0.863 | 1.218 | 1.662 | 63.384 |
| `intent_speed_target` | 0.683 | 0.873 | 1.164 | 2.802 |
| `occupancy_bin_build` | 0.349 | 0.453 | 0.628 | 45.620 |
| `occupancy_finalize` | 0.143 | 0.239 | 0.344 | 2.348 |
| `occupancy_position_lookup` | 1.280 | 2.159 | 2.946 | 15.969 |
| `occupancy_rebuild` | 15.667 | 20.971 | 27.776 | 74.609 |
| `occupancy_section_mapping` | 5.880 | 8.492 | 11.754 | 64.430 |


## Method and limits

The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. Target cap schedule: 100 cars for 150s, then 200 cars for 150s.

The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.

© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).
