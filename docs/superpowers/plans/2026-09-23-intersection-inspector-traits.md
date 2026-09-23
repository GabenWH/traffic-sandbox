# Editable Intersection Traits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each intersection's useful geometry traits editable and persistent, with roundabout routing and the 2D/3D views using the same per-intersection values.

**Architecture:** Store optional user overrides on `models.Intersection`, while `CityMap` continues to compute road-clearance minimums. Keep roundabout defaults and dimension validation in `roundabouts.py`; use the same accessors in routing, 2D drawing, and 3D scene geometry. The Inspector adds editable rows through its current `InspectionRow` pattern and refreshes dependent simulation/map state after accepted changes.

**Tech Stack:** Python 3, dataclasses, Tkinter Inspector rows, JSON persistence, Panda3D scene geometry, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-23-intersection-inspector-traits-design.md`

## Global Constraints

- Preserve the current defaults: 0.67 circulating-radius ratio, 0.50 island-radius ratio, and 3-unit outer band width.
- Load existing world-save versions 4 and 5 after advancing the format version.
- A roundabout must have positive junction, circulating, and island radii; its island must be inside the circulating radius with adequate traffic width, and the circulating radius must be inside its junction radius.
- The outer band width may be zero.
- Intersection position and elevation remain read-only.
- Keep this change focused on intersections; preserve existing editing behavior for other inspectable types.
- Keep the original checkout untouched; perform work in the approved isolated worktree.
- Commit only feature deltas in the isolated worktree. Its initial baseline snapshot contains the original checkout's existing work, so task commits must not include baseline changes.

## Review Focus

- Road additions or changes can increase the required junction radius; retain the user's override while enforcing the new clearance minimum. Cover this in the `CityMap` geometry tests.
- A circulating radius near the island can violate the existing car-body clearance rule; reject the edit without changing any trait. Cover this in Inspector validation tests.
- A malformed save can contain non-finite or internally inconsistent dimensions; reject it as `WorldFormatError`. Cover this in persistence tests.
- Switching a roundabout to another supported kind and back must preserve its authored dimensions; returning to roundabout mode must validate them. Cover this in Inspector tests.
- Zero band width is valid and must remove the band in both renderers; cover this in shared-geometry tests.

---

## File Structure

- Modify `models.py` to hold optional per-intersection geometry overrides.
- Modify `city.py` to calculate the road-required radius separately from the user's requested radius and preserve the override during mobility rebuilds.
- Modify `roundabouts.py` to provide effective-dimension accessors and validate roundabout geometry; routing keeps using `ring_radius()`.
- Modify `persistence.py` to save/load optional overrides and support versions 4, 5, and 6.
- Modify `ui_tools/tools/inspect_tool.py` to expose editable distance rows and apply geometry changes safely.
- Modify `ui/renderer.py` and `ui/scene_geometry.py` to consume per-intersection island and band dimensions. `ui/scene3d.py` already builds the intersection from `roundabout_deck_quads()`; preserve that shared path and add coverage through `tests/test_scene3d.py`.
- Extend `tests/test_roundabout_visuals.py`, `tests/test_city.py`, `tests/test_persistence.py`, `tests/test_city_inspector.py`, `tests/test_scene_geometry.py`, and `tests/test_scene3d.py` for their owning behavior.

### Task 1: Store and calculate intersection geometry traits

**Files:**
- Modify: `models.py`
- Modify: `city.py`
- Modify: `roundabouts.py`
- Test: `tests/test_roundabout_visuals.py`
- Test: `tests/test_city.py`

**Interfaces:**
- Add optional `Intersection.radius_override`, `Intersection.roundabout_ring_radius`, `Intersection.roundabout_island_radius`, and `Intersection.roundabout_outer_band_width` fields. `None` means use the existing computed/default value.
- Keep `ring_radius(junction)` and `island_radius(junction)` as the routing/geometry accessors; add `outer_band_width(junction)` and `validate_roundabout_dimensions(junction)` in `roundabouts.py`.
- Add `CityMap.minimum_intersection_radius(intersection) -> float`; mobility rebuilds set the effective `intersection.radius` to `max(minimum_intersection_radius, radius_override or 0)`.

- [ ] **Step 1: Write failing tests for default and overridden roundabout traits**

In `tests/test_roundabout_visuals.py`, extend the existing default-clearance test with:

```python
junction = Intersection("r", (100, 100), radius=60, kind=IntersectionKind.ROUNDABOUT)
self.assertEqual(ring_radius(junction), 40.2)
self.assertEqual(island_radius(junction), 30.0)
self.assertEqual(outer_band_width(junction), 3.0)

