# Buildables catalog

The **Build** dropdown exposes **Build road** and **Build building** canvas
modes. Activating either mode opens an Inspector-style catalog panel in the
bottom-left of the canvas. The panel reads templates from
`ui_tools/buildables.json`; it does not hard-code the displayed choices.

The catalog is a versioned JSON object:

```json
{
  "version": 1,
  "buildables": [
    {
      "id": "small_house",
      "kind": "building",
      "name": "Small house",
      "description": "A detached residential home.",
      "specs": {
        "width": 40,
        "height": 30,
        "zone": "residential",
        "residents": 4,
        "jobs": 0,
        "color": "#d9b38c"
      }
    }
  ]
}
```

Building templates require positive `width` and `height`, a valid city zone,
nonnegative integer `residents` and `jobs`, and a hex `color`. One click places
the selected footprint centered on the pointer. The entire footprint must fit
inside the city map. Placed buildings retain their template ID and color in
world saves and can be selected with the Inspector.

Road templates use this `specs` shape:

```json
{
  "lane_width": 12,
  "forward_lane_count": 1,
  "reverse_lane_count": 1
}
```

Lane width must be positive, lane counts must be nonnegative integers, and at
least one travel lane is required. The chosen specs control both the live road
preview and the committed road. Road construction otherwise keeps the existing
click vertices, Enter to finish, and Escape to cancel workflow.

Committed roads collide with the full footprint of existing intersections, not
only their connected road centerlines. A pass-through collision inserts the
existing junction center into the new road; an endpoint collision snaps that
endpoint to the center. Junction capture uses both footprint radii so the
builder reuses a nearby intersection instead of creating overlapping junctions.
Cul-de-sacs use this same generic intersection model with a different footprint
and movement policy. A road or future driveway that reaches the bulb joins that
existing intersection; the bulb is not owned by a single road.

IDs must be unique across the entire catalog. Invalid files raise a focused
`BuildableCatalogError` during tool loading rather than producing partially
defined templates.

## Construction state

Every placed road and building shares the same model-level `Buildable` state:

- a lifecycle phase: planning, under construction, operational,
  decommissioned, or demolishing;
- a local resource inventory for deliveries, construction inputs, operating
  supplies, and maintenance materials;
- condition from 0 to 1; and
- at most one active construction, maintenance, upgrade, or demolition work
  order.

Lifecycle and work type are deliberately separate. For example, maintenance
can be active while a building remains operational, while construction and
demolition move it into their corresponding lifecycle phases. Inventory
consumption reports whether a request was fulfilled fully, partially, or not at
all, so later worker and logistics systems can react without being built into
the inventory itself.

This is currently preparatory state. Planning or construction does not yet stop
a road from participating in routing or a building from being drawn and used.
Those gameplay gates should be introduced when construction crews, resource
requirements, and outside connections are wired into the simulation.

World-save version 2 persists this state for both roads and buildings. Road
splitting distributes stored resources and active work between the resulting
segments in proportion to their lengths rather than duplicating them.
