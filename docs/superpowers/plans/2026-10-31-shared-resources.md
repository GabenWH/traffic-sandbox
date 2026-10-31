# Shared Resources Implementation Plan

> Use superpowers:executing-plans to implement task by task.

**Goal:** Unify resource mechanics and add resident shopping and construction labor.
**Architecture:** Existing inventories remain authoritative. Shared stock and load
operations serve construction and consumer logistics; movement stays native.
**Tech Stack:** Python gameplay, existing C++ movement, unittest.
**Spec:** docs/superpowers/specs/2026-10-31-shared-resources.md

## Constraints and review focus
Preserve saves, active cargo, finite stock, no duplicated demand, event-driven labor.
Test failed routes, simultaneous delivery/shopping, mid-trip saves, shift boundaries,
and construction completion while workers are present.

## Task 1: Shared resource operations
- [x] Add failing tests for stock transfers, recipe limits, shortages and load limits.
- [x] Implement shared operations in models.py/resources.py; use them in construction
      and consumer production/logistics without changing transport ownership.
- [x] Run lifecycle, construction and service tests.

## Task 2: Shopping
- [x] Add failing integration tests for pickup/return, inbound suppression and saves.
- [x] Add shopping to ServiceTown visits; select trips in CitySimulation logistics.
      Use visits as the persisted reservation/cargo record; account for it in reports.
- [x] Run gameplay, service and recovery tests.

## Task 3: Resident labor
- [x] Add failing tests for construction attendance and leaving work.
- [x] Expose construction jobs, update labor at events, prevent regional crew spawning
      in city mode, and settle work before staffing changes.
- [x] Run relevant and full unittest discovery; review and commit the feature branch.


## Task 4: Construction company clarification
- [x] Add a buildable construction company and permanent workplace/temporary worksite IDs.
- [x] Dispatch arrived employees, return via employer, preserve parked cars and saved trips.
- [x] Keep bootstrap until housing and company exist; persist the switch to resident labor.
- [x] Test blocked dispatch/return, shopping-to-car mode changes, and restored-trip continuation.

## Validation and review
Final command: `python -m unittest discover -s tests -v`.
Result: 606 tests run in 293.717 seconds; 589 passed, 17 skipped for missing Panda3D/display.
`git diff --check` passes.

Independent reviews identified and regression tests verified fixes for:
- Missed shift departure after shopping and invalid direct shopping visits.
- Construction dispatch time lost during labor settlement.
- Personal-car arrival leaving a stale pedestrian destination.
- Missing retry after temporarily blocked builder dispatch.

Decisions: preserve persistent local freight and regional transport adapters while
sharing stock/recipe/demand/load mechanics; preserve portion-based scenario units;
use walking/transit for company-to-site travel; keep the existing coarse Python
scheduler and C++ movement. Road-demolition crews remain regional. These limits are
recorded in the spec and user-facing resource guide.