junction.roundabout_ring_radius = 42.0
junction.roundabout_island_radius = 28.0
junction.roundabout_outer_band_width = 0.0
self.assertEqual(ring_radius(junction), 42.0)
self.assertEqual(island_radius(junction), 28.0)
self.assertEqual(outer_band_width(junction), 0.0)
```

- [ ] **Step 2: Run the focused test and confirm the missing trait API fails**

Run: `python3 -m unittest tests.test_roundabout_visuals -v`
Expected: FAIL because the override fields and `outer_band_width()` do not exist.

- [ ] **Step 3: Write failing tests for radius overrides and clearance minimums**

In `tests/test_city.py`, create a standard junction, set `radius_override` to a value above its current minimum, call `city.rebuild_mobility_network()`, and assert the effective radius keeps the override. Then widen a connected road, rebuild again, and assert the effective radius is at least `city.minimum_intersection_radius(junction)` without clearing `radius_override`.

```python
city = CityMap(terrain=Terrain(trees=[]))
city.add_road([(0, 50), (100, 50)])
city.add_road([(50, 0), (50, 100)])
junction = city.standard_intersections[0]
junction.radius_override = 50.0
city.rebuild_mobility_network()
self.assertEqual(junction.radius, 50.0)

junction.connected_roads[0].lane_width = 48.0
city.rebuild_mobility_network()
self.assertGreaterEqual(junction.radius, city.minimum_intersection_radius(junction))
self.assertEqual(junction.radius_override, 50.0)
```

- [ ] **Step 4: Run the focused city test and confirm the radius override is lost**

Run: `python3 -m unittest tests.test_city -v`
Expected: FAIL because `CityMap` currently replaces `Intersection.radius` with the derived minimum on every rebuild.

- [ ] **Step 5: Implement optional model overrides and shared defaults**

Add the four `Intersection` fields. Update `ring_radius()` and `island_radius()` to use their explicit value when present; otherwise retain the current ratios. Add `outer_band_width()` with the existing 3-unit default.

```python
def ring_radius(junction):
    if junction.roundabout_ring_radius is not None:
        return junction.roundabout_ring_radius
    return junction.radius * _RING_RADIUS_RATIO
```

- [ ] **Step 6: Preserve radius overrides during mobility rebuilds**

Move the existing standard and cul-de-sac minimum-radius calculations into `CityMap.minimum_intersection_radius(intersection)`. In `rebuild_mobility_network()`, set `intersection.radius` to `max(minimum_intersection_radius, radius_override or 0)` so road changes cannot shrink a user override or reduce the required clearance.

```python
minimum_radius = self.minimum_intersection_radius(intersection)
intersection.radius = max(minimum_radius, intersection.radius_override or 0.0)
```

- [ ] **Step 7: Add validation for roundabout dimensions**

Implement `validate_roundabout_dimensions(junction)` to reject non-finite values, negative radius/band values, an island that is not inside the circulating path, insufficient usable traffic width, or a circulating radius outside the effective junction radius. Preserve the existing clearance invariant from `tests/test_roundabout_visuals.py`: `ring_radius - island_radius - 3 >= 1`.

```python
if ring_radius(junction) - island_radius(junction) - 3.0 < 1.0:
    raise ValueError("The circulating lane is too close to the island.")
