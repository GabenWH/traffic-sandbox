# Lazy Parking Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove unused alternate-parking walking searches from successful departures and measure their contribution to slow city updates.

**Architecture:** Retain the current preferred-lot order, exact walking eligibility, reservations, and change-driven waiting. Make `ParkingTrips.options(destination)` a replayable lazy iterator: yield cached eligible sites first and validate additional nearby sites only when the caller needs another choice. Each destination owns its incremental candidate iterator; access/policy changes clear that cache as before.

**Tech Stack:** Python, existing native C++ walking and vehicle routing, unittest.

**Spec:** Existing diagnosis at source commit `9e8d39218837ab68c757fa9f806aba1f410ee03d`; this plan's Goal, Architecture, and Global Constraints define the narrow performance fix. Grace authorized continued performance investigation and prefers realistic behavior when affordable. Arrival-time search remains an experiment proposal, not part of this change.

## Global Constraints

- Preserve capacity, reservation, destination ordering, walk limits, save/load, and waiter wakeup behavior.
- Do not disable garbage collection or alter tick size (0.05 seconds) to hide pauses.
- No GitHub push or merge is authorized by this task.
- Record controlled cold-departure measurements separately from full-commute results. Do not claim the original 876 ms tick was exactly restored.

## Review Focus

- A free primary lot must admit its car without building hypothetical walking paths.
- A full primary lot must still select the first reachable fitting alternative, without evaluating unused later alternatives.
- Resuming a partially consumed candidate sequence must preserve eligibility and order without repeating walking searches.
- Full-lot wait registration must cover all eligible lots, including after partial iteration and save/load.
- Access/policy invalidation must discard partially evaluated candidate state.

### Task 1: Lazily validate parking alternatives and measure the effect

**Files:**
- Modify: `parking_trips.py`
- Create: `tests/test_lazy_parking_options.py`
- Create: `tools/benchmark_parking_options.py`

**Interfaces:**
- Consumes: `ParkingAccessIndex.candidates(destination, max_distance)`, `TransitSimulation.journey_path(...)`, current fleet dispatch.
- Produces: `ParkingTrips.options(destination)` iterable with unchanged complete contents and ordering; a JSON benchmark reporting routing work and timing.

- [x] Write regression tests using real city/fleet/walking components: primary departure creates zero walking-cache entries; overflow departure does not materialize unused alternatives; repeated partial iteration reuses validation; invalidation restarts validation. Run against unchanged production code and confirm the intended eager-search failures.
- [x] Replace eager list construction with incremental cached eligibility, preserving all filters and iterator replay. Run new tests and existing parking/background tests.
- [x] Add a real Arcata-map benchmark comparing the baseline eager implementation from the starting commit with the changed implementation on controlled departures; separately measure indexed parking-availability queries. Retain raw JSON and provenance.
- [x] Run `python3 -m unittest discover -s tests -q`; expect no failures. Run the two-hour 16k, seed-42 commute with 0.05-second ticks and record garbage collection, walking queries, peak/percentile update times, population and resource invariants.
- [x] Review the diff, record limitations, and commit locally. Deliver results and patch without pushing.

### Task 2: Bound cold alternative validation across movement quanta

**Evidence:** The controlled real-map probes preserved every selected destination and complete option list, but one infeasible trip still performed 462 walking searches and took about 584 ms with lazy iteration. Deferring the tail removes waste but does not bound an exhausted search.

**Files:** `parking_trips.py`, `commute_schedule.py`, `tests/test_lazy_parking_options.py`, `tools/benchmark_parking_options.py`.

**Interfaces:** Add positive integer `CommutePolicy.parking_walk_queries=4`. `options(destination, bounded=False)` keeps its complete public iteration contract. During active simulation `_attempt` requests bounded iteration; a private pending marker leaves the trip in the existing planning/retry queue. Share the budget across event fragments in the same 0.05-second movement quantum.

- [x] Write and observe a failing regression: full cold neighboring lots and event fragments must create at most four alternative walk queries in the first 50-ms update, then eventually register the complete full-lot wait.
- [x] Implement resumable per-query validation and the positive policy limit, preserving synchronous external iteration and direct dispatch behavior.
- [x] Run all parking/background tests and full suite. Measure the bounded implementation with the same real-map commute harness; retain the eager and lazy-only runs as separate comparisons.
- [x] Verify policy persistence/defaults and partially evaluated cache recovery. Commit locally and include the measured remaining pauses in the report.

## Completed measurements

All three reported variants completed 07:00–09:00 with 16,000 residents accounted for and unchanged parking supply. The eager baseline reproduced a 1,105.556 ms update with 1,075.984 ms of automatic GC. The final lazy/bounded run measured a 718.824 ms worst update, with 704.955 ms of GC, and 25,050 retained walk-cache entries versus 62,386. Mean outer update time was 9.170 versus 10.080 ms; these single runs were not CPU-isolated, so small timing changes are not causal estimates. Both runs had 4,300 workers at work and 25 cars waiting at 09:00.

Verification: 781 tests ran, 20 skipped and 761 passed. The new budget applies only to commute plans to preserve service retry contracts. Collector pauses remain unresolved: even the initialized city with no cached walking paths takes 170–203 ms for a full collector scan. A separate immutable-link-sharing experiment was not applied. An interrupted intermediate run was excluded; the monitored final rerun completed and retained diagnostics. Changes remain local; no push or merge.
