# Canvas tools

Canvas tools are optional interaction modes for the main world canvas. The
current tools are **Inspect**, **Build road**, **Build building**, and
**Test route**, and **Test traffic**.

## Source layout

| File | Responsibility |
| --- | --- |
| `ui_tools/base.py` | Defines reusable toolbar items, one-click commands, and selectable canvas tools. |
| `ui_tools/dropdown_tool.py` | Provides standard dropdowns and dropdowns that own canvas modes. |
| `ui_tools/tools/` | Holds one concrete `*_tool.py` module for each toolbar tool. |
| `ui_tools/toolbar.json` | Controls toolbar order and whether each discovered tool is enabled. |
| `ui_tools/toolbar_registry.py` | Discovers trusted local modules and constructs the configured tools. |
| `ui_tools/sync_toolbar.py` | Appends newly discovered tool IDs to the JSON without changing existing order. |
| `ui_tools/buildables.json` | Defines validated road and building templates shown by Build modes. |
| `ui_tools/buildables_panel.py` | Provides the Inspector-style template chooser and spec display. |
| `ui/app.py` | Owns the active canvas tool, toolbar layout, and event delegation. |
| `ui/base.py`, `ui/viewport.py` | Provide shared canvas and camera helpers used by UI components and tools. |

## File and Simulation dropdown tools

**File** and **Simulation** retain the standard Tkinter dropdown behavior from
the earlier UI. They are `DropdownTool` instances, not canvas interaction modes:

| Tool | Commands |
| --- | --- |
| File | New world, Save, Load, CSV export, SVG export, Exit |
| Simulation | Pause/resume, add car, clear traffic, analytics, performance graph, recent changes |

`DropdownTool` is the reusable example for this kind of tool. A subclass
supplies its `ToolAction(label, command)` list, and the base class creates the
standard `Menubutton` and `Menu`. `FileTool` lives in
`ui_tools/tools/file_tool.py` and `SimulationTool` in
`ui_tools/tools/simulation_tool.py`; both are discovered like every other tool.
`ui_tools/tools/units_tool.py` is another small dropdown example: it calls the
host's `set_unit_system()` method to switch presentation between Imperial and
Metric without changing the traffic model's canonical values.

## Toolbar configuration and automatic discovery

`ui_tools/toolbar.json` is deliberately a simple top-level JSON array so a
JSON table editor can edit it comfortably. Its entries are ordered exactly as
the toolbar appears:

```json
[
  {"id": "file", "enabled": true},
  {"id": "simulation", "enabled": true},
  {"id": "units", "enabled": true},
  {"id": "inspect", "enabled": true},
  {"id": "reset_view", "enabled": true},
  {"id": "road", "enabled": true},
  {"id": "route_test", "enabled": true},
  {"id": "test_traffic", "enabled": true}
]
```

Move complete entries to reorder tools. Set `"enabled": false` to hide one
without deleting its setup. The manifest contains IDs only, never Python import
paths; the app imports only modules discovered in `ui_tools/tools`, which keeps
the editable configuration simple and constrained to local tool code.

Adding a new `*_tool.py` does not silently reorder anything. On application
startup, the toolbar automatically runs the synchronizer and appends its ID at
the end of the array. You can also run it manually:

```bash
python3 -m ui_tools.sync_toolbar
```

On Linux, this optional watcher can update the manifest immediately after a
tool file is created, renamed, saved, or deleted, without waiting for the next
application startup:

```bash
bash scripts/watch_toolbar_tools.sh
```

It requires `inotifywait`; on Arch Linux install it with
`sudo pacman -S inotify-tools`. The watcher changes the JSON immediately, but
the running simulator reads the toolbar only during startup, so restart the app
to see a changed order or a newly added tool. If `toolbar.json` is missing or
invalid, the application reports the problem and uses every discoverable tool
in alphabetical file-name order instead of failing to start.

## Inspect behavior