```

- [ ] **Step 8: Run the focused model and routing tests**

Run: `python3 -m unittest tests.test_roundabout_visuals tests.test_city tests.test_mobility -v`
Expected: PASS, including unchanged default geometry and preserved overrides after a mobility rebuild.

- [ ] **Step 9: Commit the model and shared-geometry feature delta**

Commit only changes since the isolated worktree's baseline:

```bash
git add models.py city.py roundabouts.py tests/test_roundabout_visuals.py tests/test_city.py
git commit -m "feat: store per-intersection geometry traits"
git show --check --stat --oneline HEAD
```

### Task 2: Persist authored intersection traits

**Files:**
- Modify: `persistence.py`
- Test: `tests/test_persistence.py`

**Interfaces:**
- Increase `WORLD_VERSION` from 5 to 6 and accept save versions `(4, 5, 6)`.
- Serialize the four optional override fields on each intersection; omitted or `null` values mean the legacy/default behavior.
- Load invalid trait data as `WorldFormatError` with the intersection path included.

- [ ] **Step 1: Write a failing round-trip test for custom traits**

In `tests/test_persistence.py`, make an intersection roundabout and set `radius_override`, `roundabout_ring_radius`, `roundabout_island_radius`, and `roundabout_outer_band_width`. Save with `world_to_dict()`, JSON round-trip through `world_from_dict()`, and assert all four values survive.

```python
intersection.radius_override = 72.0
intersection.roundabout_ring_radius = 48.0
intersection.roundabout_island_radius = 35.0
intersection.roundabout_outer_band_width = 5.0
encoded = world_to_dict(
    city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
)
loaded = world_from_dict(json.loads(json.dumps(encoded)))
round_trip = next(item for item in loaded.city_map.intersections if item.id == intersection.id)
self.assertEqual(round_trip.roundabout_ring_radius, 48.0)
self.assertEqual(round_trip.roundabout_island_radius, 35.0)
self.assertEqual(round_trip.roundabout_outer_band_width, 5.0)
self.assertEqual(round_trip.radius_override, 72.0)
```

- [ ] **Step 2: Run the persistence test to confirm the fields are omitted**

Run: `python3 -m unittest tests.test_persistence -v`
Expected: FAIL because version 5 serialization does not include the new fields.

- [ ] **Step 3: Write legacy and malformed-value persistence tests**

Create version-4 and version-5 payloads without the new keys and assert they load with `None` overrides and current defaults. Add payloads with `NaN`, a negative band width, and an island/circulating-radius conflict; assert each raises `WorldFormatError`.

- [ ] **Step 4: Implement version-6 serialization and validation**

Set `WORLD_VERSION = 6`, accept `(4, 5, WORLD_VERSION)`, write optional trait values in `world.intersections`, and restore them before `city_map.rebuild_mobility_network()`. Validate present numeric fields with the existing `_number()` / `_positive_number()` helpers and call `validate_roundabout_dimensions()` after the effective radius is known. Convert validation errors to `WorldFormatError` with the correct save path.

```python
"radius_override": intersection.radius_override,
"roundabout_ring_radius": intersection.roundabout_ring_radius,
"roundabout_island_radius": intersection.roundabout_island_radius,
"roundabout_outer_band_width": intersection.roundabout_outer_band_width,
```

- [ ] **Step 5: Run the persistence and legacy-load tests**

Run: `python3 -m unittest tests.test_persistence tests.test_road_elevation -v`
Expected: PASS for custom round-trips and supported versions 4, 5, and 6.

- [ ] **Step 6: Commit the persistence feature delta**

```bash
git add persistence.py tests/test_persistence.py
git commit -m "feat: persist intersection geometry traits"
git show --check --stat --oneline HEAD
```

### Task 3: Edit traits in the Inspector and refresh dependent state

**Files:**
- Modify: `ui_tools/tools/inspect_tool.py`
- Test: `tests/test_city_inspector.py`

**Interfaces:**
- Add `set_intersection_trait(host, intersection, trait, value) -> None` for the traits `radius`, `roundabout_ring_radius`, `roundabout_island_radius`, and `roundabout_outer_band_width`.
- Add `clear_routed_test_cars(host) -> None` to remove routed-test-car models and their canvas items before route shapes change.
- Map the Inspector trait name `radius` to `Intersection.radius_override`; the three roundabout names map directly to their fields.
- Render distances with `pixels_to_display_distance()` and apply typed values with `display_distance_to_pixels()`.
- Clear routed test cars before a route-affecting edit, then call `host.city_map.rebuild_mobility_network()` and `host.redraw_world()`. Island-only and band-only edits redraw without rebuilding routes or clearing traffic.

- [ ] **Step 1: Write failing tests for type-specific Inspector rows**

Extend `CityInspectorTests` so standard and cul-de-sac intersections show an editable radius row; roundabouts additionally show editable circulating radius, island radius, and outer band width. Assert existing kind and all-way-stop rows remain present for standard intersections, and route-count diagnostics remain read-only.

```python
rows_by_label = {row.label: row for row in rows}
self.assertEqual(rows_by_label["Junction radius"].editor, "text")
self.assertIsNotNone(rows_by_label["Junction radius"].apply)
self.assertIsNone(rows_by_label["Lane connections"].editor)
```

Add a conversion case that sets custom roundabout values, switches the same intersection to standard and back, and confirms the values remain on that intersection. Also cover a conversion back to roundabout being rejected if a standard-radius edit has made the saved roundabout geometry invalid.

- [ ] **Step 2: Run the Inspector tests and confirm the geometry rows are read-only or absent**

Run: `python3 -m unittest tests.test_city_inspector -v`
Expected: FAIL because `InspectionRow.editor` and `apply` are not set for intersection dimensions.

- [ ] **Step 3: Write failing tests for edit conversion, rejection, and refresh**

Use a fake host with metric units, `test_traffic.clear_cars()`, `canvas.delete()`, and `redraw_world()`. Apply a roundabout ring-radius row in displayed meters and assert the stored world value is converted correctly and the host refreshes. Apply an invalid island/ring combination and assert `ValueError`, unchanged old values, and no refresh. Assert island and band edits redraw without clearing routed test traffic.

```python
old_ring = junction.roundabout_ring_radius
with self.assertRaises(ValueError):
    set_intersection_trait(host, junction, "roundabout_ring_radius", "1")
