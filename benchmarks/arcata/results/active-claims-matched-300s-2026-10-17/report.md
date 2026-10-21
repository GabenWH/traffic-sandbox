# Arcata traffic scale test

Run status: **complete**. Reached the 5 updates/s threshold at 229.5 simulated seconds with 200 active cars (4.46 FPS rolling); the requested cap stages continued.

## Result

- Simulated time: 300.0 / 300 seconds (6,000 updates at 0.05 seconds each).
- Peak active test cars: 200; active at end: 200.
- Total spawned / completed: 213 / 13.
- Target cap at end: 200; schedule: 100 cars for 150s, then 200 cars for 150s.
- Measured update FPS uses the rolling mean wall time of 20 simulator updates; the threshold is 200 ms/update.
- Directed portal routes cached before timing: 30; route setup excluded from the FPS result (5.39 seconds).
- Host: INTEL(R) XEON(R) PLATINUM 8573C (9 logical CPUs), Linux-6.18.55-x86_64-with-glibc2.39, Python 3.12.14.
- Benchmark wall time: 146.6 seconds.

## Network

- 681 clipped OSM ways, 1,181 simulation road segments, 971 junctions.
- 88.4 miles of road centerline; 50 city-boundary portals available, 16 selected.
- OSM snapshot: 2026-06-01T08:52:28Z; boundary relation: 112123 (Arcata).

## Update phase timings

These are profiler samples across the full 300-second run. Values are milliseconds.

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 23.910 | 36.728 | 83.475 | 1675.336 |
| `spawn` | 1.340 | 0.794 | 45.666 | 76.346 |
| `snapshot` | 3.541 | 5.080 | 8.445 | 549.675 |
| `observe` | 2.010 | 3.046 | 4.868 | 242.154 |
| `intent_generation` | 8.583 | 12.973 | 21.331 | 837.841 |
| `conflict_resolution` | 0.802 | 1.528 | 2.560 | 155.606 |
| `movement_apply` | 4.283 | 8.104 | 11.653 | 437.198 |
| `occupancy_rebuild` | 3.294 | 4.514 | 7.572 | 777.485 |

## Internal phase timings across all stages

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 1.150 | 2.177 | 3.703 | 163.898 |
| `intent_chain_check` | 0.130 | 0.188 | 0.625 | 223.897 |
| `intent_control_claim_lookup` | 0.225 | 0.493 | 1.238 | 10.500 |
| `intent_control_inside_scan` | 0.461 | 0.942 | 1.989 | 133.406 |
| `intent_control_state` | 0.805 | 1.546 | 3.031 | 144.217 |
| `intent_control_stop_distance` | 0.060 | 0.116 | 0.424 | 2.719 |
| `intent_exit_gap` | 1.919 | 3.136 | 4.997 | 305.229 |
| `intent_generation` | 8.583 | 12.973 | 21.331 | 837.841 |
| `intent_leader_lookup` | 1.441 | 2.529 | 3.942 | 326.859 |
| `intent_merge_observation` | 0.028 | 0.033 | 0.162 | 16.803 |
| `intent_packaging` | 0.362 | 0.829 | 1.559 | 11.287 |
| `intent_priority_query` | 0.743 | 1.380 | 2.358 | 165.187 |
| `intent_route_lookup` | 0.926 | 1.748 | 3.058 | 74.481 |
| `intent_speed_target` | 0.878 | 1.642 | 3.001 | 94.647 |
| `occupancy_bin_build` | 0.453 | 0.742 | 1.492 | 462.808 |
| `occupancy_finalize` | 0.091 | 0.165 | 0.650 | 14.040 |
| `occupancy_position_lookup` | 0.841 | 1.424 | 2.667 | 205.624 |
| `occupancy_rebuild` | 3.294 | 4.514 | 7.572 | 777.485 |
| `occupancy_section_mapping` | 4.347 | 6.309 | 10.120 | 793.265 |

### Stage 1: cap 100 (0–150 simulated seconds)

