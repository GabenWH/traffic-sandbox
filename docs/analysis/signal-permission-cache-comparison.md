# Signal permission CPU comparison

The signal controller now publishes a shared movement-to-aspect map when its state changes. A vehicle reads that aspect once per update. Physical conflict checks are deferred until the vehicle is in the entry zone; `data_first` repeats the check only if a new claim was granted at that same intersection. Signal occupancy is refreshed once at frame start and updated per vehicle after movement.

## Frozen-state CPU

Median CPU milliseconds per `update()` across three seeds. Each seed used 50 timed samples after 20 warmups at each vehicle count.

| Update mode | Cars | Original | Previous rewrite | Optimized | vs original | vs previous rewrite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy | 32 | 2.648 | 3.651 | 3.027 | +14.3% | -17.1% |
| legacy | 64 | 9.181 | 11.601 | 9.925 | +8.1% | -14.4% |
| legacy | 128 | 33.336 | 42.163 | 38.605 | +15.8% | -8.4% |
| data_first | 32 | 1.146 | 1.324 | 1.230 | +7.4% | -7.1% |
| data_first | 64 | 2.197 | 2.556 | 2.279 | +3.8% | -10.8% |
| data_first | 128 | 4.621 | 5.312 | 4.644 | +0.5% | -12.6% |

The optimization lowers CPU against the preceding rewrite by 8% to 17% in legacy mode and 7% to 13% in `data_first`. Against the original implementation, the latest medians range from 0.5% to 16% higher. The short frozen workload has visible run-to-run noise, so treat those small differences as approximate; the three-seed raw results are included in the JSON file.

## Method

The comparison ran the original source at `fa6fe8203ddf9f1c982d4e8e87b18c1b090a6c50`, the previous rewrite, and the optimized worktree in isolated, counterbalanced subprocesses. It used identical frozen 32-, 64-, and 128-car states in both update modes. CPU timing covers `update()` only. A single 0.05-second flow tick followed each frozen run and is not included in the CPU summary; this is a CPU microbenchmark, not a throughput measurement.

Exact samples, source hashes, and run metadata are in [signal-permission-cache-comparison.json](signal-permission-cache-comparison.json).
