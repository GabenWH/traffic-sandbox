# Background Commutes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Keep active traffic responsive while preparing capped, staggered trips and learning routes for the following day.

**Architecture:** An immutable native vehicle graph and cached destination trees run on a bounded background worker. The simulation owner schedules departures, validates plans, reserves parking and records travel observations; learned costs apply from the next day.

**Tech Stack:** Existing Python 3, ctypes, C++17 and unittest; no added dependency.

**Spec:** `docs/superpowers/specs/2026-11-04-background-commutes-design.md`

## Global Constraints

- No simulation update waits on a routing future.
- Workers never mutate live actors or parking; topology edits invalidate results.
- Congestion learning changes following-day routes, not active trips.
- Preserve native admission safety, actor identity, inventory/fuel accounting and old saves.
- User authorized a feature-branch GitHub push; do not merge main.

## Review Focus

- A road is edited or a workplace closes while a request is queued: reject the old plan and preserve the resident/car.
- A destination lot fills while a route is being calculated: reserve only at admission and retry fairly.
- Save/load while a route is pending: restore logical intent without serializing or waiting on a future.
- A large update crosses midnight while trips finish: only completed prior-day observations affect the new day.
- A blocked worker or saturated entrance: active cars advance and another entrance can continue admitting.

### Task 1: Immutable native routing trees

**Files:** Create `native/traffic/routing.h`, `native_routing.py`, `tests/test_native_routing.py`; modify `native/traffic/engine.cpp` and `engine.h`.

**Interfaces:** `NativeRouteGraph(node_count, edges)` accepts `(source, destination, cost)` rows; `tree(targets, costs=None)` accepts `(node, final_cost)` roots; `tree.path(origins)` returns `(origin_index, target_index, edge_indices, cost)` or `None`. Query-local buffers and immutable native ownership allow concurrent callers.

- [x] Write failing tests for weighted paths, multiple endpoints, unreachable nodes, independent concurrent queries and invalid inputs.
- [x] Run `python -m unittest tests.test_native_routing`; inspect expected failures.
- [x] Implement native reverse Dijkstra and ctypes ownership; use existing hashed native build.
- [x] Run the native routing tests plus existing native walking/spawning tests; expect no failures.
- [x] Commit the tested component.

### Task 2: Background route preparation and following-day learning

**Files:** Create `commute_routing.py`, `route_learning.py`, `tests/test_commute_routing.py`, `tests/test_route_learning.py`; modify `persistent_fleet.py`.

**Interfaces:** `BackgroundRoutes` owns graph snapshots, bounded futures and destination trees; `request(...)` returns pending/ready/unreachable without waiting; `begin_update(day)` resets submission allowance. `TravelLearning` records link samples, freezes next-day costs, retains per-driver habitual routes and tracks remaining-route users.

- [x] Write and run failing tests for worker blocking without blocking the caller, shared trees, queue/submission bounds, stale topology, same-lane partial routes, no same-day adaptation and next-day alternative choice.
- [x] Implement preparation using copied endpoint values and native-only searches; marshal plans and apply parking/admission only on the owner thread.
- [x] Record link travel times from fleet progress and preserve familiar choices below the improvement threshold.
- [x] Run component, parking and persistent-fleet tests; expect no failures.
- [x] Commit the tested component.

### Task 3: Bounded, distributed city departures and persistence

**Files:** Create `commute_schedule.py`, `tests/test_commute_schedule.py`, `tests/test_background_city.py`; modify `city_simulation.py`, `gameplay_persistence.py`, and lifecycle fixtures only where old departure timing was assumed.

**Interfaces:** `CommutePolicy` stores spread/rate/active limits; queued departure intents are keyed by resident and direction. `CitySimulation.update` advances movement before servicing bounded departures and never calls a synchronous planner. Save/load requeues pending logical intent and learned state.

- [x] Write and run failing tests for deterministic spread, shifted returns, global/lot admission bounds, fairness, a held route worker with an already moving actor, road edits, pending saves and learned-state saves.
- [x] Integrate the service into city updates and fleet dispatch; apply current person/workplace/access validation on every admission.
- [x] Persist logical state and migrate absent fields; discard native caches during restore/rebind.
- [x] Run city, construction, recovery, service and persistence tests; expect no failures.
- [x] Commit the tested integration.

### Task 4: Arcata verification and publication

**Files:** Modify `tools/run_arcata_city_workday.py`, `tests/test_arcata_city_workday.py`, `benchmarks/arcata/README.md`; add measured benchmark results.

**Interfaces:** CLI exposes departure window, trip-start rate and active-car limit; reports include routing queue, cached trees and admission counters.

- [x] Write and run failing CLI/report tests, then implement flags and counters.
- [x] Run the whole unittest suite with Panda3D available; inspect all failures/skips.
- [x] Run the 10,000-resident synchronized departure case and a spread case with exact 50-ms update calls. Save original and new timing distributions, arrivals and resource conservation; do not infer frame guarantees from averages.
- [x] Obtain one fresh whole-branch review, fix important findings with reproducing tests and rerun required checks.
- [x] Commit the tested implementation, benchmark evidence and handoff notes.

Publication follows these local checks: push the tested feature branch through the connected GitHub service, verify its remote head and tree against the local committed tree, then report the branch and measured limitations. The user has authorized this external step.