Press **Inspect** in the toolbar to activate the tool and show its panel in the
bottom-left corner of the main canvas. The sunken toolbar button shows that it
owns ordinary left clicks. Press the button again, or use the panel's × button,
to deactivate it.

With Inspect active:

- Clicking a speed-limit sign shows limit, lane, and world position.
- Clicking a car shows lane, actual/cruise speed, applicable limit, position,
  acceleration, and next path point. Acceleration uses g in Imperial mode and
  m/s² in Metric mode.
- Clicking a lane shows gap, car count, posted limits, and path-point count.
- Clicking empty space shows global simulation stats.

Fields explicitly choose one of three presentations:

| Selection | Editable with slider | Editable with text | Read-only examples |
| --- | --- | --- | --- |
| Global stats | Simulation speed, traffic target, selected-lane gap | — | Run state, active cars, average speed, exits/minute |
| Car | Speed preference | — | Lane, actual/cruise speed, limit, position, path point |
| Lane | Following gap | — | Name, car count, limits, path-point count |
| Speed-limit sign | — | Limit in active speed units | Lane and position |

Text edits apply with **Apply** or Enter. Invalid input stays in the panel and
shows a validation message rather than opening a dialog. Slider and text changes
write directly to the existing model. Runtime-derived values intentionally have
no editor.

Selection priority matches visual order: signs, car canvas polygons, buildings,
intersections, roads, legacy lanes, then global stats. Values refresh during `tick()`, so moving-car and
simulation values remain live. A removed object or replaced world automatically
returns the Inspector to global stats.

Global stats mirror the toolbar's quick information and controls: run state,
simulation multiplier, actual/target traffic, active display units, average
speed, exits per minute, selected lane, and following gap.

## Route-test behavior

Press **Test route**, then click directly on a generated lane of a constructed
road to choose the start. Click a second lane to choose the destination. The
tool calls the city's normal directed vehicle router and overlays the result:
cyan follows lane travel, orange crosses an intersection connection, green
marks the start, and red marks the destination. The label reports total route
distance or that no directed route exists. A third lane click starts a new
query, and Escape clears the current query.

Clicking inside an intersection or cul-de-sac selects that complete junction
instead of a nearby lane. A selected starting junction may use any outgoing
lane, and a selected destination junction may use any incoming lane. Junction
selection is displayed as a footprint-sized ring.

The route test is diagnostic only. It does not create cars, trips, demands, or
persistent save data. Each click is projected onto the nearest lane centerline,
so ordinary road clicks begin and end at exact directed distances along their
lanes.

## Test-traffic behavior

Press **Test traffic** and click an intersection or cul-de-sac to toggle it as
a combined source and sink. Active endpoints have cyan and red rings. With at
least two enabled endpoints, each periodically asks the normal vehicle router
for a path to another enabled endpoint and spawns a lightweight car when that
directed path exists. Clicking an endpoint again disables future spawns there.

Cars follow the route geometry carried by lane, road-port, and lane-connection
edges. Each routed test car owns a behavior brain with visible cruise,
approach-stop, stopped, waiting, entering, and clearing states. Brains use
bounded acceleration and braking, queue behind a car ahead on the same current lane,
and obey all-way stops configured through the Inspector. Car occupancy is
indexed by current mobility link and fixed longitudinal cells, so cars sharing
an approach see one another even when their later routes diverge. Building the
index and performing bounded neighboring-cell probes are expected linear time
in the active car count; motion is also hard-limited to preserve physical
separation. After a complete
0.5-second stop, the brain requests its intended movement from a runtime
coordinator. First arrival has priority; equal arrivals use deterministic
clockwise approach order. Intersections expose facts and arbitrate claims but
never command car movement. The
Simulation pause and speed controls affect them, and **Clear traffic** removes
the current cars without disabling their endpoints. Escape clears both the
cars and endpoint selection. Test traffic is runtime-only and is not saved.
Off-screen test cars are culled, and low zoom renders them as simple direction
lines to keep this diagnostic mode practical for larger fleets.

