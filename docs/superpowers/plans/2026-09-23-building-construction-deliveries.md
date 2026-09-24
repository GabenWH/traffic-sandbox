# Building Construction Deliveries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Place new buildings as construction projects and satisfy their material and worker needs using routed deliveries from an unlimited virtual provider.

**Architecture:** Keep resource identity and physical properties in data-driven `ResourceSpec` entries, independent of providers. A construction simulation asks an unlimited virtual provider at the west road gate to dispatch material or crew trips over `CityMap`'s existing mobility graph, records delivered amounts and assigned workers on buildings, and advances the existing `WorkOrder` lifecycle. Trips are runtime-only; building demand, deliveries, crews, and work progress persist.

**Tech Stack:** Python 3, dataclasses, JSON catalogs, existing `CityMap`/`mobility.py` route graph, Tkinter canvas, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-23-building-construction-needs-design.md`

## Global Constraints

- The initial provider is non-placeable and unlimited; do not add provider stock, production, a finite truck fleet, or a separate economy state.
- Resource IDs and physical properties are supplied as data and remain independent of their provider; optional `visual_key` values connect future supplied art.
- Each material shipment carries exactly one material.
- Material load amount is `min(remaining_need, truck_max_weight / resource_weight_per_unit, truck_max_volume / resource_volume_per_unit)`.
- Starter resource and truck values make each starter material need take at least two shipments; larger or heavier needs can require more.
- Subtract in-transit commitments before dispatching so concurrent trips cannot over-deliver.
- Worker trucks carry at most their configured crew capacity. Delivered workers stay assigned until construction completes.
- Work starts only when all required material and workers are on site. Construction progress is `assigned_workers * elapsed_simulation_seconds`, measured in worker-seconds.
- A provider gate must attach to the west map-edge road network. Building access is a virtual roadside lane position; a cul-de-sac is not required for a building.
- Missing routes leave demand pending and retried after the road network changes.
- Trips are runtime-only. Delivered material, construction requirements, assigned worker count, phase, and work progress persist; trips are regenerated after load.
- Do not add depots, mines, quarries, factories, processing chains, a workforce market, or ongoing economic inputs/outputs.

## Review Focus

- A construction template references a resource ID absent from the supplied catalog; reject it with a catalog error instead of failing during dispatch. Pin this in Task 2.
- A resource has zero/non-finite mass or volume, or a truck has invalid capacities; reject it before load division. Pin this in Task 2.
- The provider has no west-edge gate, a building has no nearby road lane, or all lane directions are unreachable; keep demand pending and retry after roads connect. Pin this in Task 3.
- Several simulation ticks occur before a truck arrives; reserve in-transit cargo so they do not dispatch duplicate loads. Pin this in Task 3.
- A save occurs during partial delivery or active work; restore delivered quantities and crews, then regenerate only missing trips. Pin this in Task 5.

---

### Task 1: Add construction demand to building templates and lifecycle state

**Files:**
- Modify: `models.py` — add persistent construction worker/work counters to `Buildable`.
- Modify: `ui_tools/buildables.py` — validate the new building template fields.
- Modify: `ui_tools/buildables.json` — define workers and worker-seconds for each building.
- Modify: `ui_tools/tools/road_tool.py:BuildingTool.place_building` — initialize the building as under construction and copy template requirements.
- Test: `tests/test_buildable_lifecycle.py`
- Test: `tests/test_buildables.py`

**Interfaces:**
- Produces `Buildable.construction_workers: int`, `Buildable.construction_work: float`, `Buildable.assigned_workers: int`, and `Buildable.construction_delivered: dict[str, float]`.
- Produces `Buildable.record_construction_delivery(resource_id: str, amount: float) -> None`, which adds material to inventory and increments the cumulative delivered counter while rejecting unknown resources and over-delivery.
- Existing `Buildable.begin_work(WorkType.CONSTRUCTION, required_work)` remains the operation that consumes all required material and creates the active `WorkOrder`.

- [ ] **Step 1: Write failing tests for template requirements and placement phase**

Add tests asserting that every building template has positive `construction_workers` and `construction_work`, and that `BuildingTool.place_building()` copies them, sets `phase` to `BuildablePhase.UNDER_CONSTRUCTION`, leaves `active_work` unset, and starts with zero assigned workers and no delivered resources.

```python
building = tool.place_building((100, 120))
assert building is not None
self.assertEqual(building.phase, BuildablePhase.UNDER_CONSTRUCTION)
self.assertIsNone(building.active_work)
self.assertGreater(building.construction_workers, 0)
self.assertGreater(building.construction_work, 0)
self.assertEqual(building.assigned_workers, 0)
self.assertEqual(building.construction_delivered, {})
```

Also assert that `record_construction_delivery("lumber", 5)` updates both inventory and cumulative delivered quantities, while an unknown resource or amount above the remaining need raises `ValueError`.

- [ ] **Step 2: Run focused tests and confirm the new expectations fail**

Run: `python3 -m unittest discover -s tests -p 'test_buildables.py' -v`

Expected: FAIL because templates/model do not yet expose worker/work requirements and placement leaves the phase in planning.

- [ ] **Step 3: Add and validate the building requirement fields**

Add the four state fields to `Buildable` with empty/zero defaults. Validate `construction_workers` as a positive integer and `construction_work` as a positive finite number for building specs. Give every building in `ui_tools/buildables.json` starter values. In `BuildingTool.place_building()`, copy those values and pass `phase=BuildablePhase.UNDER_CONSTRUCTION`.

```python
construction_workers: int = 0
construction_work: float = 0.0
assigned_workers: int = 0
construction_delivered: dict[str, float] = field(default_factory=dict)
```

Add `record_construction_delivery()` so automated trips and the existing Inspector helper share one accounting path:

```python
remaining = self.construction_needs.get(resource_id, 0.0) - self.construction_delivered.get(resource_id, 0.0)
if amount <= 0 or amount > remaining:
    raise ValueError("Construction delivery must fit the outstanding need")
