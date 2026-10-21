# Arcata traffic scale test

Run status: **complete**. Did not reach 5 updates/s in 300 simulated seconds. The highest observed cap was 200, with 200 active cars.

## Result

- Simulated time: 300.0 / 300 seconds (6,000 updates at 0.05 seconds each).
- Peak active test cars: 200; active at end: 200.
- Total spawned / completed: 213 / 13.
- Target cap at end: 200; schedule: 100 cars for 150s, then 200 cars for 150s.
- Measured update FPS uses the rolling mean wall time of 20 simulator updates; the threshold is 200 ms/update.
- Directed portal routes cached before timing: 30; route setup excluded from the FPS result (5.76 seconds).
- Host: AMD EPYC 9V74 80-Core Processor (9 logical CPUs), Linux-6.18.55-x86_64-with-glibc2.39, Python 3.12.14.
- Benchmark wall time: 187.1 seconds.

## Network

- 681 clipped OSM ways, 1,181 simulation road segments, 971 junctions.
- 88.4 miles of road centerline; 50 city-boundary portals available, 16 selected.
- OSM snapshot: 2026-06-01T08:52:28Z; boundary relation: 112123 (Arcata).

## Update phase timings

These are profiler samples across the full 300-second run. Values are milliseconds.

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 30.880 | 57.226 | 71.489 | 135.897 |
| `spawn` | 0.912 | 0.191 | 26.551 | 97.995 |
| `snapshot` | 2.762 | 5.993 | 8.312 | 33.988 |
| `observe` | 1.360 | 2.909 | 4.572 | 14.111 |
| `intent_generation` | 11.418 | 19.986 | 24.388 | 70.050 |
| `conflict_resolution` | 0.539 | 0.876 | 1.079 | 40.805 |
| `movement_apply` | 3.341 | 7.763 | 8.688 | 21.261 |
| `occupancy_rebuild` | 10.520 | 19.420 | 22.702 | 50.829 |

## Internal phase timings across all stages

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.740 | 1.233 | 1.521 | 5.136 |
| `intent_chain_check` | 0.057 | 0.110 | 0.153 | 0.843 |
| `intent_control_claim_lookup` | 0.140 | 0.229 | 0.345 | 2.233 |
| `intent_control_inside_scan` | 5.668 | 9.450 | 11.204 | 50.381 |
| `intent_control_state` | 5.900 | 9.816 | 11.673 | 50.705 |
| `intent_control_stop_distance` | 0.050 | 0.083 | 0.132 | 0.319 |
| `intent_exit_gap` | 1.629 | 3.531 | 4.681 | 14.037 |
| `intent_generation` | 11.418 | 19.986 | 24.388 | 70.050 |
| `intent_leader_lookup` | 1.036 | 1.691 | 2.083 | 5.800 |
| `intent_merge_observation` | 0.021 | 0.031 | 0.056 | 1.130 |
| `intent_packaging` | 0.245 | 0.408 | 0.538 | 4.014 |
| `intent_priority_query` | 0.573 | 1.220 | 1.493 | 37.375 |
| `intent_route_lookup` | 0.570 | 1.051 | 1.432 | 52.371 |
| `intent_speed_target` | 0.521 | 0.876 | 1.080 | 3.271 |
| `occupancy_bin_build` | 0.248 | 0.427 | 0.563 | 37.340 |
| `occupancy_finalize` | 0.095 | 0.206 | 0.292 | 4.874 |
| `occupancy_position_lookup` | 0.764 | 1.877 | 2.463 | 6.645 |
| `occupancy_rebuild` | 10.520 | 19.420 | 22.702 | 50.829 |
| `occupancy_section_mapping` | 3.743 | 7.424 | 9.323 | 37.171 |

### Stage 1: cap 100 (0–150 simulated seconds)

