# Arcata traffic scale test

Run status: **complete**. Did not reach 5 updates/s in 60 simulated seconds. The highest observed cap was 200, with 114 active cars.

## Result

- Simulated time: 60.0 / 60 seconds (1,200 updates at 0.05 seconds each).
- Peak active test cars: 114; active at end: 114.
- Total spawned / completed: 114 / 0.
- Target cap at end: 200; schedule: 100 cars for 30s, then 200 cars for 30s.
- Measured update FPS uses the rolling mean wall time of 20 simulator updates; the threshold is 200 ms/update.
- Directed portal routes cached before timing: 30; route setup excluded from the FPS result (6.67 seconds).
- Host: AMD EPYC 9V74 80-Core Processor (9 logical CPUs), Linux-6.18.55-x86_64-with-glibc2.39, Python 3.12.14.
- Benchmark wall time: 9.2 seconds.

## Network

- 681 clipped OSM ways, 1,181 simulation road segments, 971 junctions.
- 88.4 miles of road centerline; 50 city-boundary portals available, 16 selected.
- OSM snapshot: 2026-06-01T08:52:28Z; boundary relation: 112123 (Arcata).

## Update phase timings

These are profiler samples across the full 60-second run. Values are milliseconds.

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 7.610 | 29.517 | 38.311 | 66.169 |
| `spawn` | 2.352 | 23.117 | 26.879 | 52.065 |
| `snapshot` | 0.925 | 2.119 | 3.560 | 5.157 |
| `observe` | 0.500 | 0.973 | 1.530 | 3.283 |
| `intent_generation` | 2.334 | 4.328 | 5.417 | 12.087 |
| `conflict_resolution` | 0.234 | 0.405 | 0.534 | 1.252 |
| `movement_apply` | 0.471 | 1.002 | 1.233 | 2.531 |
| `occupancy_rebuild` | 0.782 | 1.574 | 2.517 | 39.221 |

## Internal phase timings across all stages

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.334 | 0.573 | 0.737 | 2.942 |
| `intent_chain_check` | 0.018 | 0.033 | 0.070 | 0.243 |
| `intent_control_claim_lookup` | 0.067 | 0.114 | 0.164 | 0.581 |
| `intent_control_inside_scan` | 0.086 | 0.150 | 0.213 | 0.393 |
| `intent_control_state` | 0.189 | 0.326 | 0.419 | 0.787 |
| `intent_control_stop_distance` | 0.018 | 0.030 | 0.048 | 0.122 |
| `intent_exit_gap` | 0.529 | 1.018 | 1.386 | 6.033 |
| `intent_generation` | 2.334 | 4.328 | 5.417 | 12.087 |
| `intent_leader_lookup` | 0.489 | 0.879 | 1.047 | 2.988 |
| `intent_merge_observation` | 0.008 | 0.013 | 0.015 | 0.064 |
| `intent_packaging` | 0.117 | 0.210 | 0.291 | 0.421 |
| `intent_priority_query` | 0.128 | 0.249 | 0.314 | 0.502 |
| `intent_route_lookup` | 0.186 | 0.335 | 0.427 | 2.107 |
| `intent_speed_target` | 0.282 | 0.562 | 0.856 | 1.854 |
| `occupancy_bin_build` | 0.129 | 0.265 | 0.356 | 37.063 |
| `occupancy_finalize` | 0.025 | 0.053 | 0.088 | 0.317 |
| `occupancy_position_lookup` | 0.087 | 0.194 | 0.310 | 2.148 |
| `occupancy_rebuild` | 0.782 | 1.574 | 2.517 | 39.221 |
| `occupancy_section_mapping` | 1.120 | 2.372 | 3.465 | 6.763 |

### Stage 1: cap 100 (0–30 simulated seconds)