self.add_resource(resource_id, amount)
self.construction_delivered[resource_id] = self.construction_delivered.get(resource_id, 0.0) + amount
```

Pass the template requirements when constructing the new `Building`:

```python
building = Building(
    name=building_name,
    parcel=parcel,
    construction_needs=dict(details["construction_needs"]),
    construction_workers=int(details["construction_workers"]),
    construction_work=float(details["construction_work"]),
    phase=BuildablePhase.UNDER_CONSTRUCTION,
)
```

Use these starter crew/work values in `ui_tools/buildables.json`; work is measured in worker-seconds:

| Building template | Workers | Work |
| --- | ---: | ---: |
| `small_house` | 2 | 180 |
| `apartment_building` | 4 | 960 |
| `corner_shop` | 3 | 450 |
| `office_building` | 6 | 2400 |
| `factory` | 6 | 3600 |

- [ ] **Step 4: Run focused tests and confirm they pass**

Run: `python3 -m unittest discover -s tests -p 'test_buildables.py' -v`

Expected: PASS, including existing resource-delivery and building-placement coverage.

- [ ] **Step 5: Run lifecycle tests**

Run: `python3 -m unittest discover -s tests -p 'test_buildable_lifecycle.py' -v`

Expected: PASS; defaults keep existing road/buildable lifecycle behavior unchanged.

- [ ] **Step 6: Commit building construction requirements**

```bash
git add models.py ui_tools/buildables.py ui_tools/buildables.json ui_tools/tools/road_tool.py tests/test_buildable_lifecycle.py tests/test_buildables.py
git commit -m "feat: add building construction requirements"
```

---

### Task 2: Define supplied resource and truck catalogs plus provider/access contracts

**Files:**
- Create: `resources.py` — validated `ResourceSpec`, `TruckSpec`, and catalog loading.
- Create: `ui_tools/construction_resources.json` — starter physical and visual-key data for lumber, stone, steel, material trucks, and crew trucks.
- Create: `construction.py` — provider/access types and helpers.
- Create: `tests/test_construction_catalog.py`
- Create: `tests/test_construction_access.py`
- Test: `tests/test_construction_catalog.py`
- Test: `tests/test_construction_access.py`

**Interfaces:**
- `ResourceSpec(id: str, name: str, unit: str, mass_kg_per_unit: float, volume_m3_per_unit: float, visual_key: str | None = None)`.
- `TruckSpec(id: str, payload_kg: float, cargo_m3: float, crew_capacity: int, length: float, width: float, visual_key: str | None = None)`; payload/volume/crew capacity may be zero when that truck cannot carry that payload type, but all capacities must be nonnegative and at least one payload type must be supported.
- `load_construction_catalog(path: str | Path | None = None) -> tuple[dict[str, ResourceSpec], dict[str, TruckSpec]]`.
- The catalog JSON has `version`, `resources`, and `trucks` keys; resource and truck arrays are converted to dictionaries keyed by their stable `id` values.
- `ConstructionCatalogError(ValueError)` reports malformed resource/truck data or duplicate IDs.
- `validate_resource_references(buildables: Iterable[BuildableSpec], resources: Mapping[str, ResourceSpec]) -> None` rejects building needs with unknown resource IDs.
- `provider_access_points(city_map: CityMap) -> tuple[VehicleRouteEndpoint, ...]` returns usable endpoints on roads meeting the west map edge.
- `building_access_points(city_map: CityMap, building: Building) -> tuple[LanePosition, ...]` returns nearest lane positions beside the parcel in each lane direction when the lane is no farther than twice its road's lane width from the parcel edge.
- `distance_from_parcel(parcel: Parcel, point: Point) -> float` returns the distance from a point to the parcel rectangle, or zero when the point falls inside it.
- `ConstructionProvider` exposes `id: str`, `access_points(city_map: CityMap) -> tuple[VehicleRouteEndpoint, ...]`, `available_material(resource_id: str) -> float`, `available_workers() -> float`, `reserve_material(resource_id: str, amount: float) -> bool`, and `reserve_workers(count: int) -> bool`.
- `UnlimitedConstructionProvider` implements that contract with a stable ID, west-edge access points, unlimited availability, and successful reservations.

- [ ] **Step 1: Write failing tests for resource/truck validation and catalog loading**

Cover valid JSON loading, duplicate IDs, blank IDs/units, non-finite or non-positive resource mass/volume, invalid truck payload/dimensions, and negative crew capacity. Allow `crew_capacity == 0` for material-only trucks. Also test that every resource named by a building's `construction_needs` exists in the loaded catalog.

```python
with self.assertRaisesRegex(ConstructionCatalogError, "mass_kg_per_unit"):
    ResourceSpec("stone", "Stone", "t", 0.0, 1.0)