To configure a stop, activate **Inspect**, select a standard intersection, set
**All-way stop** to `yes`, and press Enter or Apply. The setting applies to all
incoming movements, draws white stop bars, and is persisted with the world.
Select a routed test car to inspect its brain state, wait reason, current and
desired speeds, turn-signal intent, route progress, and claimed movement. The
brain activates the appropriate left or right signal 100 feet before its next
turn, treats a U-turn as a left signal, keeps signaling while stopped or inside
the turn, and cancels after clearing it. At normal zoom, paired amber front and
rear indicators flash from simulation time, so pausing freezes their phase.
The debug window also
lists compact live brain decisions. Setting **All-way stop** back to `no`
restores uncontrolled movements. Cul-de-sacs cannot be configured as all-way
stops.

## Performance graph

Choose **Simulation → Performance graph** to inspect the actual interval between
UI ticks. The upper orange plot is frame time in milliseconds and marks the
16.67 ms (60 FPS) budget; the lower blue plot is instantaneous FPS and marks
60 FPS. The summary reports latest, average, and worst frame time. It retains
only the most recent 20 seconds and redraws four times per second so the
diagnostic itself stays lightweight.

## Tool lifecycle

Every selectable canvas tool subclasses `CanvasTool` and may override these
hooks:

| Hook | Called when | Typical use |
| --- | --- | --- |
| `activate()` | Its toolbar button is selected. | Show or raise a panel; initialize previews. |
| `deactivate()` | It is toggled off or another tool is selected. | Remove panels and temporary canvas items. |
| `on_canvas_click(event)` | Main canvas receives a left click while active. | Select an object or place/edit something. |
| `on_canvas_motion(event)` | The pointer moves over the main canvas. | Update a construction preview. |
| `refresh()` | Each UI frame while active. | Update live labels or moving previews. |
| `reset()` | The app replaces the current world. | Drop references to objects from the old world. |

The base methods do nothing, so a simple tool only overrides the hooks it
needs. Tools receive the main `FreewaySimulator` as `self.host`; the Inspect
example uses its root, canvas, simulation, projection, and hit-test helpers.
Every canvas tool also exposes `self.inspector` and `show_inspector()` so it can
reuse the shared Inspector panel without replacing the current active mode.
`inspect_object(model)` additionally hands a newly selected or created model
object to that panel. Build modes instead own a Buildables catalog panel while
active so construction choices remain visible after placement.

## Canvas tools in dropdowns

`CanvasToolDropdown` owns one or more `CanvasTool` instances returned by
`create_canvas_tools()`. Selecting one of its entries activates that canvas
mode. The ordinary dropdown button is hidden and a blue copy is docked in the
reserved far-left active-menu area. Its native Tk `Menu` is posted without a
popup grab, so it remains visible while clicks continue to reach the canvas.
Deactivating the canvas mode removes the blue copy and restores the dropdown to
its configured toolbar position. Choosing the already-active canvas entry again
deactivates it. Clicking the docked blue dropdown button also deactivates the
mode and closes its menu. The active canvas entry remains selected with Tk's
radio-menu indicator for as long as its dropdown occupies the blue zone.

Canvas-tool dropdowns automatically include an **Inspector…** command when the
shared Inspector is available. `BuildTool` in `road_tool.py` is the concrete
example:

```python
class BuildTool(CanvasToolDropdown):
    name = "Build"

    def create_canvas_tools(self) -> list[CanvasTool]:
        return [RoadTool(self.host), BuildingTool(self.host)]
```

## Adding a tool by hand

Create `ui_tools/tools/measure_tool.py`:

```python
from __future__ import annotations

from typing import Any

from ..base import CanvasTool


TOOL_ID = "measure"


class MeasureTool(CanvasTool):
    name = "Measure"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.start: tuple[float, float] | None = None

    def activate(self) -> None:
        self.start = None

    def on_canvas_click(self, event: Any) -> None:
        point = self.host.screen_to_world((event.x, event.y))
        if self.start is None:
            self.start = point
            return
        print(f"Measure from {self.start} to {point}")
        self.start = None

    def reset(self) -> None:
        self.start = None


TOOL_CLASS = MeasureTool
```

