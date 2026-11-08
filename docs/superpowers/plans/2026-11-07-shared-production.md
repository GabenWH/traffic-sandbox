# Production Shared Vehicle State Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan.

**Goal:** Make shared state the sole application path and push the verified branch.
**Architecture:** Always bind native vehicle storage to Python views. Materialize
views at lifecycle boundaries; retain owned snapshots only for diagnostics.
**Tech Stack:** Python, ctypes, C++17, unittest.
**Spec:** `docs/superpowers/specs/2026-11-07-shared-production.md`

## Global Constraints

Preserve save/load, live edits, road rebuilds, completion events, RNG semantics and
shared-view lifetimes. Keep engine.cpp readable and below 2,000 lines. Push to
`fix/parking-cache-preference-scaffold`; preserve unrelated working-tree edits.

## Review Focus

- Retained completed/removed objects and brains remain readable after engine close.
- Brain replacement and scalar edits materialize all attached state first.
- Saves taken while native views are live load into identical transport state.
- Road rebuilds release old storage without dangling views.
- Rendering/inspection reads live state without eager full-fleet export.

### Task 1: Promote shared state and retire runtime copying

**Files:** `traffic_testbed.py`, `native_spawning.py`, `native_shared.py`,
`native_traffic.py`, `tests/test_native_shared.py`, affected integration tests,
`tools/benchmark_native_shared.py`, `tools/benchmark_dense_vehicles.py`, runtime docs.

**Interfaces:** `RoadVehicleSimulation(native_output_mode='shared')`;
`SharedBinding.detach()` materializes a stable ordinary vehicle/brain;
benchmark tools measure shared state only.

- [x] Write and run failing tests: default updates expose live fields without
  state export; requesting copy raises before discarding an active engine.
- [x] Always attach shared views; remove eager sync and runtime mode branches.
- [x] Exercise edits, completion/removal/close, road rebuilds, transport round-trip
  saves and actual renderer inputs; repair lifecycle defects with failing tests.
- [x] Migrate comparisons to independent Python reference tests and shared-only
  benchmarks. Update docs to distinguish current behavior from historical results.
- [x] Run `python -m unittest discover -s tests -q` and dense shared benchmarks,
  retaining traffic outcomes alongside mean/p95/p99/max.
- [x] Fix viewer zoom around the pointer with pan/limit regression tests; include
  the Arcata visual launcher requested during implementation.
- [x] Commit; obtain independent code review, resolve material findings, push and
  verify the GitHub branch head.
