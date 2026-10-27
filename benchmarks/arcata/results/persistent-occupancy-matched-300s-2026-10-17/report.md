# Arcata traffic scale test

Run status: **complete**. Did not reach 5 updates/s in 300 simulated seconds. The highest observed cap was 200, with 200 active cars.

## Result

- Simulated time: 300.0 / 300 seconds (6,000 updates at 0.05 seconds each).
- Peak active test cars: 200; active at end: 200.
- Total spawned / completed: 213 / 13.
- Target cap at end: 200; schedule: 100 cars for 150s, then 200 cars for 150s.
- Measured update FPS uses the rolling mean wall time of 20 simulator updates; the threshold is 200 ms/update.
- Directed portal routes cached before timing: 30; route setup excluded from the FPS result (7.42 seconds).
- Host: INTEL(R) XEON(R) PLATINUM 8573C (9 logical CPUs), Linux-6.18.55-x86_64-with-glibc2.39, Python 3.12.14.
- Benchmark wall time: 121.6 seconds.

## Network

- 681 clipped OSM ways, 1,181 simulation road segments, 971 junctions.
- 88.4 miles of road centerline; 50 city-boundary portals available, 16 selected.
- OSM snapshot: 2026-06-01T08:52:28Z; boundary relation: 112123 (Arcata).

## Update phase timings

These are profiler samples across the full 300-second run. Values are milliseconds.

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 19.802 | 45.262 | 64.939 | 146.237 |
| `spawn` | 1.413 | 1.609 | 41.468 | 86.794 |
| `snapshot` | 1.354 | 3.616 | 5.318 | 18.357 |
| `observe` | 2.126 | 5.110 | 7.428 | 66.590 |
| `intent_generation` | 7.780 | 17.286 | 23.172 | 113.060 |
| `conflict_resolution` | 0.891 | 2.528 | 4.269 | 60.950 |
| `movement_apply` | 5.060 | 13.189 | 18.817 | 101.249 |
| `occupancy_rebuild` | 1.148 | 3.195 | 4.883 | 57.239 |

## Internal phase timings across all stages

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 1.409 | 3.765 | 6.058 | 36.634 |
| `intent_chain_check` | 0.153 | 0.303 | 1.589 | 84.036 |
| `intent_control_claim_lookup` | 0.286 | 0.745 | 2.377 | 6.052 |
| `intent_control_inside_scan` | 0.468 | 1.474 | 3.031 | 18.776 |
| `intent_control_state` | 0.914 | 2.662 | 4.209 | 19.012 |
| `intent_control_stop_distance` | 0.085 | 0.153 | 1.017 | 4.106 |
| `intent_exit_gap` | 0.898 | 2.708 | 4.602 | 30.902 |
| `intent_generation` | 7.780 | 17.286 | 23.172 | 113.060 |
| `intent_leader_lookup` | 0.613 | 1.841 | 3.535 | 8.902 |
| `intent_merge_observation` | 0.039 | 0.055 | 0.281 | 5.365 |
| `intent_packaging` | 0.470 | 1.522 | 3.354 | 9.645 |
| `intent_priority_query` | 0.884 | 2.643 | 4.659 | 51.742 |
| `intent_route_lookup` | 1.115 | 3.171 | 5.341 | 58.085 |
| `intent_speed_target` | 1.034 | 2.928 | 4.601 | 45.084 |
| `occupancy_bin_build` | 0.123 | 0.248 | 1.441 | 4.340 |
| `occupancy_finalize` | 0.208 | 0.502 | 1.720 | 8.530 |
| `occupancy_position_lookup` | 0.279 | 0.824 | 2.310 | 6.489 |
| `occupancy_rebuild` | 1.148 | 3.195 | 4.883 | 57.239 |
| `occupancy_section_mapping` | 0.836 | 2.443 | 4.428 | 18.651 |

### Stage 1: cap 100 (0–150 simulated seconds)

