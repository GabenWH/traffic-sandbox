# Native signal intersection profile

Profiled on 2026-10-26 with Python 3.12.14, GCC 13.3.0, and an AMD EPYC
9V74. The benchmark used the `signalized-crossing` scenario, seed 42, a 60-car
cap, 30 simulated seconds per run, 5 seconds of warmup, and 50 ms updates.
Three paired runs alternated engine order. Each engine processed 600 measured
updates per run. Spawned, completed, and peak-active counts matched within each
pair.

| Engine | Mean process CPU per update | Median | p95 | Mean completed |
| --- | ---: | ---: | ---: | ---: |
| Native C++ | 0.4331 ms | 0.4156 ms | 0.4797 ms | 8.67 |
| Data-first Python | 1.5971 ms | 1.5403 ms | 1.7290 ms | 8.67 |

The native run used 72.9% less process CPU per update (3.69× speedup) on this
scenario. This comparison measures the full application update, including
Python configuration and output synchronization; C++ compilation and warmup
are excluded.

The native wrapper's mean time per update was 0.3916 ms across its recorded
phases:

| Phase | Mean |
| --- | ---: |
| Output synchronization | 0.1792 ms |
| Native configuration | 0.1186 ms |
| Spawn views | 0.0619 ms |
| C++ movement call | 0.0277 ms |
| Native spawning | 0.0042 ms |

Inside the C++ tick, optional phase timers measured about 0.0249 ms per update.
Vehicle decisions were the largest internal phase at 0.0099 ms (39.8%),
followed by claim arbitration at 0.0047 ms (18.9%), preparation at 0.0051 ms
(20.4%), movement at 0.0035 ms (14.2%), and control arbitration at 0.0017 ms
(6.7%). The largest end-to-end CPU cost is output synchronization, so reducing
that Python/native boundary work has more headroom than tuning signal checks
inside the C++ movement loop.

Reproduce the profile with:

```sh
python tools/benchmark_native_spawning.py --scenario signalized-crossing \
  --seconds 30 --warmup 5 --dt 0.05 --max-cars 60 --repeats 3 \
  --output build/native-spawning/signal-profile.json
```

These are timings from the current shared runner, not a hardware-independent
performance guarantee.