```

- [ ] **Step 2: Run the catalog tests to confirm they fail**

Run: `python3 -m unittest discover -s tests -p 'test_construction_catalog.py' -v`

Expected: FAIL because catalog types and loader do not exist.

- [ ] **Step 3: Implement resource/truck dataclasses and JSON loading**

Validate physical values before dispatch math, reject duplicate IDs, and load the starter values from JSON rather than hard-coding resource names or capacities in the dispatcher. Include optional `visual_key` fields; use neutral starter keys that can later be replaced by supplied art without changing simulation data.

Seed the JSON catalog with lumber measured in cubic metres (`500 kg` and `1 m³` per unit), stone measured in tonnes (`1000 kg` and `0.5 m³` per unit), and steel measured in tonnes (`1000 kg` and `1 m³` per unit). Give the material truck `7500 kg` payload, `10 m³` cargo volume, and zero crew capacity; give the crew truck zero material capacity and capacity for `3` workers. Give them lengths of `18` and `20` map units and widths of `8` map units. These values make the smallest starter need take two material loads: lumber is volume-limited, while stone and steel are weight-limited. Keep all values in JSON so supplied specifications can replace them later.

Keep validation at the data boundary so zero values cannot reach the load formula:

```python
if not isfinite(self.mass_kg_per_unit) or self.mass_kg_per_unit <= 0:
    raise ConstructionCatalogError("mass_kg_per_unit must be positive and finite")
if not isfinite(self.volume_m3_per_unit) or self.volume_m3_per_unit <= 0:
    raise ConstructionCatalogError("volume_m3_per_unit must be positive and finite")
