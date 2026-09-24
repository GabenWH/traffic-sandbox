# Shared City Road Vehicles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move construction trucks into the city road vehicle simulation so every city road user shares movement and right-of-way rules.

**Architecture:** Generalize the existing routed test traffic actor and simulation to admit vehicles from any supported mobility route. Construction retains dispatch and delivery accounting, while one shared traffic simulation owns all road motion and reports arrivals. The app renders cars and trucks from that shared state.

**Tech Stack:** Python 3, unittest, Tkinter, Panda3D view adapters.

**Spec:** `docs/superpowers/specs/2026-09-24-shared-road-vehicles-design.md`

## Global Constraints

- Preserve the existing 20 simulated second shared regional departure interval.
- Preserve the current uncommitted construction, west port, and visual work in this linked worktree.
- Keep the city traffic source tool's enabled junctions independent from construction dispatch.
- Material and crew deliveries apply only on route completion.

## Review Focus

- West access occupied at departure time: keep the trip pending and reserve its cargo without overlap.
- A truck behind a car, a car behind a truck, and two trucks in one lane: maintain bumper clearance.
- Truck at an all-way stop or merge: use the same coordinator and right-of-way decision as cars.
- Clearing traffic or loading a world: remove road actors and construction reservations together.
- Large elapsed updates and high simulation speed: preserve departure spacing and arrival order.

---

### Task 1: Admit arbitrary routed road vehicles

**Files:** `traffic_testbed.py`, `tests/test_traffic_testbed.py`

**Interfaces:** Add a route admission method accepting a mobility route, actor identity, kind, speed cap, length, and width. It returns the routed actor only if entry clearance permits. Existing test traffic spawning uses the same method. Expose the existing simulation as the generic city road vehicle simulation while retaining compatibility names.

- [ ] Write a failing behavior test: admit a truck on a lane with a car ahead, confirm both actors occupy the same simulation and preserve clearance when advanced.
- [ ] Run the focused test and confirm the missing admission API fails.
- [ ] Add the route admission API and per-actor metadata; route generated test cars through it.
- [ ] Run focused traffic tests and inspect the output.

### Task 2: Delegate truck motion to road traffic

**Files:** `construction.py`, `tests/test_construction_simulation.py`

**Interfaces:** Construction accepts the shared road simulation. A successful departure admits a road actor associated with the trip. `update()` advances that single road simulation, applies completed delivery vehicles, and returns completed construction trips. Construction trip position and heading mirror its road actor while in transit.

- [ ] Write a failing integration test: a queued delivery enters the shared simulation, waits behind an existing car, and applies cargo only after its road actor reaches the building.
- [ ] Run the focused test and confirm the current independent truck movement fails it.
- [ ] Replace construction's distance advancement with shared traffic admission and completion handling; keep pending reservations and 20 second spacing.
- [ ] Run construction and traffic tests; adjust existing assertions that assumed constant speed movement.

### Task 3: Use the shared city simulation in the app

**Files:** `ui/app.py`, `ui/renderer.py`, `ui/interactions.py`, `ui_tools/tools/test_traffic_tool.py`, `ui/view3d.py`, `tests/test_construction_presentation.py`

**Interfaces:** The app passes its road simulation to construction and advances it once per tick. Car and truck visuals select the correct actor kind. Clear and reset actions remove the appropriate road actors and construction trips together.

- [ ] Write a failing presentation or app orchestration test proving a truck road actor is drawn once in truck style and clearing traffic removes its trip.
- [ ] Run the focused test and confirm the current double ownership fails it.
- [ ] Connect app update, completion cleanup, 2D and 3D filtering, and clear/reset behavior.
- [ ] Run focused presentation and UI tests.

### Task 4: Reduce truck body sizes and verify the integration

**Files:** `ui_tools/construction_resources.json`, relevant construction and traffic tests.

**Interfaces:** Reduce both catalog truck lengths and widths about ten percent and pass those exact values into traffic clearance and rendering.

- [ ] Inspect current catalog dimensions and edit only the two truck body sizes.
- [ ] Run the construction, traffic, routing, and presentation tests.
- [ ] Run the full test suite, using a virtual display if available, and report any environment-only failures.
- [ ] Review the final diff against every requirement in the spec.