Mean active cars: 36.45; profiler samples: 600.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 4.878 | 25.240 | 29.987 | 32.790 |
| `spawn` | 2.118 | 21.842 | 25.337 | 27.886 |
| `snapshot` | 0.477 | 0.953 | 1.758 | 2.305 |
| `observe` | 0.275 | 0.494 | 0.624 | 2.635 |
| `intent_generation` | 1.276 | 2.310 | 2.556 | 5.247 |
| `conflict_resolution` | 0.141 | 0.257 | 0.337 | 0.462 |
| `movement_apply` | 0.211 | 0.428 | 0.525 | 1.323 |
| `occupancy_rebuild` | 0.372 | 0.675 | 0.870 | 2.199 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.198 | 0.344 | 0.422 | 2.942 |
| `intent_chain_check` | 0.010 | 0.016 | 0.067 | 0.165 |
| `intent_control_claim_lookup` | 0.039 | 0.065 | 0.109 | 0.314 |
| `intent_control_inside_scan` | 0.053 | 0.096 | 0.208 | 0.279 |
| `intent_control_state` | 0.114 | 0.205 | 0.297 | 0.443 |
| `intent_control_stop_distance` | 0.011 | 0.017 | 0.032 | 0.106 |
| `intent_exit_gap` | 0.268 | 0.522 | 0.614 | 0.666 |
| `intent_generation` | 1.276 | 2.310 | 2.556 | 5.247 |
| `intent_leader_lookup` | 0.264 | 0.495 | 0.569 | 0.732 |
| `intent_merge_observation` | 0.004 | 0.007 | 0.008 | 0.053 |
| `intent_packaging` | 0.069 | 0.122 | 0.210 | 0.307 |
| `intent_priority_query` | 0.067 | 0.121 | 0.189 | 0.502 |
| `intent_route_lookup` | 0.104 | 0.183 | 0.251 | 0.361 |
| `intent_speed_target` | 0.146 | 0.276 | 0.367 | 0.443 |
| `occupancy_bin_build` | 0.049 | 0.103 | 0.182 | 0.728 |
| `occupancy_finalize` | 0.014 | 0.023 | 0.046 | 0.180 |
| `occupancy_position_lookup` | 0.042 | 0.084 | 0.137 | 0.355 |
| `occupancy_rebuild` | 0.372 | 0.675 | 0.870 | 2.199 |
| `occupancy_section_mapping` | 0.568 | 1.102 | 1.520 | 2.310 |

### Stage 2: cap 200 (30–60 simulated seconds)

Mean active cars: 90.65; profiler samples: 600.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 10.342 | 33.936 | 41.924 | 66.169 |
| `spawn` | 2.585 | 25.096 | 28.454 | 52.065 |
| `snapshot` | 1.374 | 2.802 | 3.928 | 5.157 |
| `observe` | 0.726 | 1.094 | 1.784 | 3.283 |
| `intent_generation` | 3.391 | 4.729 | 6.629 | 12.087 |
| `conflict_resolution` | 0.328 | 0.444 | 0.577 | 1.252 |
| `movement_apply` | 0.732 | 1.107 | 1.327 | 2.531 |
| `occupancy_rebuild` | 1.192 | 1.887 | 3.044 | 39.221 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.470 | 0.640 | 0.900 | 2.433 |
| `intent_chain_check` | 0.025 | 0.037 | 0.070 | 0.243 |
| `intent_control_claim_lookup` | 0.094 | 0.126 | 0.186 | 0.581 |
| `intent_control_inside_scan` | 0.119 | 0.160 | 0.230 | 0.393 |
| `intent_control_state` | 0.264 | 0.358 | 0.435 | 0.787 |
| `intent_control_stop_distance` | 0.025 | 0.032 | 0.049 | 0.122 |
| `intent_exit_gap` | 0.791 | 1.147 | 1.919 | 6.033 |
| `intent_generation` | 3.391 | 4.729 | 6.629 | 12.087 |
| `intent_leader_lookup` | 0.715 | 0.956 | 1.098 | 2.988 |
| `intent_merge_observation` | 0.011 | 0.013 | 0.028 | 0.064 |
| `intent_packaging` | 0.165 | 0.244 | 0.340 | 0.421 |
| `intent_priority_query` | 0.189 | 0.273 | 0.327 | 0.436 |
| `intent_route_lookup` | 0.267 | 0.369 | 0.502 | 2.107 |
| `intent_speed_target` | 0.418 | 0.700 | 1.038 | 1.854 |
| `occupancy_bin_build` | 0.208 | 0.297 | 0.420 | 37.063 |
| `occupancy_finalize` | 0.035 | 0.068 | 0.106 | 0.317 |
| `occupancy_position_lookup` | 0.133 | 0.233 | 0.324 | 2.148 |
| `occupancy_rebuild` | 1.192 | 1.887 | 3.044 | 39.221 |
| `occupancy_section_mapping` | 1.672 | 2.829 | 4.175 | 6.763 |


## Method and limits

The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. Target cap schedule: 100 cars for 30s, then 200 cars for 30s.

The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.

© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).