Mean active cars: 84.96; profiler samples: 3000.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 10.703 | 24.246 | 40.720 | 146.237 |
| `spawn` | 1.121 | 1.254 | 29.841 | 86.794 |
| `snapshot` | 0.790 | 2.033 | 3.957 | 12.141 |
| `observe` | 1.229 | 3.028 | 5.203 | 44.066 |
| `intent_generation` | 4.466 | 9.473 | 13.588 | 113.060 |
| `conflict_resolution` | 0.530 | 1.302 | 2.822 | 60.950 |
| `movement_apply` | 1.878 | 4.878 | 7.500 | 84.468 |
| `occupancy_rebuild` | 0.668 | 1.741 | 3.465 | 34.507 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.843 | 2.190 | 4.128 | 36.634 |
| `intent_chain_check` | 0.065 | 0.123 | 0.600 | 3.647 |
| `intent_control_claim_lookup` | 0.169 | 0.319 | 1.417 | 5.599 |
| `intent_control_inside_scan` | 0.280 | 0.630 | 2.203 | 18.776 |
| `intent_control_state` | 0.542 | 1.428 | 3.005 | 19.012 |
| `intent_control_stop_distance` | 0.050 | 0.095 | 0.443 | 2.590 |
| `intent_exit_gap` | 0.539 | 1.471 | 3.530 | 30.903 |
| `intent_generation` | 4.466 | 9.473 | 13.588 | 113.060 |
| `intent_leader_lookup` | 0.374 | 0.910 | 2.409 | 6.931 |
| `intent_merge_observation` | 0.023 | 0.020 | 0.133 | 4.090 |
| `intent_packaging` | 0.275 | 0.672 | 2.247 | 4.862 |
| `intent_priority_query` | 0.423 | 0.984 | 2.744 | 51.742 |
| `intent_route_lookup` | 0.604 | 1.469 | 3.254 | 58.085 |
| `intent_speed_target` | 0.637 | 1.775 | 3.378 | 8.399 |
| `occupancy_bin_build` | 0.071 | 0.129 | 0.696 | 4.185 |
| `occupancy_finalize` | 0.132 | 0.255 | 1.275 | 5.115 |
| `occupancy_position_lookup` | 0.159 | 0.315 | 1.422 | 4.322 |
| `occupancy_rebuild` | 0.668 | 1.741 | 3.465 | 34.507 |
| `occupancy_section_mapping` | 0.475 | 1.299 | 2.984 | 10.036 |

### Stage 2: cap 200 (150–300 simulated seconds)

Mean active cars: 184.76; profiler samples: 3000.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 28.902 | 51.819 | 77.903 | 135.028 |
| `spawn` | 1.704 | 1.837 | 47.386 | 83.562 |
| `snapshot` | 1.918 | 4.225 | 6.225 | 18.357 |
| `observe` | 3.023 | 5.875 | 8.420 | 66.590 |
| `intent_generation` | 11.094 | 19.694 | 25.064 | 91.556 |
| `conflict_resolution` | 1.252 | 3.100 | 4.966 | 60.127 |
| `movement_apply` | 8.243 | 15.588 | 20.503 | 101.249 |
| `occupancy_rebuild` | 1.629 | 3.770 | 5.314 | 57.239 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 1.976 | 4.520 | 6.970 | 17.039 |
| `intent_chain_check` | 0.242 | 0.583 | 2.269 | 84.036 |
| `intent_control_claim_lookup` | 0.403 | 1.209 | 2.692 | 6.052 |
| `intent_control_inside_scan` | 0.656 | 1.886 | 3.446 | 7.902 |
| `intent_control_state` | 1.287 | 3.191 | 4.920 | 10.823 |
| `intent_control_stop_distance` | 0.119 | 0.214 | 1.355 | 4.106 |
| `intent_exit_gap` | 1.257 | 3.195 | 5.029 | 11.375 |
| `intent_generation` | 11.094 | 19.694 | 25.064 | 91.556 |
| `intent_leader_lookup` | 0.852 | 2.373 | 3.958 | 8.902 |
| `intent_merge_observation` | 0.054 | 0.072 | 0.630 | 5.365 |
| `intent_packaging` | 0.665 | 2.153 | 3.954 | 9.645 |
| `intent_priority_query` | 1.345 | 3.323 | 5.285 | 30.429 |
| `intent_route_lookup` | 1.627 | 3.918 | 6.406 | 13.517 |
| `intent_speed_target` | 1.431 | 3.586 | 5.473 | 45.084 |
| `occupancy_bin_build` | 0.174 | 0.402 | 1.781 | 4.340 |
| `occupancy_finalize` | 0.284 | 0.753 | 2.010 | 8.530 |
| `occupancy_position_lookup` | 0.398 | 1.262 | 2.696 | 6.489 |
| `occupancy_rebuild` | 1.629 | 3.770 | 5.314 | 57.239 |
| `occupancy_section_mapping` | 1.197 | 3.065 | 5.044 | 18.651 |


## Method and limits

The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. Target cap schedule: 100 cars for 150s, then 200 cars for 150s.

The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.

© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).
