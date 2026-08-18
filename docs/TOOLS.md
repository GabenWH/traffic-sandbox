# Canvas tools

Canvas tools are optional interaction modes for the main world canvas. The
first implementation is **Inspect**, intentionally kept small enough to copy
when adding construction, demolition, zoning, or measurement tools.

## Source layout

| File | Responsibility |
| --- | --- |
| `ui_tools/base.py` | Defines reusable toolbar items, one-click commands, and selectable canvas tools. |
| `ui_tools/dropdown_tool.py` | Provides the reusable standard dropdown-menu base. |
| `ui_tools/tools/` | Holds one concrete `*_tool.py` module for each toolbar tool. |
| `ui_tools/toolbar.json` | Controls toolbar order and whether each discovered tool is enabled. |
| `ui_tools/toolbar_registry.py` | Discovers trusted local modules and constructs the configured tools. |
| `ui_tools/sync_toolbar.py` | Appends newly discovered tool IDs to the JSON without changing existing order. |
| `ui.py` | Owns the active canvas tool, toolbar layout, and event delegation. |

## File and Simulation dropdown tools

**File** and **Simulation** retain the standard Tkinter dropdown behavior from
the earlier UI. They are `DropdownTool` instances, not canvas interaction modes:

| Tool | Commands |
| --- | --- |
| File | New world, Save, Load, CSV export, SVG export, Exit |
| Simulation | Pause/resume, add car, clear traffic, analytics, recent changes |

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
  {"id": "reset_view", "enabled": true}
]
```

Move complete entries to reorder tools. Set `"enabled": false` to hide one
without deleting its setup. The manifest contains IDs only, never Python import
paths; the app imports only modules discovered in `ui_tools/tools`, which keeps
the editable configuration simple and constrained to local tool code.

Adding a new `*_tool.py` does not silently reorder anything. Run this once to
append its ID at the end of the array:

```bash
python3 -m ui_tools.sync_toolbar
```

On Linux, this optional watcher runs that synchronizer after a tool file is
created, renamed, saved, or deleted:

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

Selection priority matches visual order: signs, then car canvas polygons, then
lanes, then global stats. Values refresh during `tick()`, so moving-car and
simulation values remain live. A removed object or replaced world automatically
returns the Inspector to global stats.

Global stats mirror the toolbar's quick information and controls: run state,
simulation multiplier, actual/target traffic, active display units, average
speed, exits per minute, selected lane, and following gap.

## Tool lifecycle

Every selectable canvas tool subclasses `CanvasTool` and may override these
hooks:

| Hook | Called when | Typical use |
| --- | --- | --- |
| `activate()` | Its toolbar button is selected. | Show or raise a panel; initialize previews. |
| `deactivate()` | It is toggled off or another tool is selected. | Remove panels and temporary canvas items. |
| `on_canvas_click(event)` | Main canvas receives a left click while active. | Select an object or place/edit something. |
| `refresh()` | Each UI frame while active. | Update live labels or moving previews. |
| `reset()` | The app replaces the current world. | Drop references to objects from the old world. |

The base methods do nothing, so a simple tool only overrides the hooks it
needs. Tools receive the main `FreewaySimulator` as `self.host`; the Inspect
example uses its root, canvas, simulation, projection, and hit-test helpers.

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
JSON entry where you want it in the toolbar. There are no `ui.py` imports,
manual constructions, toolbar-button calls, or registry edits to make.

No additional toolbar construction or canvas binding code is required for a
`CanvasTool`: `ui.py` builds registered tools, delegates left clicks to
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