self.assertEqual(junction.roundabout_ring_radius, old_ring)
self.assertEqual(host.redraw_count, 0)
```

- [ ] **Step 4: Implement `set_intersection_trait()` transactionally**

Parse the displayed number, convert it to world distance, and validate the candidate before committing it. For radius edits, reject values below `city_map.minimum_intersection_radius(intersection)` and validate roundabout constraints against the candidate effective radius. For roundabout edits, call `validate_roundabout_dimensions()` with the candidate values. Keep the prior field value intact on failure. On success, call `clear_routed_test_cars(host)` (matching `set_intersection_kind()`); rebuild the mobility network for radius or circulating-radius edits. For every accepted edit, call `host.redraw_world()` when available.

```python
def clear_routed_test_cars(host):
    traffic = getattr(host, "test_traffic", None)
    if traffic is None:
        return
    for car in traffic.clear_cars():
        canvas = getattr(host, "canvas", None)
        if canvas is not None:
            for item in [car.item, *car.signal_items]:
                if item is not None:
                    canvas.delete(item)
```

Call this helper from `set_intersection_kind()` as well, so type changes and geometry changes use one cleanup path.

```python
attribute = {
    "radius": "radius_override",
    "roundabout_ring_radius": "roundabout_ring_radius",
    "roundabout_island_radius": "roundabout_island_radius",
    "roundabout_outer_band_width": "roundabout_outer_band_width",
}[trait]
world_value = display_distance_to_pixels(float(value), host.unit_system)
previous = getattr(intersection, attribute)
old_radius = intersection.radius
try:
    if trait == "radius":
        minimum = host.city_map.minimum_intersection_radius(intersection)
        if world_value < minimum:
            raise ValueError("Junction radius is below the required road clearance.")
        intersection.radius = world_value
    setattr(intersection, attribute, world_value)
    validate_roundabout_dimensions(intersection)
except ValueError:
    setattr(intersection, attribute, previous)
    intersection.radius = old_radius
    raise
