# Native traffic parity verification

October 21, 2026. Reference engine: Python `data_first`.

| Check | Result |
|---|---|
| Live native differential/lifecycle tests | 17 cases, no failures |
| Full repository suite | 398 tests run, 17 skipped, no failures |
| Dense gauntlet, seed 42 | 7,200 compared ticks; 360 simulated seconds; 328 completions; no compared state mismatches |
| Slip-lane short link, seed 19 | 7,200 compared ticks; 360 simulated seconds; 153 completions; no compared state mismatches |
| Continuous roundabout pressure, seed 19 | 7,200 compared ticks; 360 simulated seconds; 182 completions; no compared state mismatches |
| Saved-output baseline checker smoke test (`test_car_brain.py`) | Native exit 0; 43 assertion replays; 142 geometry samples; one Python-only assertion |
| Full saved-output baseline replay | 368 original tests; 17 skipped; 17,507 assertion replays and 220,807 geometry samples; native exit 0 |

The live tests run actual C++ decisions and movement. The saved-output checker is
a separate baseline-import check. Neither run is a performance benchmark.

Run the live suite:

```sh
python -m unittest discover -s tests -p 'test_native*.py' -v
```

Reproduce the six-minute dense comparison:

```sh
NATIVE_PARITY_SCENARIO=dense-network-gauntlet NATIVE_PARITY_SECONDS=360 NATIVE_PARITY_SEED=42 python -m unittest tests.test_native_traffic.NativeScenarioParityTests -v
```

All seven default merge scenarios run for 30 seconds each; the uploaded slip-lane
and roundabout maps each run for 80 seconds. See README.md for compared fields,
tolerances and the remaining application-integration boundary.

The extended checks reproduced and fixed two deadlock-state mismatches: importing
an already committed winner now preserves its grant and wait ages; explicitly
removing a vehicle resets the native deadlock resolver as Python does. The saved
baseline exporter also excludes native comparator self-tests, whose deliberately
failed assertions are expected test inputs rather than traffic regressions.
