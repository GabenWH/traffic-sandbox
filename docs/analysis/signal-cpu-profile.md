# Signalized intersection CPU profile

## Is signal control the fastest?

I compared the optimized signal implementation with all-way-stop control on the same four-way map, using the same straight-through routes, car positions, and update modes. Each result is the median of three seeds; each seed used 50 timed `update()` samples after 20 warmups. Route construction and setup are outside the timer.

| Update mode | Cars | Signal | All-way stop | Signal change |
| --- | ---: | ---: | ---: | ---: |
| `data_first` | 32 | 1.225 ms | 1.068 ms | +14.7% |
| `data_first` | 64 | 2.295 ms | 2.372 ms | -3.2% |
| `data_first` | 128 | 4.725 ms | 4.845 ms | -2.5% |
| legacy | 32 | 3.170 ms | 3.058 ms | +3.7% |
| legacy | 64 | 11.038 ms | 11.034 ms | +0.0% |
| legacy | 128 | 40.269 ms | 38.398 ms | +4.9% |

Negative means signal control used less CPU. In the app’s `data_first` mode, signal control was about 2.5–3.2% faster at 64–128 cars, but 14.7% slower at 32. Legacy mode was effectively tied, with signals up to 4.9% slower. The results do not support calling signals categorically fastest; their cost is close to all-way-stop control in this workload.

## Where `data_first` spends CPU

`cProfile` captured 50 updates with 128 frozen cars. Times below are cumulative, so rows overlap and must not be added. Profiling overhead also makes these absolute times larger than the unprofiled benchmark above.

| Function | Calls | Cumulative time | What it does |
| --- | ---: | ---: | --- |
| `AllWayStopCoordinator.has_claim` | 31,700 | 0.120 s | Checks claimed crossings while finding the next controlled movement and updating vehicle state. |
| `TrafficOccupancyIndex.rebuild` | 100 | 0.103 s | Rebuilds spatial bins and section occupancy. |
| `_next_controlled_movement` | 12,800 | 0.075 s | Finds each vehicle’s next stop, yield, merge, or signal. |
| `TrafficOccupancyIndex.lead_from` | 12,700 | 0.064 s | Finds the nearest vehicle ahead. |
| `dataclasses.replace` | 6,400 | 0.055 s | Builds adjusted decisions during conflict resolution. |
| `_observe_priority_arrivals` | 50 | 0.051 s | Collects the entry-ready approaches for arbitration. |
| `CarBrain.decide` | 6,400 | 0.041 s | Produces vehicle speed and entry decisions. |
| `_signal_aspect` | 6,300 | 0.028 s | Reads the shared cached aspect for the current movement. |

The signal aspect lookup is about 3.6% of the profiled `update()` cumulative time. General vehicle and occupancy work takes more: 12,700 movement lookups, 12,700 lead searches, and two occupancy rebuilds per update dominate the profiled path.

## Legacy-mode hotspot

At 128 cars, `TrafficOccupancyIndex.rebuild` accounted for 4.93 of 5.58 seconds of cumulative time over 50 profiled updates, across 6,450 calls. Legacy mode rebuilds occupancy after each vehicle moves, so this grows with both vehicle count and update count. The signal-specific functions were not among its leading hotspots.

The application uses `data_first`; its next CPU target is the shared occupancy and movement-query work, not signal phase calculation. The previous comparison report contains the exact signal permission optimization and source fingerprints: [signal-permission-cache-comparison.md](signal-permission-cache-comparison.md).
