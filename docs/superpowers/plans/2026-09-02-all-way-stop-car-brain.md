# All-Way Stop Car Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an inspectable car-owned behavior layer and working all-way stops to constructed-road test traffic.

**Architecture:** A `CarBrain` chooses desired motion from immutable route progress and shared stop-control observations. A runtime `AllWayStopCoordinator` records arrivals and movement claims without controlling vehicle motion; `TestTrafficSimulation` orchestrates perception, decisions, and advancement.

**Tech Stack:** Python 3 dataclasses, Tkinter canvas/Inspector, `unittest`, existing mobility and persistence models.

**Spec:** `docs/superpowers/specs/2026-09-02-all-way-stop-car-brain-design.md`

## Global Constraints

- Cars choose when to go; intersections never command or advance cars.
- Keep the legacy freeway simulation unchanged.
- Use only the Python standard library.
- Traffic signals, roundabouts, lane changing, and personalities are out of scope.

---

### Task 1: Route-aware car state and brain decisions

**Files:**
- Create: `car_brain.py`
- Modify: `traffic_testbed.py`
- Test: `tests/test_car_brain.py`

**Interfaces:**
- Produces: `BehaviorState`, `CarObservation`, `CarDecision`, and `CarBrain.decide(observation, dt)`.
- Produces: route-segment progress on `RoutedTestCar`, including the next/current `LaneConnection`.
- Consumes: existing `Path`, `MobilityLink`, and `LaneConnection` values.

- [ ] Write failing tests proving a spawned routed car owns a brain, exposes its current route link, and transitions from cruising to approaching a stop-controlled connection.
- [ ] Run `python3 -m unittest tests.test_car_brain -v` and confirm the new imports or assertions fail.
- [ ] Add focused brain dataclasses/enums and route-edge distance bookkeeping; keep rendering-compatible `position`, `heading`, `distance`, and `points` fields.
- [ ] Run the focused tests and existing `tests.test_traffic_testbed` until they pass.

### Task 2: All-way-stop arrival and claim coordinator

**Files:**
- Create: `intersection_controls.py`
- Test: `tests/test_intersection_controls.py`

**Interfaces:**
- Produces: `AllWayStopCoordinator.observe_stop(car_id, connection, time)`, `can_claim(...)`, `claim(...)`, `release(...)`, and `forget_car(...)`.
- Consumes: `LaneConnection.source_output.heading` to compute clockwise approach order.

- [ ] Write failing tests for first-arrival priority, simultaneous clockwise ordering, deterministic car-ID fallback, exclusive active claims, release, and stale-car cleanup.
- [ ] Run `python3 -m unittest tests.test_intersection_controls -v` and confirm failure.
- [ ] Implement runtime-only arrival/claim records grouped by intersection ID. Treat arrivals within `1e-6` seconds as simultaneous and sort their normalized incoming approach angles clockwise, then car ID.
- [ ] Run the focused tests until they pass.

### Task 3: Stop, wait, enter, and clear behavior

**Files:**
- Modify: `car_brain.py`
- Modify: `traffic_testbed.py`
- Test: `tests/test_car_brain.py`
- Test: `tests/test_traffic_testbed.py`

**Interfaces:**
- Consumes: coordinator observation/claim API from Task 2.
- Produces: car brain states `cruising`, `approaching_stop`, `stopped`, `waiting_for_priority`, `entering_intersection`, and `clearing_intersection`, plus `wait_reason` and `desired_speed`.

- [ ] Add failing integration tests showing a car brakes before the stop line, dwells for 0.5 simulated seconds, waits when another car owns priority, claims its own movement, and releases after leaving the connection.
- [ ] Add a failing same-route queuing test proving a following car retains a safe gap.
- [ ] Run both focused test modules and confirm the behavioral assertions fail.
- [ ] Update `TestTrafficSimulation.update()` to build observations, call each car brain, apply bounded acceleration/deceleration, advance route progress, and clean coordinator state when cars finish or are cleared.
- [ ] Run both focused modules until they pass.

### Task 4: Author and persist all-way stops

**Files:**
- Modify: `models.py`
- Modify: `ui_tools/tools/inspect_tool.py`
- Test: `tests/test_city.py`
- Test: `tests/test_persistence.py`
- Test: `tests/test_inspect_tool.py`

**Interfaces:**
- Produces: `Intersection.is_all_way_stop` and `Intersection.set_all_way_stop(enabled)`.
- Consumes: existing `ControlDefinition(ControlType.STOP)` and persistence of each lane connection.

- [ ] Write failing model tests showing the setter applies STOP to every standard movement, disabling restores UNCONTROLLED, and cul-de-sacs reject all-way-stop configuration.
- [ ] Write failing Inspector-row tests for reading and editing the all-way-stop field.
- [ ] Run the focused tests and confirm failure.
- [ ] Implement model helpers and Inspector editing with accepted boolean/control strings; trigger world redraw after editing.
- [ ] Extend persistence round-trip coverage and run all focused tests.

### Task 5: Stop-line and brain debugging surfaces

**Files:**
- Modify: `ui/renderer.py`
- Modify: `ui/interactions.py`
- Modify: `ui/dashboards.py`
- Modify: `ui_tools/tools/inspect_tool.py`
- Test: `tests/test_traffic_testbed.py`
- Test: `tests/test_inspect_tool.py`

**Interfaces:**
- Consumes: intersection control helpers and public `RoutedTestCar.brain` fields.
- Produces: stop-line canvas items, routed-car hit testing/inspection, and routed-car debug text.

- [ ] Write failing fake-canvas tests for stop-line drawing and routed-car selection/inspection rows.
- [ ] Run focused UI tests and confirm failure.
- [ ] Draw stop bars at controlled incoming ports, add routed-car hit testing, expose brain rows, and append compact routed-car lines to the debug dashboard.
- [ ] Run focused UI tests until they pass.

### Task 6: Full regression and documentation correction

**Files:**
- Modify: `README.md`
- Modify: `docs/TOOLS.md`
- Modify: `docs/ROUTING.md`

**Interfaces:**
- Documents the implemented behavior and debug controls without claiming support for signals or legacy-car migration.

- [ ] Update documentation to describe all-way-stop authoring, car-brain behavior/debugging, and explicit limitations.
- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `python3 -m py_compile car_brain.py intersection_controls.py traffic_testbed.py models.py ui/*.py ui_tools/tools/*.py`.
- [ ] Review `git diff --check` and the final diff for unrelated changes; fix only issues introduced by this feature.
