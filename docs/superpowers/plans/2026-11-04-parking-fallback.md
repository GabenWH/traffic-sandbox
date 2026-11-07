# Parking Fallback Implementation Plan

**Goal:** Resolve parking-constrained trips and remove repeated work on idle vehicles.
**Architecture:** Existing native traffic and walking remain authoritative. Python
keeps indexed capacity, explicit multimodal trip legs, and event-driven wait queues.
**Tech Stack:** Python 3 / C++17; existing unittest suite.
**Spec:** `docs/superpowers/specs/2026-11-04-parking-fallback-design.md`

## Global constraints
Finite real spaces; reserve before departure; no duplicate actors or claims;
stationary delivery trucks remain physical obstacles; persistence and resource
conservation must hold. No remote writes are required for implementation.

## Review focus
- A full shared lot admits only one waiter when one suitable space is released.
- Return legs retrieve the original car, including after save/load or road edits.
- Failed dispatch leaves parking/obstacle occupancy intact.
- Inaccessible parking and missed deadlines have explicit outcomes.
- Idle processing does not iterate the full vehicle/waiter population.

## Tasks
- [x] 1. Fleet indexes (`persistent_fleet.py`, tests): demonstrate idle scans;
  introduce active/occupancy indexes and capacity-release events; preserve claims.
- [x] 2. Parking access (`parking_access.py`, tests): add finite
  curbside spaces, separate fleet endpoints, and bounded nearby public candidates.
- [x] 3. Trip resolution (`parking_trips.py`, `city_simulation.py`, service hooks,
  `commute_schedule.py`, tests): test full/inaccessible lots, implement drive-walk
  and return retrieval, mode fallback, capacity wakes and explicit missed trips.
- [x] 4. Truck stops (native engine/wrappers, helper, fleet hooks, tests): reproduce
  undersized-bay failure, implement stationary occupancy and atomic departures.
- [x] 5. Persistence/diagnostics (`gameplay_persistence.py`, benchmark tool, tests):
  round-trip multimodal/wait/stop state; expose reasons and destination wait times.
- [x] 6. Integration: full suite, bounded behavior scenario, controlled idle scaling,
  independent review, fixes and local commits; deliver a usable patch and evidence.

Each behavior change follows failing regression test -> implementation -> passing
focused tests. Root integrates shared boundaries; each worker owns distinct files.
