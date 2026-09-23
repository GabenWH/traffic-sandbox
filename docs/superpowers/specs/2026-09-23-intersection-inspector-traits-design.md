# Editable intersection traits

## Approved direction

Give each intersection its own editable, persisted geometry and control traits
in the Inspector. Use the Inspector's existing per-field editing pattern so
the approach remains available to other inspectable types, while keeping this
change focused on intersections. Existing read-only diagnostics remain
read-only.

## Problem

Roundabout dimensions are currently module-level defaults in `roundabouts.py`:
the circulating radius and island radius are proportions of the junction
radius, and the outer band has one global width. Every roundabout therefore
shares the same shape. The Inspector already supports some editable rows, but
intersection geometry is currently presented as read-only and the junction
radius is recalculated by `CityMap.rebuild_mobility_network`.

Intersection geometry is consumed by traffic route generation, road endpoint
setbacks, and both 2D and 3D renderers. Editing a displayed value must update
all of those consumers from one source of truth.

## Design

### Traits by intersection kind

- Every intersection gets an editable junction/turnaround radius. The stored
  user value acts as a requested minimum; the effective radius may not fall
  below the clearance required by its connected roads.
- Roundabouts additionally get editable circulating radius, island radius,
  and outer band width. These are actual distances, displayed in the active
  unit system, rather than editable ratios. Ratios and the current 3-unit band
  width remain defaults for old maps and newly created roundabouts.
- Standard intersections retain the existing junction-type and all-way-stop
  controls. Cul-de-sac type remains derived from road endpoints.
- Position, elevation, connected-road counts, lane counts, and generated
  connection counts remain read-only because they are topology or diagnostic
  values, rather than authored geometry traits.

### Data and shared geometry

Store user-authored geometry overrides on `Intersection`. Preserve the
existing automatically calculated dimensions as defaults, and calculate an
effective geometry from the overrides plus road-clearance requirements.
Roundabout routing, `ui/scene_geometry.py`, and `ui/renderer.py` must all use
the same effective values. Do not add a second renderer-specific settings
path.

Changing an effective junction radius or circulating radius rebuilds the
mobility network and road setbacks. Changing the island radius or band width
redraws geometry without changing vehicle routes. All geometry edits redraw
both views. Routed test cars with old immutable paths are cleared before a
route-affecting rebuild, following the existing intersection-kind conversion
behavior.

### Validation and failures

Reject non-finite values, negative dimensions, and geometry that violates
road-clearance requirements. A roundabout must have a positive island radius,
a circulating radius outside the island with enough usable width for traffic,
and a circulating radius contained by its junction radius. The band width may
be zero to remove it. Validate a proposed edit before mutating the model; on
failure, keep the previous value and show the Inspector's normal validation
message.

### Persistence and old maps

Persist authored overrides with each intersection and advance the world-save
format version. Continue loading existing versions 4 and 5. Saves that lack
the new fields use the current derived-radius, 0.67 circulating-radius ratio,
0.50 island-radius ratio, and 3-unit band defaults, preserving their current
appearance and behavior. Saving and reopening a customized intersection
preserves its values.

### Inspector scope

Build on `InspectionRow` and `inspection_rows` rather than replacing the whole
Inspector system. Keep edit handling reusable at the row/property level, but
do not add or redesign editing for cars, roads, buildings, lanes, signs, or
other inspectables in this change. Their current editable controls and
read-only diagnostics keep their existing behavior.

## Verification

- Inspector tests cover kind-specific editable rows, unit conversion, accepted
  edits, and rejected edits leaving the old trait unchanged.
- Model and mobility tests cover derived defaults, overrides surviving network
  rebuilds, minimum-clearance enforcement, and rebuilt routes after geometry
  changes.
- Persistence tests cover round-tripping overrides and loading older saves
  with default traits.
- 2D and 3D geometry tests assert they consume the same customized ring,
  island, and outer-band dimensions.
- Existing roundabout and traffic collision regressions remain green.

## Out of scope

- Editing the position or elevation of an intersection.
- Editing every diagnostic row or auditing other inspectable types.
- Adding presets, global style settings, or new intersection kinds.
- Undo/redo support for Inspector property edits.