```

For `TruckSpec`, require finite nonnegative payload capacities, a nonnegative integer crew capacity, positive finite dimensions, and at least one supported payload type; material dispatch requires both weight and volume capacity.

Add a catalog test that computes the maximum material amount per load from the JSON specs and confirms it is smaller than every matching starter building requirement, so each starter material takes at least two trips.

- [ ] **Step 4: Add failing access tests for provider gates and roadside buildings**

Use a `CityMap` with a two-way road touching `x == 0` and verify it exposes the boundary cul-de-sac as a provider endpoint. Put buildings next to each side of the road and verify lane positions are found in both directions. In a separate map, verify a one-way lane entering at `x == 0` is returned as a `LanePosition` gate. Verify a building farther than twice the road lane width from a lane has no access point.

```python
starts = provider_access_points(city)
accesses = building_access_points(city, building)
self.assertTrue(starts)
self.assertEqual({item.lane.direction for item in accesses}, {"forward", "reverse"})
```

- [ ] **Step 5: Run the access tests to confirm they fail**

Run: `python3 -m unittest discover -s tests -p 'test_construction_access.py' -v`

Expected: FAIL because construction access discovery is not implemented.

- [ ] **Step 6: Implement provider and building access discovery**

Use existing `CityMap.intersections`, `LanePosition`, `nearest_lane_position()`, and `CityMap.find_vehicle_route_between()`. Include west-edge lane endpoints for one-way roads; do not assume every valid provider gate has a cul-de-sac. For building access, measure from the parcel rectangle to the nearest point on each lane and return candidates no farther than twice that road's `lane_width`.

Represent endpoints with the existing `VehicleRouteEndpoint` alias and test building frontage against lane geometry:

```python
parcel_center = (
    building.parcel.x + building.parcel.width / 2,
    building.parcel.y + building.parcel.height / 2,
)
for road in city_map.roads:
    for lane in road.lanes:
        lane_position, _ = nearest_lane_position(lane, parcel_center)
        if distance_from_parcel(building.parcel, lane_position.point) <= 2.0 * road.lane_width:
            candidates.append(lane_position)
```

- [ ] **Step 7: Run catalog and access tests**

Run: `python3 -m unittest discover -s tests -p 'test_construction_*.py' -v`

Expected: PASS for valid supplied specs, rejected invalid capacities, boundary gates, and roadside access in both directions.

- [ ] **Step 8: Commit construction catalogs and access discovery**

```bash
git add resources.py construction.py ui_tools/construction_resources.json tests/test_construction_catalog.py tests/test_construction_access.py
git commit -m "feat: add construction resource catalogs and road access"
```

---

### Task 3: Schedule and advance construction material and crew trips

**Files:**
- Modify: `construction.py` — payload, trip, truck, and simulation behavior.
- Create: `tests/test_construction_simulation.py`
- Test: `tests/test_construction_simulation.py`
- Test: `tests/test_mobility.py` only if a route-endpoint integration regression needs a focused assertion.

**Interfaces:**
- `MaterialPayload(resource_id: str, amount: float)` and `CrewPayload(workers: int)` are mutually exclusive trip payloads.
- `ConstructionTrip` stores `id`, `provider_id`, `building_id`, `truck_id`, one payload, route points, traveled distance, and speed; `position: Point` interpolates the current position on the route.
- `CONSTRUCTION_TRUCK_SPEED = 90.0` world units per simulation second is the shared first-slice speed; the regional port allows one departure every `20.0` simulation seconds across material and crew trucks, with the first departure immediate.
- Material dispatch uses profiles with positive `payload_kg` and `cargo_m3`; crew dispatch uses profiles with positive `crew_capacity`. Zero-capacity fields exclude a profile from that payload type.
- `ConstructionSimulation(resources: Mapping[str, ResourceSpec], trucks: Mapping[str, TruckSpec], provider: ConstructionProvider, truck_speed: float = CONSTRUCTION_TRUCK_SPEED)` exposes active `trips`, queued `pending_trips`, and `update(city_map: CityMap, elapsed_seconds: float) -> tuple[ConstructionTrip, ...]`, returning trips completed during that update.
- `ConstructionSimulation._in_transit_material(building_id: str, resource_id: str) -> float` and `_in_transit_workers(building_id: str) -> int` total reserved payloads in active and queued trips.
- `ConstructionSimulation._best_route(city_map: CityMap, building: Building) -> Path[MobilityNode, MobilityLink] | None` checks provider gates and building lane accesses and returns the shortest reachable route.
- `ConstructionSimulation._make_trip(building: Building, truck: TruckSpec, payload: MaterialPayload | CrewPayload, route: Path[MobilityNode, MobilityLink]) -> ConstructionTrip` records the provider ID and flattened route geometry.
- `ConstructionSimulation._apply_delivery(trip: ConstructionTrip) -> None` calls `record_construction_delivery()` for material or updates assigned-worker state for crew, exactly once on arrival.
- `ConstructionSimulation._materials_complete(building: Building) -> bool` compares cumulative delivered amounts with `construction_needs`.
- `ConstructionSimulation.clear_trips() -> None` drops runtime deliveries when the app creates or loads a different world.
- `update()` advances work, arrivals, and shared-port departure events over simulation time so a long tick still spaces departures correctly. Demand is queued and reserved; each emitted truck begins moving exactly at its departure time.

- [ ] **Step 1: Write failing tests for weight/volume limited material dispatch**

Inject small fixture specs where one resource is weight-limited and another is volume-limited. Assert each trip contains one resource only, cargo amount follows the minimum of remaining amount and both capacities, and repeated updates dispatch exactly enough trips to cover the requirement.

```python
trip = simulation.trips[0]
assert isinstance(trip.payload, MaterialPayload)
self.assertEqual(trip.payload.resource_id, "stone")
self.assertLessEqual(trip.payload.amount * stone.mass_kg_per_unit, truck.payload_kg)
self.assertLessEqual(trip.payload.amount * stone.volume_m3_per_unit, truck.cargo_m3)
```

- [ ] **Step 2: Run the material scheduling test and confirm it fails**

Run: `python3 -m unittest discover -s tests -p 'test_construction_simulation.py' -v`

Expected: FAIL because no construction simulation or trip model exists.

- [ ] **Step 3: Implement material demand reservation and one-material trips**

For each building/material, compute `required - construction_delivered - in_transit_amount`. Recompute after each new trip and keep dispatching until all outstanding demand is reserved or no route/provider capacity is available. Keep per-trip payload single-material. Choose starter catalog capacities so every starter need requires at least two loads.

Use the same bounded formula for each reserved load:

```python
remaining = required - delivered - self._in_transit_material(building.id, resource.id)
load = min(
    remaining,
    truck.payload_kg / resource.mass_kg_per_unit,
    truck.cargo_m3 / resource.volume_m3_per_unit,
    self.provider.available_material(resource.id),
)
route = self._best_route(city_map, building)
if load > 0 and route is not None and self.provider.reserve_material(resource.id, load):
    self._make_trip(building, truck, MaterialPayload(resource.id, load), route)
