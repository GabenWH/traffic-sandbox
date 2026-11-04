# Native pedestrian routing handoff

Branch: `feature/native-pedestrian-routing`.
Includes the shared building-resource/construction-company changes and the Arcata workday harness.

Python owns roads, pedestrian geometry, world edits, jobs and service choices.
Walking now compiles once per world revision into the native traffic library.
Cars and walkers share the C++ `SpawnGraph` pathfinder, with separate mode connectivity.
Native code projects walking endpoints and searches without copying adjacency.
Python receives edge slices and reconstructs the existing route/crossing metadata.

## Run in Codex

From the repository root, with Python and a C++17 compiler available (the native library builds automatically):

```sh
git fetch origin
git switch --track origin/feature/native-pedestrian-routing
python -m unittest discover -s tests -v
python -u tools/run_arcata_workday_stress.py
```

If the local branch already exists, switch to it normally. The normal stress run
includes automatic job assignment. To isolate routing from employment selection:

```sh
STRESS_AUTHORED_JOBS=1 python -u tools/run_arcata_workday_stress.py
```

Optional bounded diagnostic (intentional exit 124 after 90 wall seconds once simulation starts):

```sh
STRESS_AUTHORED_JOBS=1 STRESS_WATCH_SECONDS=90 python -u tools/run_arcata_workday_stress.py
```

The scenario is 500 houses plus 500 apartments, 6,000 residents, 20 endpoint
businesses, three farms, one factory, a construction company and diagnostic site,
three bus lines and 12 buses. Target simulated interval: 06:00–20:00.
The checked-in Arcata result files describe the **pre-migration failure**, not a
successful run of this branch. The harness writes its new output under
`benchmarks/arcata/results/`; inspect the new timestamps and completion status.

## Evidence and limits

- Full suite: 610 tests ran successfully (593 passed, 17 skipped for missing Panda3D/display). The additional Dijkstra regression also passed in the five-test focused run.

- New regression forbids Python graph copying and Python path search during walking queries.
- Tests cover reverse curved geometry, disconnected/empty/zero-length journeys,
  independent concurrent results, world rebuilds and reference Dijkstra lengths.
- Independent review compared 2,000 routes with the old Python implementation;
  lengths and first-crossing fractions matched within 1e-6. It also checked cold
  concurrent compilation using 10 workers and reported no correctness blockers.
- Small local comparison: 100 identical routes on a 220-segment grid took 1.0232s
  with the old Python implementation versus 0.0188s with a warm native snapshot.
  This excludes compilation and is illustrative, not an Arcata throughput result.
- The full Arcata workday has not been rerun after migration; that is the next Codex test.
- Native queries release the GIL and support concurrent readers, but current
  gameplay callers still wait synchronously. Background economy scheduling,
  destination shortlisting, and native transit itinerary selection are not part
  of this migration. Bus schedules and the small itinerary graph remain Python.
- Deferred minor review suggestion: add a permanent cold-start concurrency test;
  the current regression warms the snapshot, while cold-start was checked by review.
