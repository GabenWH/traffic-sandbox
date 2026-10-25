# Native traffic simulation and parity tests

These tests run the real C++ traffic engine through `native_traffic.py` and compare
it against Python's `data_first` engine after every step. They do not replay saved
Python decisions. C++ computes observations, following, merge choices, priority,
claims, deadlock handling, acceleration, and route movement internally. The full
native simulation also owns source timers, Python-compatible random selection,
A* routing, route assembly, admission, IDs/colors/styles and insertion.

## Run the application with C++ traffic

```sh
python freeway_simulator.py --traffic-engine native
```

Or construct `RoadVehicleSimulation(update_mode="native")` and use its existing
`update`, `spawn_car`, `admit_route` and mutation APIs. Python compiles the map
graph on network changes and maintains output views for rendering/construction;
spawn decisions and movement run inside C++. The shared library compiles locally
when first needed. Native-mode errors are surfaced explicitly.

From the repository root, with Python 3.11+ and a C++17 compiler:

```sh
python -m unittest discover -s tests -p 'test_native*.py' -v
python -m unittest discover -s tests -q
```

The binding compiles a content-addressed shared library under ignored
`build/native-traffic/`. A failed compilation or missing binding fails the tests;
the native checks do not silently fall back to Python.

## Compared outputs

Vehicle IDs, active/completed membership, route distance, speed, x/y position,
heading, desired speed, stop dwell, brain state, turn signal, wait reason,
phantom leader, and current claim are compared on each tick. Numeric tolerance
is approximately `1e-7` in model units; enum/string/ID comparisons are exact.
The original low-level movement tests supply identical external admissions.
`test_native_spawn_scenarios.py` runs independent Python and C++ spawning for
80 simulated seconds per scenario/map, with one-second staggered source clocks.
It additionally compares route edges/costs, source/destination, color/style,
generated counts, source clocks and complete RNG state on every 50 ms tick.

Coverage includes all seven merge-lab scenarios, both uploaded slip-lane and
roundabout maps, four-way stops, uncontrolled crossings, cautious drivers,
vehicle speed caps, live speed/control changes, following, placement/rewinds,
resizing, removal, zero-time steps, large timesteps, completion during an early
substep, and importing a simulation after it has begun driving. Additional tests
disable Python decision/movement functions while stepping native code, and
deliberately alter native state to confirm the comparison fails.

The committed-deadlock-winner fixture checks a stopped car with an existing grant
while circulating traffic blocks its path. Import preserves that grant and wait
ages, and removing the blocker resets deadlock bookkeeping as Python does.

`test_native_spawn_admission.py` runs the admission regression scenarios against
native clearance. `native/traffic/test_spawning.cpp` executes C++ routing,
body/gap admission and scheduling assertions, plus 800 random choices and a
complete MT19937 state comparison driven by the Python test harness. This is
actual native execution, independent of the saved-result regression replay.

## Integration and lifetime

Source edits, cap/speed/control changes, external admissions, placement, resize,
route replacement, roster order, clears, network rebuilding and switching update
modes are supported. Explicit changes to a public vehicle view invalidate its
native backend and import the changed state on the next native operation.
Native debugger frames contain native observations/results. Static conflicts
and yielding relationships are stored within junctions, avoiding a global square
matrix across every regional connection.

Python still constructs the canonical road network and external trip requests.
`NativeRoadSimulation.find_route` supports junction and precise lane-position
queries in C++. The existing construction scheduler can supply external routes
to native admission. The older fixed freeway simulation and economy stay Python.

`vehicle_views()` borrows native records until the next engine operation.
`snapshot()` returns owned Python values. `sync()` explicitly copies output into
existing display vehicles; it is not called by the differential driver before
comparison, so Python reference state cannot mask a native discrepancy.

The C ABI is version 2; borrowed route, event, bookkeeping and trace records also
expire on engine mutation. Python returns owned `Path` objects for application
route views. Handle-to-ID history is currently retained for the engine lifetime;
very long high-throughput runs can grow that Python mapping.

## Measure full spawning and movement

```sh
python tools/benchmark_native_spawning.py --seconds 60 --warmup 20 \
  --scenario dense-network-gauntlet --output build/native-spawning/timings.json
```

This runs both engines' own schedulers and admissions, reports cold graph/update
startup separately, and retains every measured tick. Native timings separate
configuration, spawning, accepted-car views, movement and output synchronization.
Whole-update wall time includes the application views and Python occupancy
publication. Rendering and economy are excluded. Car caps are ceilings; the
report records actual peak/final counts and admissions/completions.

The Arcata/Eureka/McKinleyville 10,000-car test still requires regional input with
verified freeway ramps. The earlier Arcata extract has no ramp-link coverage;
these fixture tests do not establish regional capacity or application FPS.