```

In `update()`, repeat this calculation after each trip so the newly committed cargo reduces `_in_transit_material()`. Never reserve or dispatch if `_best_route()` returns `None`.

- [ ] **Step 4: Write failing tests for crew assignment, construction start, and release**

Test crew loads bounded by `crew_capacity`, workers remaining assigned while work runs, no work before every resource and required worker arrives, progress equal to `assigned_workers * elapsed_seconds`, and worker release when `perform_work()` completes the work order. Include the case where `begin_work()` consumes inventory and verify this does not trigger duplicate material trips. Test `clear_trips()` removes runtime reservations without changing delivered material or assigned workers.

- [ ] **Step 5: Run the crew/work tests and confirm they fail**

Run: `python3 -m unittest discover -s tests -p 'test_construction_simulation.py' -v`

Expected: FAIL because worker trips and construction orchestration are not implemented.

- [ ] **Step 6: Implement crew dispatch and construction progression**

Compute worker deficit as `construction_workers - assigned_workers - in_transit_workers`. Send at most the crew truck's capacity per trip. On arrival, assign the crew and persist the worker count on the building. When all material and workers are present, call `begin_work(WorkType.CONSTRUCTION, building.construction_work)`. During later ticks call `perform_work(assigned_workers * dt)`; set assigned workers to zero when construction completes.

Keep the assignment and work transition explicit:

```python
worker_deficit = (
    building.construction_workers
    - building.assigned_workers
    - self._in_transit_workers(building.id)
)
crew = min(worker_deficit, truck.crew_capacity, self.provider.available_workers())
route = self._best_route(city_map, building)
if crew > 0 and route is not None and self.provider.reserve_workers(int(crew)):
    self._make_trip(building, truck, CrewPayload(int(crew)), route)

if self._materials_complete(building) and building.assigned_workers >= building.construction_workers:
    building.begin_work(WorkType.CONSTRUCTION, building.construction_work)
```

Implement runtime reset without touching persisted building state:

```python
def clear_trips(self) -> None:
    self.trips.clear()