Mean active cars: 84.96; profiler samples: 3000.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 12.890 | 23.213 | 35.015 | 69.983 |
| `spawn` | 0.942 | 0.763 | 26.271 | 45.084 |
| `snapshot` | 1.839 | 3.485 | 4.733 | 9.950 |
| `observe` | 1.119 | 2.309 | 3.335 | 9.798 |
| `intent_generation` | 5.092 | 8.844 | 11.355 | 24.506 |
| `conflict_resolution` | 0.477 | 1.168 | 2.077 | 4.911 |
| `movement_apply` | 1.761 | 4.177 | 5.551 | 11.042 |
| `occupancy_rebuild` | 1.635 | 3.242 | 4.709 | 52.957 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.726 | 1.721 | 2.655 | 5.280 |
| `intent_chain_check` | 0.056 | 0.083 | 0.574 | 4.370 |
| `intent_control_claim_lookup` | 0.152 | 0.343 | 1.109 | 3.894 |
| `intent_control_inside_scan` | 0.228 | 0.574 | 1.273 | 13.731 |
| `intent_control_state` | 0.458 | 1.127 | 2.096 | 13.927 |
| `intent_control_stop_distance` | 0.040 | 0.063 | 0.265 | 2.719 |
| `intent_exit_gap` | 1.138 | 2.511 | 4.028 | 7.388 |
| `intent_generation` | 5.092 | 8.844 | 11.355 | 24.506 |
| `intent_leader_lookup` | 0.911 | 2.067 | 3.052 | 9.301 |
| `intent_merge_observation` | 0.018 | 0.016 | 0.097 | 0.894 |
| `intent_packaging` | 0.242 | 0.673 | 1.437 | 3.586 |
| `intent_priority_query` | 0.344 | 0.943 | 1.717 | 3.276 |
| `intent_route_lookup` | 0.508 | 1.297 | 2.197 | 5.478 |
| `intent_speed_target` | 0.562 | 1.312 | 2.457 | 7.071 |
| `occupancy_bin_build` | 0.220 | 0.584 | 1.330 | 49.438 |
| `occupancy_finalize` | 0.056 | 0.086 | 0.544 | 2.351 |
| `occupancy_position_lookup` | 0.303 | 0.965 | 1.711 | 5.766 |
| `occupancy_rebuild` | 1.635 | 3.242 | 4.709 | 52.957 |
| `occupancy_section_mapping` | 2.291 | 4.295 | 5.943 | 13.714 |

### Stage 2: cap 200 (150–300 simulated seconds)

Mean active cars: 184.76; profiler samples: 3000.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 34.930 | 58.077 | 167.958 | 1675.336 |
| `spawn` | 1.738 | 0.809 | 49.783 | 76.346 |
| `snapshot` | 5.243 | 6.037 | 14.181 | 549.675 |
| `observe` | 2.901 | 3.394 | 6.504 | 242.154 |
| `intent_generation` | 12.074 | 15.120 | 40.974 | 837.841 |
| `conflict_resolution` | 1.128 | 1.726 | 3.258 | 155.606 |
| `movement_apply` | 6.805 | 8.935 | 15.757 | 437.198 |
| `occupancy_rebuild` | 4.953 | 5.154 | 12.877 | 777.485 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 1.574 | 2.526 | 5.267 | 163.898 |
| `intent_chain_check` | 0.204 | 0.223 | 0.690 | 223.897 |
| `intent_control_claim_lookup` | 0.298 | 0.585 | 1.320 | 10.500 |
| `intent_control_inside_scan` | 0.695 | 1.082 | 2.659 | 133.406 |
| `intent_control_state` | 1.151 | 1.827 | 3.556 | 144.217 |
| `intent_control_stop_distance` | 0.080 | 0.140 | 0.469 | 2.321 |
| `intent_exit_gap` | 2.699 | 3.564 | 7.060 | 305.229 |
| `intent_generation` | 12.074 | 15.120 | 40.974 | 837.841 |
| `intent_leader_lookup` | 1.971 | 2.839 | 4.421 | 326.859 |
| `intent_merge_observation` | 0.039 | 0.051 | 0.199 | 16.803 |
| `intent_packaging` | 0.481 | 0.898 | 1.691 | 11.287 |
| `intent_priority_query` | 1.142 | 1.653 | 3.003 | 165.187 |
| `intent_route_lookup` | 1.343 | 2.044 | 5.029 | 74.481 |
| `intent_speed_target` | 1.195 | 1.870 | 3.543 | 94.647 |
| `occupancy_bin_build` | 0.687 | 0.853 | 1.811 | 462.808 |
| `occupancy_finalize` | 0.125 | 0.204 | 0.677 | 14.040 |
| `occupancy_position_lookup` | 1.379 | 1.695 | 3.929 | 205.624 |
| `occupancy_rebuild` | 4.953 | 5.154 | 12.877 | 777.485 |
| `occupancy_section_mapping` | 6.403 | 7.399 | 21.019 | 793.265 |


## Method and limits

The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. Target cap schedule: 100 cars for 150s, then 200 cars for 150s.

The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.

© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).