Then run `python3 -m ui_tools.sync_toolbar` and restart the app. Move the new
JSON entry where you want it in the toolbar. There are no `ui/app.py` imports,
manual constructions, toolbar-button calls, or registry edits to make.

No additional toolbar construction or canvas binding code is required for a
`CanvasTool`: `ui/app.py` builds registered tools, delegates left clicks to
`active_tool`, refreshes it, deactivates the old canvas tool when a new one is
chosen, and calls `reset()` for registered tools when a world is replaced.

For a dropdown, subclass `DropdownTool`, implement `actions()`, and give its
module `TOOL_ID` and `TOOL_CLASS` exactly like the example. For a single
immediate command, subclass `CommandTool` as `ResetViewTool` does in
`ui_tools/tools/reset_view_tool.py`; this keeps every concrete tool in its own
file.

## Inspect implementation notes

`inspection_rows(host, selected)` is separate from Tkinter panel drawing. It
returns a title and `InspectionRow` descriptions, making values and editability
straightforward to test or reuse in another presentation later.

An `InspectionRow` supplies `label` and `value`. Leaving `editor=None` creates a
read-only label. Set `editor="slider"` with `minimum`, `maximum`, `resolution`,
and an `apply(value)` callback for a scale. Set `editor="text"` with an
`apply(value)` callback for an Entry plus Apply button. For example:

Set `target` to another inspectable model object to render the value as a blue
navigation link. Roads use these links for their generated lanes, and lanes
link back to their parent road. Cars and speed-limit signs also link to their
lane. The field area scrolls when an object, such as a multi-way intersection,
has more properties than fit in the fixed Inspector panel.

```python
InspectionRow("Cars", "12")

InspectionRow(
    "Lane width", road.width, "slider", set_width,
    minimum=20, maximum=100, resolution=5,
)

InspectionRow("Road name", road.name, "text", set_name)
```

`InspectTool._build_fields()` is the only Tkinter widget factory for these
descriptions. `refresh()` updates labels and sliders from live model state while
preserving text currently being typed.

The panel is a `Frame` parented by the main canvas and positioned with
`place(x=12, rely=1.0, y=-12, anchor="sw")`. This keeps it attached to the
visible bottom-left corner during window resizing, panning, and zooming. Because
it is a widget overlay rather than a world-space canvas item, it is not affected
by scene render order or camera transforms.

Cars are selected using `canvas.find_overlapping()` against their stored body
and detail item IDs. Signs and lanes reuse the application's existing
world-space hit tests. `pixels_per_second_to_mph()` centralizes the unit
conversion used for individual-car values.

The Inspector does not copy simulation state. It reads current objects each
refresh, and every editor callback updates the same model used by simulation.

## Buildables behavior

Both Build modes load validated choices from `ui_tools/buildables.json`. The
panel provides a scrollable template list, description, and every JSON spec.
See [`BUILDABLES.md`](BUILDABLES.md) for the versioned schema and field rules.

### Build road

Choose **Build → Build road** to author a road centreline directly on the world:

- Left-click to add polyline vertices.
- Move the pointer to preview the next segment.
- Press Enter after at least two vertices to create the road.
- Press Escape to discard the current draft.

A committed `Road` owns its generated `Lane` children. The selected template
provides lane width and directional lane counts. The authored road
centreline is the editable source geometry; lane centrelines are offsets and
are rebuilt from it. Crossing and endpoint joins create inspectable
`Intersection` objects, split road centrelines into connected segments, and
generate lane connections between the segments' derived road outputs and inputs.

### Build building

Choose a building template and click its desired center. A live rectangle shows
the footprint. Valid placement creates a zoned `Parcel` and persistent
`Building`, redraws the world, and leaves the mode active for repeated
placement. Escape or the panel's × button closes the mode. Buildings retain
their catalog ID, color, population, employment, dimensions, and zone through
save/load and can be selected by Inspect.