```

- [ ] **Step 7: Write failing route and retry tests**

Verify trips route from a west-edge provider endpoint to a building's reachable side-of-road lane position, a two-road endpoint join routes through the existing junction graph, a disconnected/no-gate case creates no trip, and adding a connecting road allows the pending demand to dispatch on the next update. Verify one-way direction choices are tested until a reachable route is found.

- [ ] **Step 8: Implement routing, movement, and blocked-demand retry**

For each provider/building endpoint pair, use `CityMap.find_vehicle_route_between()`, select the shortest available path, flatten it with `vehicle_route_points()`, and move only trips that existed at the start of the update at their configured speed. A trip arriving at its roadside access applies its payload and is removed. If no route exists, leave demand unchanged and re-evaluate it on subsequent updates.

Route search should continue past an inaccessible direction instead of treating the nearest lane as automatically usable:

```python
routes = [
    route
    for start in self.provider.access_points(city_map)
    for destination in building_access_points(city_map, building)
    if (route := city_map.find_vehicle_route_between(start, destination)) is not None
]
if not routes:
    return None
route = min(routes, key=lambda candidate: candidate.cost)
```

`_best_route()` returns the selected `Path`; `_make_trip()` calls `vehicle_route_points(route)` and stores the resulting polyline on the new trip. Advance each active trip along that stored path and apply its payload once when it reaches the end:

```python
trip.distance_travelled = min(
    polyline_length(trip.route_points),
    trip.distance_travelled + elapsed_seconds * trip.speed,
)
if trip.distance_travelled >= polyline_length(trip.route_points):
    self._apply_delivery(trip)
    completed.append(trip)
```

- [ ] **Step 9: Run construction simulation tests**

Run: `python3 -m unittest discover -s tests -p 'test_construction_simulation.py' -v`

Expected: PASS for partial loads, transit reservation, provider access, road changes, crew delivery, work progress, material consumption, and completion.

- [ ] **Step 10: Commit routed construction deliveries**

```bash
git add construction.py tests/test_construction_simulation.py
git commit -m "feat: dispatch construction material and crew deliveries"
```

---

### Task 4: Integrate construction ticks, Inspector status, and map visuals

**Files:**
- Modify: `ui/app.py:FreewaySimulator.__init__` and `FreewaySimulator.tick` — own and advance the construction simulation while the city runs.
- Modify: `ui/files.py:FileActionsMixin.new_world` and `load_state` — clear runtime construction trips when the city changes.
- Modify: `ui/renderer.py:RendererMixin._draw_buildings` — distinguish under-construction footprints and draw route-oriented native construction trucks.
- Modify: `ui_tools/tools/inspect_tool.py:inspection_rows` — show demand and progress instead of manual delivery controls.
- Create: `tests/test_construction_presentation.py`

**Interfaces:**
- `FreewaySimulator.construction_simulation` owns runtime-only trips and receives elapsed simulation seconds from `tick()` when `self.running` is true.
- `new_world()` and successful `load_state()` call `self.construction_simulation.clear_trips()` before the next update derives demand from the new city.
- `RendererMixin.draw_construction_trucks() -> None` clears and redraws native 2D trucks for the simulation's active trips each frame.
- `RendererMixin.draw_construction_truck(trip)` draws an oriented low-poly cab-over truck with resource cargo or crew compartment, keyed by `TruckSpec.visual_key` and `ResourceSpec.visual_key`.
- Building Inspector rows show required/delivered/remaining material by resource, required/assigned workers, and active work progress.

- [ ] **Step 1: Write failing presentation tests**

Test Inspector row values during material delivery and active construction, test that the manual `Deliver resource` row is absent, and test that the renderer uses a distinct construction outline/fill for `UNDER_CONSTRUCTION`. Test that each runtime trip has a corresponding visible truck marker and that the marker is removed after arrival.

- [ ] **Step 2: Run presentation tests to confirm they fail**

Run: `python3 -m unittest discover -s tests -p 'test_construction_presentation.py' -v`

Expected: FAIL because construction state is not shown and deliveries have no renderer integration.

- [ ] **Step 3: Add construction simulation to the app tick and world lifecycle**

Initialize the simulation with the loaded construction catalog and virtual provider. Validate template resource IDs at startup. In `tick()`, call `construction_simulation.update(self.city_map, dt * self.simulation_speed)` only while `self.running`, then call `draw_construction_trucks()` every tick to reflect the active trip list; preserve the existing traffic update and redraw ordering.

The app update remains simulation-speed aware and redraws the static map if a building changes lifecycle phase:

```python
resources, trucks = load_construction_catalog()
validate_resource_references(load_buildables(), resources)
self.construction_simulation = ConstructionSimulation(
    resources, trucks, UnlimitedConstructionProvider(),
)