```

In `set_intersection_kind()`, keep roundabout-specific overrides when changing kind. Before converting to roundabout, calculate the target kind's effective radius, validate the retained roundabout values against it, and leave the old kind untouched if they no longer fit.

- [ ] **Step 5: Add editable intersection rows**

In `inspection_rows()`, keep ID, location, road links, and generated counts read-only. Add a text-editor "Junction radius" row for standard and roundabout intersections and a "Turnaround radius" row for cul-de-sacs. For roundabouts add text-editor rows for circulating radius, island radius, and outer band width, with the band displaying zero when disabled. Format all row values in the host's current unit system and bind each row to `set_intersection_trait()`.

- [ ] **Step 6: Run Inspector and interaction regressions**

Run: `python3 -m unittest tests.test_city_inspector -v`
Expected: PASS; valid route-affecting edits clear stale cars and redraw, while invalid edits leave the selected intersection unchanged.

- [ ] **Step 7: Commit the Inspector feature delta**

```bash
git add ui_tools/tools/inspect_tool.py tests/test_city_inspector.py
git commit -m "feat: edit intersection traits in inspector"
git show --check --stat --oneline HEAD
```

### Task 4: Use the same customized traits in 2D and 3D

**Files:**
- Modify: `ui/renderer.py`
- Modify: `ui/scene_geometry.py`
- Test: `tests/test_roundabout_visuals.py`
- Test: `tests/test_scene_geometry.py`
- Test: `tests/test_scene3d.py`
- Test: `tests/test_ui_package.py`

**Interfaces:**
- `ui/renderer.py` uses `outer_band_width(junction)` and `island_radius(junction)` for 2D surfaces.
- `roundabout_deck_quads(junction, segments=32)` uses the same per-intersection outer-band and island dimensions for 3D surfaces; its tuple return signature remains unchanged.
- `ring_radius(junction)` remains the sole source for the traffic ring path in `add_roundabout_to_layer()`.
- The existing 3D car layer displays the route positions produced from that ring path; do not add a separate 3D-only radius setting.

- [ ] **Step 1: Write failing tests for customized 3D geometry**

In `tests/test_scene_geometry.py`, set a roundabout's ring, island, and band overrides; assert the island vertices use the custom island radius and the outer-band vertices extend by the custom band width. Test a zero-width band produces only degenerate band quads and does not change island geometry.

```python
from math import hypot

junction.roundabout_island_radius = 9.0
junction.roundabout_outer_band_width = 5.0
deck, band, island = roundabout_deck_quads(junction)
island_radii = {
    round(hypot(vertex[0] - junction.position[0], vertex[1] - junction.position[1]), 6)
    for quad in island for vertex in quad
}
band_radii = {
    round(hypot(vertex[0] - junction.position[0], vertex[1] - junction.position[1]), 6)
    for quad in band for vertex in quad
}
self.assertEqual(island_radii, {0.0, 9.0})
self.assertEqual(max(band_radii), junction.radius + 5.0)
```

- [ ] **Step 2: Run the scene geometry test and confirm it still uses module defaults**

Run: `python3 -m unittest tests.test_scene_geometry -v`
Expected: FAIL because `roundabout_deck_quads()` currently reads the global band width and derived island radius.

- [ ] **Step 3: Write failing checks for 2D and scene integration**

Extend `tests/test_ui_package.py` to verify a custom island and band size reaches the 2D renderer's geometry, and extend `tests/test_scene3d.py` to verify the `roundabout-island` and `roundabout-outer-band` nodes are built from custom quads. In `tests/test_roundabout_visuals.py`, build a roundabout mobility layer with a custom ring radius and assert each ring arc's centerline points stay at that radius from the junction center.

In the same 3D test, pass a car positioned on a custom ring arc to `update_car_layer()` and assert the registered vehicle node receives that exact world position.

- [ ] **Step 4: Implement shared dimension accessors in both renderers**

Replace `ROUNDABOUT_OUTER_BAND_WIDTH` reads in `ui/renderer.py` and `ui/scene_geometry.py` with `outer_band_width(junction)`. Keep `island_radius(junction)` shared. Preserve `roundabout_deck_quads()`'s current three-list return so `ui/scene3d.py` continues drawing those surfaces through its existing scene registry. Keep routing arcs generated through `ring_radius(junction)`.

- [ ] **Step 5: Run geometry and renderer tests**

Run: `python3 -m unittest tests.test_roundabout_visuals tests.test_scene_geometry tests.test_scene3d tests.test_ui_package -v`
Expected: PASS; both renderers use customized band/island geometry, and traffic arcs use the customized circulating radius.

- [ ] **Step 6: Run the full suite and inspect the final diff**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS with the suite's normal skips and warnings; then run `git diff --check` and review the planned changes alongside the pre-existing dirty files without reverting or staging those earlier edits.

- [ ] **Step 7: Commit the shared renderer feature delta**

```bash
git add ui/renderer.py ui/scene_geometry.py tests/test_roundabout_visuals.py tests/test_scene_geometry.py tests/test_scene3d.py tests/test_ui_package.py
git commit -m "feat: render customized intersection geometry in 2d and 3d"
git show --check --stat --oneline HEAD
```
