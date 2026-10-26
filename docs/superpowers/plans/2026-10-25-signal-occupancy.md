# Signal Occupancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace signal reservations with entry permission and measure correctness and runtime against main fa6fe820.

**Architecture:** Keep stop/yield claims. Observe signal occupants only after physical entry, ignoring same-approach followers when checking conflicting occupancy. Share controller event timing and yellow decision semantics across both update modes.

**Tech Stack:** Python standard library and unittest.

**Spec:** docs/superpowers/specs/2026-10-25-signal-occupancy-design.md

## Global Constraints
- No new runtime dependencies; retain both update modes and non-signal controls.
- Do not merge main without a user instruction.

## Review Focus
- Streams of cars sharing a green must overlap movement occupancy without overlapping bodies.
- Removing a car or rebuilding a network must remove its physical occupancy.
- Multiple scheduled requests pending before clearance use the latest requested plan.
- Separate controllers at one junction cannot display conflicting protected greens.
- Event subdivision and yellow decisions must not become stale at chained junctions.

## Task 1: Behavioral regression suite
- [x] Add tests/test_signal_occupancy.py for platoons, pre-entry red, yellow braking, opposing clearance, schedules, substep timing, fail-closed IDs, red deadlock and removal.
- [x] Run on baseline and record expected failures before product changes.

## Task 2: Signal rewrite
- [x] Modify intersection_controls.py: safe effective schedules, next_boundary_after(time), separately observed signal occupants and entry conflict checks.
- [x] Modify car_brain.py: signal_entry_allowed decision, latched yellow decision, no signal claim request.
- [x] Modify traffic_testbed.py: cached aspects per tick, controller event splitting, physical occupancy observation and signal entry integration in both engines, no signal deadlock candidates.
- [x] Update obsolete reservation expectations in tests/test_signalized_intersections.py and document behavior in docs/JUNCTIONS.md.
- [x] Run signal and full regression suites; correct failures.

## Task 3: Comparison and review
- [ ] Add tools/compare_signal_systems.py for seeded identical demand, counterbalanced process runs, frozen-state CPU comparison, throughput, queue, overlaps, and entry metrics.
- [ ] Run old/new benchmarks and save machine-readable and human-readable results under docs/analysis.
- [ ] Review the complete diff, test all important findings, commit and publish the isolated feature branch.

## Verification ledger
- Baseline main fa6fe820: 330 tests run, 17 skipped, no failures.
- Task 1: baseline failed 20 regression subcases before product changes.
- Task 2: signal regressions passed; full suite passed 346 tests with 17 skips.
- Independent review found same-batch signal/yield entry, decimal event rounding,
  and cross-controller yellow/green conflicts. Each has a failing regression
  followed by a passing fix. Signalized merge projection and speed-plan retention
  were also checked with failing-then-passing tests. Full suite remained green.
- Ruling: Yellow uses comfortable stopping distance with no added reaction-time
  calibration. This retains the existing deterministic driver model; human
  reaction variability remains outside the comparison.
- Ruling: Protected green/yellow permissions that geometrically conflict across
  controllers are configuration errors. Mixed signal and yield arbitration
  rechecks new signal entry after ordinary claims resolve.
- Ruling: Use 32/64/128 cars for the fixed-load comparison, matching the 128-car
  cap used by paired flow runs. The unrequested 256-car stress case was excluded
  because its legacy update cost dominated runtime.
