# Native Walking Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; track steps below.

**Goal:** Move pedestrian graph projection/search into the native vehicle routing library.
**Architecture:** Python compiles immutable native graph snapshots lazily; shared SpawnGraph searches use query-local bidirectional endpoint overlays. Existing WalkingRoute consumers retain their API.
**Tech Stack:** Python ctypes, C++17, unittest.
**Spec:** docs/superpowers/specs/2026-10-31-native-walking-design.md

## Global Constraints
- Python owns world editing and citizen decisions.
- No per-query graph copies; preserve distinct walking/driving layers.
- Include existing resource feature and Arcata reproduction harness in published branch.

## Review Focus
- Reverse and curved lane slices preserve geometry and length.
- Disconnected/empty/zero-length journeys fail cleanly.
- Map rebuild replaces compiled connectivity.
- Concurrent queries cannot corrupt result buffers.
- Vehicle route behavior remains unchanged.

## Task 1: Native snapshot and shared search
- [x] Add regression exercising walking while Python graph search/copy is disabled; test parallel queries, reverse curves and rebuilds.
- [x] Run focused tests and observe missing migration failure.
- [x] Add native snapshot C ABI and Python wrapper; extend SpawnGraph endpoint overlay for reverse lanes.
- [x] Replace pedestrian Python query path with native edge slices, preserving access/crossing assembly.
- [x] Run pedestrian and native vehicle tests, then full unittest discovery.

## Task 2: Handoff
- [x] Independent review, address correctness findings, document remaining performance scope.
- [x] Commit and publish feature/native-pedestrian-routing with stress harness.
- [x] Verify published tree matches tested local tree; provide branch and Codex commands.

## Execution record

- Implemented in the dedicated checkout on `feature/native-pedestrian-routing`, based on `d96212b`; no main-branch edits.
- Regression first failed on the old Python graph copy. Native walking tests then passed.
- Full discovery: 610 tests, 593 passed, 17 skipped (Panda3D/display unavailable), 276.924 seconds. The subsequently added Dijkstra reference regression also passed in the five-test focused run.
- Independent review: no correctness blockers; 2,000 reference route comparisons and cold concurrent queries checked. Minor deferred: permanent cold-start concurrency regression (recorded in handoff).
- Ruling: preserve Python transit itinerary/schedule and synchronous gameplay calls for this graph migration. Native queries are immutable and release the GIL; asynchronous economy scheduling remains a separate change. Cost if insufficient: large decision batches can still block the caller, to be measured by the Arcata workday.
- Handoff includes the earlier resource changes and stress harness; full Arcata day deliberately left for Codex as requested.
