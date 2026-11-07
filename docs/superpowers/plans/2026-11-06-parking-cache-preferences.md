# Parking cache repair and preference scaffolding implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement the tasks inline, with a final independent review.

**Goal:** Reduce retained walking-path graphs and scaffold next-day commute preferences without enabling mode changes.

**Architecture:** Preserve the existing lazy parking baseline. Add a bounded walking-path cache and compact native pedestrian registry keys, then add event-time experience recording and JSON persistence.

**Tech Stack:** Python, existing C++ walking/traffic engine, unittest.

**Spec:** docs/superpowers/specs/2026-11-06-parking-cache-preferences-design.md

## Global Constraints

- Current mode selection and parking reservations remain unchanged.
- GC stays enabled and the movement quantum remains 0.05 seconds.
- Preference observations affect no current-trip decision; prior-day access excludes today's observations.
- Existing saved point geometry stays compatible; old saves need no preferences block.
- Work in this isolated checkout and do not overwrite the concurrently edited source checkout or push GitHub.

## Review Focus

- Cache eviction must preserve live walkers and native route deduplication across save/load.
- Geometry-heavy single routes must not bypass retention limits.
- Repeated failures, return journeys, and shopping must not create misleading commute experience.
- Home/work changes must not inherit unrelated parking experience.
- Save/load must reject malformed values and preserve neutral preferences without changing behavior.

### Task 1: Bound retained walking geometry

Files: walking_cache.py, transit.py, gameplay_persistence.py, tests/test_walking_retention.py.

- [x] Add real-route tests that fail on unbounded retention and GC-tracked route-registry geometry.
- [x] Implement `WalkingRouteCache(max_entries=512, max_units=65536)` and exact binary geometry keys/codecs. Run the tests green.
- [x] Add capacity/oversize tests and active-walker save/restore/arrival checks; verify weighted bounds.
- [x] Commit the performance change, recording actual tests and limits.

### Task 2: Add inactive preferences and prior-day parking memory

Files: commute_preferences.py, parking_trips.py, tests/test_commute_preferences.py.

- [x] Add tests for tomorrow-only observations, day/route scoping, neutral profiles, JSON roundtrip and legacy snapshots, and real overflow recording with today's mode unchanged.
- [x] Implement `CommutePreferences` with immutable neutral `ModePreferences`, bounded experiences, validation, and snapshot/restore. Hook recording into outbound parking recalibration only.
- [x] Verify new and existing parking/persistence tests. Commit the scaffold.

### Task 3: Verify and deliver

- [x] Run the complete unittest suite; report every failure or skip.
- [x] Measure controlled Arcata route retention/collector cost on this version; distinguish the cold startup, explicit collection probes and natural update measurements.
- [x] Request one independent review, fix material findings with regressions, and rerun affected checks plus the full suite when warranted.
- [x] Deliver the tested local branch and patch with performance limits and the inactive preference scope stated plainly.