if self.running:
    phases = {building.id: building.phase for building in self.city_map.buildings}
    self.construction_simulation.update(
        self.city_map, dt * self.simulation_speed,
    )
    if any(phases.get(building.id) != building.phase for building in self.city_map.buildings):
        self.redraw_world()
self.draw_construction_trucks()
```

Clear in-flight deliveries only when replacing the world, after a successful load:

```python
# After new-world confirmation and before assigning the new CityMap:
self.construction_simulation.clear_trips()
self.city_map = CityMap()

# After world_from_dict succeeds and before assigning its CityMap:
self.construction_simulation.clear_trips()
self.city_map = loaded.city_map
```

- [ ] **Step 4: Add construction status and truck placeholders to the 2D map**

Draw under-construction buildings with a clear temporary outline or hatch while preserving their template color. Draw each active truck at its interpolated route position with the route tangent controlling its heading. Give material trucks a flatbed and resource-specific cargo silhouette; give crew trucks an enclosed rear compartment. Add matching native geometry to the 3D vehicle layer. Delete markers on arrival or when the scene redraws. Keep resource/truck catalog data independent of rendering.

Use a dedicated canvas tag so active truck markers can be replaced every tick:

```python
canvas.delete(CONSTRUCTION_TRUCK_TAG)
for trip in self.construction_simulation.trips:
    self.draw_construction_truck(trip)
```

- [ ] **Step 5: Replace manual resource delivery with construction status rows**

In `inspection_rows()`, show each resource's required, delivered, and remaining quantities using `construction_delivered`, not the currently empty inventory after `begin_work()` consumes it. Show construction worker demand/assignment and work progress. Remove the manual delivery editor so the provider-driven simulation is the normal path. Keep `deliver_building_resource()` for existing programmatic callers, but have it call `Building.record_construction_delivery()` so its inventory and cumulative delivery stay in sync.

Format one read-only status row per demanded resource, including the catalog unit:

```python
resources = host.construction_simulation.resources
for resource_id, required in building.construction_needs.items():
    resource = resources[resource_id]
    delivered = building.construction_delivered.get(resource_id, 0.0)
    remaining = max(0.0, required - delivered)
    rows.append(InspectionRow(
        f"{resource.name} (required / delivered / remaining)",
        f"{required:g} / {delivered:g} / {remaining:g} {resource.unit}",
    ))
