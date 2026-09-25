# Simulation Profiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record per-tick simulation phase timings and expose them in a selectable, exportable visualizer separate from UI frame timing.

**Architecture:** A reusable `SimulationProfiler` stores timing-only samples in a bounded deque and calculates statistics and exports. `TestTrafficSimulation` submits one record per internal tick using phase timers, while the existing debugger keeps its detailed car trace. `DashboardMixin` renders a separate simulation profiler window from those records.

**Tech Stack:** Python standard library, `unittest`, Tkinter Canvas.

**Spec:** `docs/superpowers/specs/2026-09-25-simulation-profiler-design.md`

## Global Constraints

- Keep the runtime dependency set unchanged.
- Retain no more than 600 samples by default.
- Do not time individual vehicles in the new profiler.
- Keep UI frame timing and simulation timing visibly separate.
- Keep the profile data contract independent of car and construction-vehicle classes.

## Review Focus

- The recorder remains bounded after runs longer than its capacity; test that the oldest sample is evicted.
- Recursive updates split into 0.05-second steps; test that each internal step is recorded.
- Profiling works with `debugger=None`; test a real routed traffic update in that configuration.
- An empty history renders a waiting state without an exception; exercise the empty graph-data helper.
- `total` is never double-counted in the stacked phase graph; test a sample with a larger `total` than its phase sum.

---

### Task 1: Record reusable per-tick timing data

**Files:**
- Create: `simulation_profiler.py`
- Modify: `traffic_testbed.py`
- Create: `tests/test_simulation_profiler.py`
- Modify: `tests/test_traffic_testbed.py`

**Interfaces:**
- Produces `SimulationProfiler.record_tick(system, simulated_time, elapsed_seconds, entity_counts, timings_ms)`, `samples`, `statistics()`, `as_dict()`, and `to_csv()`.
- `TestTrafficSimulation.profiler` is a default `SimulationProfiler`; update loops submit one timing-only record per internal tick, whether or not `TrafficDebugger` is configured.

- [x] Write tests for ring-buffer eviction, nearest-rank percentiles, arbitrary entity-count keys, invalid timing input, and JSON/CSV fields.
- [x] Run `python -m unittest discover -s tests -p test_simulation_profiler.py -v`; expect failures because the profiler module does not exist.
- [x] Implement `SimulationProfiler` with immutable sample records, bounded storage, aggregate statistics, and exports.
- [x] Run `python -m unittest discover -s tests -p test_simulation_profiler.py -v`; expect all profiler tests to pass.
- [x] Add an integration test using the existing real routed-traffic fixture with `debugger=None`; expect a recorded `total`, a `cars` count, and data-first phase names.
- [x] Instrument phase boundaries in `TestTrafficSimulation` and submit one profiler sample per 0.05-second or shorter tick. Leave detailed per-car timing behavior confined to `TrafficDebugger`.
- [x] Run `python -m unittest discover -s tests -p test_simulation_profiler.py -v`, `python -m unittest discover -s tests -p test_traffic_testbed.py -v`, and `python -m unittest discover -s tests -p test_traffic_debugger.py -v`; expect all tests to pass.
- [x] Commit as `feat: record per-tick simulation phase timings`.

### Task 2: Visualize and export the simulation profile

**Files:**
- Modify: `ui/app.py`
- Modify: `ui/dashboards.py`
- Modify: `ui/files.py`
- Modify: `docs/UI.md`
- Modify: `tests/test_performance_metrics.py`

**Interfaces:**
- Consumes the `TestTrafficSimulation.profiler` produced in Task 1.
- Produces a separate simulation-performance window opened from the current Performance window, with selectable phase blocks, a stacked tick graph, selected-tick details, aggregate statistics, and JSON/CSV export actions.
- Produces `stacked_timing_rows(samples, selected_blocks)` for deterministic graph data; it excludes `total` from the stack.

- [x] Add focused tests for empty graph data, selected-phase stacking without `total`, and tick selection by graph position; run `python -m unittest discover -s tests -p test_performance_metrics.py -v` and expect failure because the graph helpers are absent.
- [x] Implement the data helper, then add the simulation-profiler window with multi-select block filtering and click-to-select tick details.
- [x] Add export actions using `SimulationProfiler.as_dict()` and `.to_csv()` without changing existing analytics exports.
- [x] Document the Simulation profiler entry point and its phase graph in `docs/UI.md`.
- [x] Run `python -m unittest discover -s tests -p test_performance_metrics.py -v`; expect all graph-data tests to pass.
- [x] Run `python -m unittest discover -s tests -v`; expect the full suite to pass, with only existing optional Panda3D/display skips.
- [x] Commit as `feat: add simulation performance visualizer`.
