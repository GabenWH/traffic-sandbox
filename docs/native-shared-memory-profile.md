# Shared native vehicle memory benchmark

Profiled on 2026-10-27. Baseline `main` was verified at `3bee2f8e11f7fed87312759e03f6dfd3e5595c12` before the experiment. Both measured modes use the same native C++ driving and spawning engine; this is not a C++ versus Python engine comparison.

## What shares memory

The experimental `native_output_mode="shared"` attaches Python vehicle and brain views to the actual C++ `NTSpawn` driving fields and position/heading records. Current claim metadata is maintained on claim changes and exposed by address. It does not export or copy all active vehicle records each update. Strings are queried when read. Python vehicle identities and route metadata are retained.

The library runs in the Python process, so there is no operating-system shared-memory segment or IPC. C++ writes during the synchronous step; Python reads between steps. Views attach at admission and materialize before completion, removal, engine shutdown, or an explicit Python mutation. The experiment supports the standard vehicle/brain classes. It is not a concurrent multi-thread read/write interface.

Both modes still publish RNG/source clocks, claims/deadlock bookkeeping, and the Python occupancy index every tick. The shared path only changes how vehicle fields reach Python. Copying remains the default.

## Method

Three paired runs alternate copy/shared order, with seed 42, 5 simulated seconds of warmup and 30 measured seconds per run at 50 ms updates. Each mode has 1,800 measured updates per workload/consumer combination. Compilation and setup are excluded. Native phase timers are enabled in both modes. There are 48 runs and 28,800 measured updates in total.

The generated case is the original 600-foot signalized crossing, capped at 60 cars; measured peak was 46 and mean active population was 34.11. The fixed-fleet cases preload 60, 250, or 1,000 cars across four approaches, with 36-foot initial spacing and longer arms to fit them. No sources run in fixed-fleet cases. The 60-car fleet averages 59.11 active cars as vehicles complete; the 250- and 1,000-car fleets retain their full populations. These are synthetic CPU loads, not throughput/capacity experiments.

The second consumer variant reads every active vehicle's position, heading and signal every update. It models display data consumption, not actual UI drawing or GPU rendering. Total timings below are process CPU per update, including those reads when enabled. Subphase timings use elapsed wall time. Small percentage differences on this shared runner should be treated as inconclusive.

Every pair matched active-car counts at every update, final vehicle/brain state fingerprints, completion IDs, RNG/source state, and display checksum. Separate regression tests compare state every tick across 900 updates and check manual placement, removal, backend close/mode changes and retained completed objects.

## Results

| Workload | Display reads | Copy CPU/update | Shared CPU/update | Change in CPU |
| --- | --- | ---: | ---: | ---: |
| Generated (46 peak) | No | 0.4649 ms | 0.4470 ms | -3.9% |
| Generated (46 peak) | Yes | 0.4882 ms | 0.4516 ms | -7.5% |
| 60 initial cars | No | 0.5388 ms | 0.5184 ms | -3.8% |
| 60 initial cars | Yes | 0.5610 ms | 0.5532 ms | -1.4% |
| 250 initial cars | No | 1.6839 ms | 1.7270 ms | +2.6% |
| 250 initial cars | Yes | 1.8786 ms | 1.8024 ms | -4.1% |
| 1,000 initial cars | No | 8.6470 ms | 7.8554 ms | -9.2% |
| 1,000 initial cars | Yes | 9.4953 ms | 10.8862 ms | +14.6% |

Negative change means less CPU. At 1,000 cars shared reads reduce CPU by 9.2% without display consumption, but increase it by 14.6% with display consumption. This experiment does not establish a general speedup.

## Where the time goes at 1,000 cars

Elapsed subphase means, in milliseconds per update. Vehicle, bookkeeping and occupancy rows partition output synchronization; the movement row is a separate native call.

| Phase | Copy, no display reads | Shared, no display reads | Copy, display reads | Shared, display reads |
| --- | ---: | ---: | ---: | ---: |
| vehicle state sync | 1.6600 | 0.0065 | 1.6536 | 0.0082 |
| bookkeeping sync | 0.0471 | 0.0303 | 0.0483 | 0.0354 |
| occupancy sync | 4.6970 | 5.4860 | 5.0830 | 7.1453 |
| native movement | 1.5816 | 1.5852 | 1.6102 | 1.7284 |

The former output-sync total bundled field copying, bookkeeping and occupancy publication. Sharing almost eliminates field synchronization, while repeatedly reading native fields through Python properties increases occupancy/display costs. The largest remaining measured phase is the retained Python occupancy update. The next substantial optimization would address that duplicate index or consume native data in batches; these results do not measure either change.

## Reproduce

```sh
python -m unittest tests.test_native_shared tests.test_native_signalized_intersections \
  tests.test_native_spawning tests.test_native_traffic tests.test_native_launch -q
python tools/benchmark_native_shared.py --seconds 30 --warmup 5 --repeats 3 \
  --fleet-sizes 60 250 1000 --output build/native-spawning/shared-profile.json
```

Targeted validation: 29 tests passed. Compact per-run results, quantiles, phase times, environment and source digest are in `docs/native-shared-memory-profile.json`. The ignored raw report contains all update samples. The source digest identifies the measured code; reruns may vary with runner load and generated map identifiers.