```

- [ ] **Step 6: Run presentation tests and existing Inspector/buildable tests**

Run: `python3 -m unittest discover -s tests -p 'test_construction_presentation.py' -v`

Run: `python3 -m unittest discover -s tests -p 'test_buildables.py' -v`

Run: `python3 -m unittest discover -s tests -p 'test_city_inspector.py' -v`

Expected: PASS for displayed construction state and existing road/building inspection behavior.

- [ ] **Step 7: Commit construction presentation and app integration**

Stage the construction hunks in the already modified `ui/renderer.py` with `git add -p`, inspect `git diff --cached -- ui/renderer.py`, then stage the clean feature files and commit:

```bash
git add ui/app.py ui/files.py ui_tools/tools/inspect_tool.py tests/test_construction_presentation.py
git diff --cached --check
git diff --cached -- ui/renderer.py
git commit -m "feat: show construction deliveries in the city"
```

---

### Task 5: Persist building construction state and validate save/load recovery

**Files:**
- Modify: `persistence.py` — serialize construction requirements, delivered amounts, assigned workers, and active work; bump `WORLD_VERSION` from 6 to 7 and load versions 4, 5, 6, and 7.
- Modify: `tests/test_persistence.py`
- Modify: `tests/test_buildable_lifecycle.py`
- Create: `tests/test_construction_persistence.py`

**Interfaces:**
- Truck trips, route points, provider runtime state, and transit reservations are not serialized.
- `world_from_dict()` restores construction fields with safe defaults for versions 4–6; the next simulation update derives outstanding trips from each building's saved delivered quantities, assigned workers, and work order.

- [ ] **Step 1: Write failing round-trip tests for partial deliveries and active work**

Save two buildings: one with partial material and a partial crew but no work order yet, and one with all material delivered, an active crew, and a partially completed construction `WorkOrder`. Assert the serialized data preserves every building field and contains no truck/trip list.

Construct the test city with a two-way west-edge road and both buildings beside reachable lanes. Give the partial building a lumber need of `10`, a crew need of `3`, `5` delivered lumber, `5` lumber in inventory, and one assigned worker. Give the active building a lumber need of `10`, a crew need of `2`, all `10` lumber delivered, and `100` required work; start its construction and record `30` worker-seconds.

```python
loaded_city = world_from_dict(world_to_dict(
    city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
)).city_map
loaded_buildings = loaded_city.buildings
partial, active = loaded_buildings
self.assertEqual(partial.construction_delivered, {"lumber": 5.0})
self.assertEqual(partial.assigned_workers, 1)
self.assertIsNone(partial.active_work)
self.assertEqual(active.construction_delivered, {"lumber": 10.0})
self.assertEqual(active.assigned_workers, 2)
self.assertEqual(active.active_work.completed_work, 30.0)
```

- [ ] **Step 2: Run persistence tests to confirm the new round-trip test fails**

Run: `python3 -m unittest discover -s tests -p 'test_construction_persistence.py' -v`

Expected: FAIL because the new construction fields are not serialized.

- [ ] **Step 3: Serialize fields and add version-7 migration defaults**

Add the new fields to the buildable-state object, validate worker counts and delivered amounts on load, and set defaults when loading versions 4–6. Continue omitting runtime trips. Bump current saves to version 7.

Include the construction values alongside the existing inventory and work order:

```python
"construction_workers": buildable.construction_workers,
"construction_work": buildable.construction_work,
"assigned_workers": buildable.assigned_workers,
"construction_delivered": dict(buildable.construction_delivered),
```

- [ ] **Step 4: Test restored demand regeneration**

After loading a partial-construction save, create a fresh `ConstructionSimulation` and update it once. Assert the partially supplied building dispatches only its undelivered material and worker deficit. Assert the active building dispatches no construction material or extra crew, and its saved `WorkOrder` advances from the restored progress.

```python
simulation.update(loaded_city, 0.5)
partial_trips = [trip for trip in simulation.trips if trip.building_id == partial.id]
active_trips = [trip for trip in simulation.trips if trip.building_id == active.id]
self.assertEqual(sum(t.payload.amount for t in partial_trips if isinstance(t.payload, MaterialPayload)), 5.0)
self.assertEqual(sum(t.payload.workers for t in partial_trips if isinstance(t.payload, CrewPayload)), 2)
self.assertEqual(active_trips, [])
self.assertGreater(loaded_city.buildings[1].active_work.completed_work, 30.0)
```

- [ ] **Step 5: Run persistence and legacy-version tests**

Run: `python3 -m unittest discover -s tests -p 'test_construction_persistence.py' -v`

Run: `python3 -m unittest discover -s tests -p 'test_persistence.py' -v`

Run: `python3 -m unittest discover -s tests -p 'test_buildable_lifecycle.py' -v`

Expected: PASS for partial and active construction round trips, all supported older save versions, and existing road/buildable state.

- [ ] **Step 6: Commit construction save/load support**

```bash
git add persistence.py tests/test_persistence.py tests/test_buildable_lifecycle.py tests/test_construction_persistence.py
git commit -m "feat: persist building construction progress"
```

---

### Task 6: Run integrated construction and application regression checks

**Files:**
- Test: all affected test modules and full `tests/` suite.
- Review: `docs/superpowers/specs/2026-09-23-building-construction-needs-design.md`.

- [ ] **Step 1: Run all construction-focused tests together**

Run: `python3 -m unittest discover -s tests -p 'test_construction*.py' -v`

Expected: PASS for catalog loading, road access, deliveries, work, presentation, and save/load recovery.

- [ ] **Step 2: Run road mobility and existing buildable/Inspector regressions**

Run: `python3 -m unittest discover -s tests -p 'test_mobility.py' -v`

Run: `python3 -m unittest discover -s tests -p 'test_buildables.py' -v`

Run: `python3 -m unittest discover -s tests -p 'test_city_inspector.py' -v`

Expected: PASS; provider and building access reuse current road connectivity without changing existing traffic routes.

- [ ] **Step 3: Run the complete test suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 4: Review files and preserve unrelated workspace changes**

Run: `git status --short` and `git diff --check`. Stage only files in this plan when committing. Do not stage or revert existing unrelated user changes.

Expected: no whitespace errors and no unrelated files in the feature commit.
