# Unified Town Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make authored buildings operate as one persistent city with households, services, transport and housing decisions.

**Architecture:** Extend Building declarative operations and reuse ServiceTown, TransitSimulation and PersistentFleet. CitySimulation schedules decisions separately from native movement and attaches its snapshot to world persistence.

**Tech Stack:** Python dataclasses/Tkinter, JSON templates/saves, existing C++ traffic ABI.

**Spec:** docs/superpowers/specs/2026-10-28-unified-town-design.md

## Global Constraints
- Only native active movement uses <=0.05-second substeps.
- Existing Building inventory and construction lifecycle remain authoritative.
- No population or resource creation through relocation; capacities and occupancy are distinct.
- Housing memory changes over simulated years, outside movement ticks.
- Cars, buses, trucks and walkers share one native engine and clock.

## Review Focus
- Partially built and disconnected buildings must remain safe and inactive until usable.
- Multiple households compete for a vacancy without exceeding capacity or duplicating resources.
- Road edits and clear-traffic operations must retain logical people, fleet and cargo.
- Save/load during trips, service queues and relocation must retain identity and progress.
- Chunked updates and repeated days must preserve clocks, schedules and accounting.

### Task 1: Placed operational buildings
Files: city.py, building_operations.py, ui_tools/buildables.py, ui_tools/buildables.json, ui_tools/tools/road_tool.py, persistence.py; tests/test_city_gameplay.py.
Interfaces: Building.operation: dict, Building.occupants: int, CityMap.gameplay_state: dict|None; validate_operation(data)->dict.
- [x] Add failing tests for cafe placement through BuildingTool, construction gating and operation save/load.
- [x] Add declarative roles and validate finite recipe/quality/rate data; preserve legacy worlds.
- [x] Run python -m unittest tests.test_city_gameplay tests.test_buildables tests.test_persistence; commit.

### Task 2: Households and scheduled city coordination
Files: households.py, city_simulation.py, town_services.py, town_simulation.py, construction.py, transit.py; tests/test_city_gameplay.py, tests/test_households.py.
Interfaces: CitySimulation(city, traffic=None, construction=None), update(seconds), sync_buildings(), invite_household(home_id,size), create_line(stop_ids), commission_truck(site_id), assess_household(id), snapshot(); HousingMemory.value_at(time), Household.
- [x] Add failing tests for yearly memory response, inactivity across frames, construction activation, vacancies, repeat commutes and identity-preserving capacity-reserved moves.
- [x] Integrate shared transport/arrival observation and coarse economic/construction events, reusing service/fleet code.
- [x] Add household-specific accessibility, safe relocation and explicit population admission; test resources, cars and competing households.
- [x] Verify focused city/household/transit/construction tests; commit.

### Task 3: Resumable city state
Files: gameplay_persistence.py, city_simulation.py, persistence.py, native/traffic/engine.cpp, native/traffic/engine.h, native_traffic.py; tests/test_city_gameplay.py.
Interfaces: dump_transport(transit)->dict, restore_transport(transit,data), CitySimulation.from saved city.gameplay_state.
- [x] Test active walks, cars, buses, inventories, queued visits and relocation through a JSON world round trip.
- [x] Serialize route geometry references, actor progress and logical service/fleet state. Rebind safely after edits without losing actors.
- [x] Validate snapshots and reject incompatible references before changing a running world; verify resumed runs; commit.

### Task 4: Application tools and verification
Files: ui/app.py, ui/files.py, ui/renderer.py, ui_tools/tools/transit_tool.py, ui_tools/tools/simulation_tool.py, ui_tools/tools/inspect_tool.py, ui_tools/toolbar.json, docs/GAMEPLAY.md; tests/test_city_gameplay_ui.py, tools/run_city_gameplay.py.
Interfaces: app.city_simulation, BusRouteTool.finish(), gameplay commands and inspector summary.
- [x] Test real app update/commands with a headless host and shared road engine; implement build-menu cafe/housing, invitations, truck and bus-line controls.
- [x] Draw active walkers/stops/queues and show household/operation data in inspector. Save/load/new-world bind one runtime.
- [x] Run a recorded authored-city scenario, multi-year empty-town scheduling benchmark, full unittest discovery and fresh whole-branch review.
- [x] Address important review findings with regression tests, document defaults and practical limits; commit and report.
