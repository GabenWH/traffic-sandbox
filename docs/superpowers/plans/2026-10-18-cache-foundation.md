# Simulation cache foundation implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline. Complete each test cycle before continuing.

**Goal:** Provide a reusable revision cache with guarded mutations and demonstrate it by retaining the city junction lookup across unchanged ticks.

**Architecture:** `simulation_cache.py` owns source revisions and lazy cache slots. `traffic_network_cache.py` adapts the existing map identity and `mobility_revision` to that API; `RoadVehicleSimulation` consumes the retained mapping.

**Tech Stack:** Existing Python and its standard library; unittest; no added dependency.

**Spec:** `docs/superpowers/specs/2026-10-18-incremental-simulation-cache-design.md`.

## Global constraints

- Preserve seeded spawn choices and existing traffic decision semantics.
- Cache dependencies are explicit root source revisions.
- A source's mutation scope invalidates on failure; it is not rollback.
- Cached reads during a dependent mutation, writes during a read phase or cache build, and cyclic cache evaluation must raise.
- The cache operates on the existing simulation thread.
- This delivery implements the foundation and junction mapping. Route, roster, occupancy, and coordinator migration remain described in the spec.

## Review focus

- An outer cache must not silently omit a nested cache's root dependencies, including when the inner value is already cached.
- Failed or nested mutations must never expose a stale saved value.
- Independent owners with equal names and revision numbers must remain independent.
- Replacing a map with an equal revision must replace the junction lookup.
- Every update mode must reuse the lookup without changing source order or random draws.

## Task 1: reusable revision cache

**Files:** create `simulation_cache.py`; create `tests/test_simulation_cache.py`.

**Interfaces:** `RevisionSource(name).stamp()/mutate()/read_only()`; `CachedValue(name, dependencies=tuple, build=callable).get()/clear()/info()`; read-only `dependencies`; immutable `RevisionStamp` and `CacheInfo`; descriptive runtime errors for unsafe access.

- [x] Write tests for lazy reuse, refresh after mutation, cached `None`, unrelated sources, partial failures, nested mutations, read/write guards, cycles, correct composition, and undeclared nested dependencies.
- [x] Run `python -m unittest discover -s tests -p test_simulation_cache.py -v`; expect RED because the new module is missing.
- [x] Implement the module with cached stamp objects, one current value per slot, and no cache registry or eager rebuilds.
- [x] Run the same focused command; expect all new tests PASS.

## Task 2: junction lookup integration

**Files:** create `traffic_network_cache.py`; modify `traffic_testbed.py`; create `tests/test_traffic_network_cache.py`.

**Consumes:** Task 1's `RevisionSource` and `CachedValue`.

**Produces:** `JunctionLookup.get(city_map) -> Mapping[str, Intersection]`, refreshed on map identity or `mobility_revision` change. `active_junctions()` and update-time source pruning use the retained lookup.

- [x] Write tests that count actual intersection iteration across unchanged ticks in both update modes, verify map rebuild/replacement, and reject mapping edits.
- [x] Run `python -m unittest discover -s tests -p test_traffic_network_cache.py -v -k unchanged`; expect RED before integration.
- [x] Implement the adapter and replace the two whole-map lookup constructions in the update path.
- [x] Run the focused tests; expect PASS and exactly one lookup build for unchanged topology.
- [x] Run `python -m unittest discover -s tests -q`; expect no failures; report skips accurately.
- [x] Review the exact changes and commit the verified foundation on the performance branch.

## Execution record

- Existing linked worktree confirmed on `perf/persistent-lane-occupancy`, base `e3e377d`.
- Existing source baseline was tested in the preceding review: 317 tests run, 17 skipped, no failures; only the design document changed before this implementation.
- Scope: provide the usable library and its first consumer; subsequent incremental-index migrations require their own behavior comparisons.
- Task 1 complete: expected missing-module RED, then 16 core tests passed.
- Task 2 integration RED: both modes traversed intersections 40 times over 20 ticks, where the new contract expects 1.
- First adapter run exposed a runtime evaluation of a type imported only under `TYPE_CHECKING`; moving the type to a postponed annotation fixed that exact error. All 6 integration tests then passed.
- Full suite: 339 tests run in 41.563 seconds, 17 skipped, no failures. `git diff --check` passed.
- Independent review: no correctness or performance findings within this delivery's scope; 28 cache-related tests passed.
- The reviewer compared 200 ticks per update mode against `e3e377d`, including a source toggle, vehicle state, completions, active-source order, and full RNG state; every compared tick matched.