Mean active cars: 84.96; profiler samples: 3000.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 16.111 | 23.913 | 35.604 | 71.710 |
| `spawn` | 0.757 | 0.158 | 22.109 | 30.147 |
| `snapshot` | 1.220 | 2.097 | 3.065 | 6.873 |
| `observe` | 0.696 | 1.019 | 1.458 | 5.595 |
| `intent_generation` | 6.505 | 8.802 | 10.522 | 15.926 |
| `conflict_resolution` | 0.319 | 0.448 | 0.600 | 1.793 |
| `movement_apply` | 1.229 | 2.403 | 2.811 | 4.790 |
| `occupancy_rebuild` | 5.370 | 7.967 | 9.524 | 38.588 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 0.457 | 0.634 | 0.807 | 3.346 |
| `intent_chain_check` | 0.027 | 0.041 | 0.071 | 0.132 |
| `intent_control_claim_lookup` | 0.088 | 0.125 | 0.193 | 2.233 |
| `intent_control_inside_scan` | 3.375 | 4.528 | 5.318 | 9.143 |
| `intent_control_state` | 3.520 | 4.710 | 5.547 | 9.325 |
| `intent_control_stop_distance` | 0.031 | 0.040 | 0.075 | 0.269 |
| `intent_exit_gap` | 0.801 | 1.251 | 1.802 | 4.188 |
| `intent_generation` | 6.505 | 8.802 | 10.522 | 15.926 |
| `intent_leader_lookup` | 0.643 | 0.878 | 1.044 | 3.085 |
| `intent_merge_observation` | 0.013 | 0.016 | 0.033 | 1.130 |
| `intent_packaging` | 0.152 | 0.217 | 0.316 | 1.444 |
| `intent_priority_query` | 0.223 | 0.337 | 0.432 | 1.444 |
| `intent_route_lookup` | 0.275 | 0.402 | 0.516 | 2.396 |
| `intent_speed_target` | 0.314 | 0.440 | 0.582 | 2.604 |
| `occupancy_bin_build` | 0.161 | 0.310 | 0.428 | 31.480 |
| `occupancy_finalize` | 0.047 | 0.093 | 0.140 | 0.422 |
| `occupancy_position_lookup` | 0.228 | 0.489 | 0.646 | 2.260 |
| `occupancy_rebuild` | 5.370 | 7.967 | 9.524 | 38.588 |
| `occupancy_section_mapping` | 1.735 | 2.925 | 3.838 | 7.243 |

### Stage 2: cap 200 (150–300 simulated seconds)

Mean active cars: 184.76; profiler samples: 3000.

Overall update phases (milliseconds):

| Phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `total` | 45.649 | 62.250 | 78.981 | 135.897 |
| `spawn` | 1.067 | 0.221 | 28.420 | 97.995 |
| `snapshot` | 4.305 | 6.856 | 9.584 | 33.988 |
| `observe` | 2.023 | 3.601 | 5.191 | 14.111 |
| `intent_generation` | 16.332 | 21.478 | 27.996 | 70.050 |
| `conflict_resolution` | 0.760 | 0.953 | 1.220 | 40.805 |
| `movement_apply` | 5.453 | 8.111 | 9.312 | 21.261 |
| `occupancy_rebuild` | 15.670 | 20.530 | 24.391 | 50.829 |

Internal phase timings (milliseconds):

| Internal phase | Mean | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| `intent_brain_decision` | 1.023 | 1.325 | 1.792 | 5.136 |
| `intent_chain_check` | 0.087 | 0.123 | 0.183 | 0.843 |
| `intent_control_claim_lookup` | 0.192 | 0.256 | 0.400 | 1.822 |
| `intent_control_inside_scan` | 7.960 | 10.001 | 12.918 | 50.381 |
| `intent_control_state` | 8.279 | 10.391 | 13.241 | 50.705 |
| `intent_control_stop_distance` | 0.069 | 0.093 | 0.159 | 0.319 |
| `intent_exit_gap` | 2.457 | 4.010 | 5.144 | 14.037 |
| `intent_generation` | 16.332 | 21.478 | 27.996 | 70.050 |
| `intent_leader_lookup` | 1.429 | 1.798 | 2.464 | 5.800 |
| `intent_merge_observation` | 0.029 | 0.034 | 0.072 | 1.055 |
| `intent_packaging` | 0.337 | 0.444 | 0.601 | 4.014 |
| `intent_priority_query` | 0.923 | 1.314 | 1.984 | 37.375 |
| `intent_route_lookup` | 0.866 | 1.186 | 1.798 | 52.371 |
| `intent_speed_target` | 0.729 | 0.950 | 1.216 | 3.271 |
| `occupancy_bin_build` | 0.335 | 0.472 | 0.627 | 37.340 |
| `occupancy_finalize` | 0.143 | 0.229 | 0.350 | 4.874 |
| `occupancy_position_lookup` | 1.301 | 2.081 | 3.052 | 6.645 |
| `occupancy_rebuild` | 15.670 | 20.530 | 24.391 | 50.829 |
| `occupancy_section_mapping` | 5.750 | 8.158 | 10.853 | 37.171 |


## Method and limits

The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. Target cap schedule: 100 cars for 150s, then 200 cars for 150s.

The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.

© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).
