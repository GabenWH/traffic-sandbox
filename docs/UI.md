# UI reference

The `ui/` package contains the Tkinter presentation layer. `ui.app.FreewaySimulator`
is the small coordinator; focused mixins provide rendering, viewport behavior,
traffic interactions, file actions, and secondary windows. `ui.__init__`
re-exports the class, so the launcher continues to use
`from ui import FreewaySimulator`.

| Module | Responsibility |
| --- | --- |
| `ui/app.py` | Application state, toolbar/tool coordination, bindings, and tick loop. |
| `ui/renderer.py` | Terrain, road, vehicle, and speed-sign canvas rendering. |
| `ui/viewport.py` | Camera state, coordinate projection, pan, and zoom. |
| `ui/interactions.py` | Traffic controls, hit testing, and context-menu edits. |
| `ui/files.py` | World save/load, exports, new-world, and exit dialogs. |
| `ui/dashboards.py` | Analytics, recent changes, debug windows, and callback errors. |
| `ui/base.py` | Shared canvas tags and Tk widget helpers. |

## Startup scene

The constructor sets up `TrafficSimulation` and `CityMap`, enables `blank_map`, centers the camera at 1×, builds the toolbar and primary canvas, binds mouse input, calls `draw_scene()`, creates debug/recent-events windows, and starts `tick()`.

`draw_scene()` creates grass using `city_map.terrain.grass_color`, draws visible
trees, and renders every authored `CityMap.roads` polyline as a layered road
surface. An empty world also shows centered construction instructions. The
fixed merge renderer remains isolated behind the non-city-builder mode while
traffic behavior is migrated to constructed roads.

### `#e83ccb` startup leak

`#e83ccb` is the main canvas `bg` fallback in the constructor; it is not a world color. The initial static grass rectangle may be drawn before the window manager gives the `pack(fill="both", expand=True)` canvas its final dimensions. If the canvas grows afterward, the exposed edge shows the fallback color until a world redraw.

`after_idle(self.draw_scene)` is not a reliable fix: it waits for Tkinter's current idle work, but the window manager can still issue a later resize. The reliable redraw signal is the canvas's `<Configure>` event, which occurs whenever its actual size changes. The UI should bind that event to `redraw_world()` (preferable to `draw_scene()` because it also updates signs and cars), ideally with debouncing if resize performance becomes a concern.

## UI state

| Attribute | Meaning |
| --- | --- |
| `simulation`, `city_map` | Traffic state and city terrain/map data. |
| `blank_map`, `running`, `simulation_speed`, `unit_system` | Current mode, pause state, time multiplier, and Imperial/Metric display choice. |
| `camera_x`, `camera_y`, `camera_zoom` | World-space origin and scale; zoom range is 0.35–3.0. |
| `_pan_anchor` | Previous pointer coordinate during a middle-button pan. |
| `selected_lane` | Lane governed by the following-gap slider. |
| `canvas` | Main world canvas. |
| `analytics_*`, `recent_*`, `debug_*` | Auxiliary windows and their canvases. |
| `tools`, `active_tool` | Toolbar tools loaded from `ui_tools/toolbar.json`, plus the current canvas interaction mode. |
| `recent_errors` | Latest three formatted Tk callback traces. |
| `last_time`, `last_dashboard_refresh` | Animation and dashboard refresh timing. |

## Controls and input

The toolbar is above the expanding world canvas and contains **File**,
**Simulation**, **Units**, **Inspect**, **Reset view**, **Build**, and a camera-use hint by default.
File and Simulation are standard dropdown menus; Inspect opens the live
editable panel in the canvas's bottom-left corner. **Build road** and **Build
building** open a similarly placed Buildables panel populated from
`ui_tools/buildables.json`; it shows the selected template's construction
specs rather than live inspection data. Reset view restores the appropriate default camera. The order and enabled state come from
`ui_tools/toolbar.json`; each concrete tool lives in its own module under
`ui_tools/tools/`. Adding a module and running `python3 -m ui_tools.sync_toolbar`
appends it to that JSON without needing changes in `ui/app.py`.

The far-left toolbar slot is reserved for an active canvas-tool dropdown. While
a dropdown-owned canvas mode is active, a blue copy of its button is docked in
that slot and its native menu stays posted without taking a popup grab. Normal
toolbar controls remain to its right and canvas clicks keep working. These
menus can open the shared Inspector without replacing the active canvas mode.

Persistent city models implement the `CityObject` inspection contract. A
constructed `Road` supplies its own title and properties—identity, lane counts,
lane width, total width, and centreline size—while the UI handles unit
presentation. Inspector hit testing covers the rendered road width. Buildings
are rendered from their persistent parcel footprints and are selectable above
the road layer.

Non-collinear road crossings and endpoint joins are explicit topology. Interior
crossings split each road, regenerate segment lanes, and create or reuse an
inspectable `Intersection` linked to every meeting road segment. Junction
surfaces cover segment seams in the renderer, and save files preserve both the
intersection ID and its segment references.
Crossings within 12 world units of an existing junction coalesce into that
junction, accommodating small placement differences from hand-drawn roads.
Each road segment derives geometric inputs and outputs from its directional lane
groups. Junctions connect incoming road outputs to outgoing road inputs and
generate non-U-turn lane connections. Those connections carry separate maneuver
and traffic-control definitions and form the vehicle layer of the city's generic
mobility network.

## Units

The model's canonical distances are pixels where one pixel is one foot, and its
stored speed limits are MPH. `config.py` names every conversion constant,
including `SECONDS_PER_HOUR`, `FEET_PER_MILE`, `METERS_PER_MILE`, and
`PIXELS_PER_MILE`; UI code uses `units.py` rather than repeating conversion
literals. This keeps the physics and existing save files stable.

`DEFAULT_UNIT_SYSTEM` in `config.py` selects `"imperial"` or `"metric"` for new
windows. The **Units** dropdown changes the live display without changing model
data. Speed signs, speed-limit prompts, Inspector speed/preferences/gaps and
positions, analytics, and exported graph values use mph/feet or km/h/metres as
selected. Save JSON remains canonical MPH/pixels.

The Inspector is the sole UI for simulation speed (0.25×–3×), fleet target
(1–30), selected-lane following gap (30–180 pixels), and live metrics such as
average MPH and exits/minute. This prevents those values from being duplicated
in the toolbar.

**Simulation → Performance graph** shows UI-tick frame time and FPS for the
most recent 20 seconds. Its samples use the raw interval between ticks, before
the simulation update clamps large elapsed time for stability, so pauses and
frame hitches remain visible in the graph.

| Input | Handler | Result |
| --- | --- | --- |
| Left click | `handle_tool_click` | Delegates the click to the selected canvas tool; Inspect selects and Build road adds a vertex. |
| Pointer motion | `handle_tool_motion` | Updates an active construction-tool preview. |
| Right click | `show_lane_menu` | Opens sign actions when a sign is hit; otherwise lane actions. |
| Middle press/drag/release | `start_pan` / `pan_camera` / `end_pan` | Pans the camera. |
| Wheel / Button 4 / Button 5 | `zoom_camera` | Zooms around the pointer. |

The lane menu edits gap or creates a sign using the currently selected speed
unit. The sign menu changes or deletes it. Sign hit testing takes precedence
over lane hit testing.

## Coordinates and render order

World coordinates map to canvas pixels using `screen = (world - camera) * camera_zoom`; `screen_to_world` is the inverse. `world_points`, `world_box`, and `visible_world_bounds` support canvas geometry and tree culling.

Tkinter draws later-created items above earlier items. The canvas layers, from back to front, are:

1. Static scenery: grass, trees, roads, junctions, buildings, and empty-world text.
2. Legacy cars and lightweight routed test cars.
3. Test-traffic source/sink markers.
4. Speed-limit signs: rectangle and text.

Static scenery shares `static` and is lowered after scene creation. Sign components share `speed_limit` and active frames raise that tag above cars. Existing car items are repositioned rather than recreated, so later-created cars remain above earlier ones where they overlap. `redraw_world()` rebuilds static scenery and signs, then updates cars.

The Inspector is a Tkinter `Frame` overlaid on the bottom-left of the canvas. It
is screen-fixed UI rather than a canvas scene item, so it stays above every
render layer and does not move with the camera. Each inspected field is rendered
as a slider, validated text input, or read-only label according to its
`InspectionRow` metadata.

## Auxiliary windows

| Window | Contents and refresh |
| --- | --- |
| Simulator debug | Merge diagnostics and tail of latest callback error; every frame. |
| Recent changes | Up to ten events from last 600 simulated seconds; once per second. |
| Traffic analytics | Up to 12 event markers, blue average-MPH line, orange exits/minute line; once per second while open. |

Closed windows are safe: their draw methods check `winfo_exists()` and the menu command recreates/raises them.

## Method ownership

| Methods | Responsibility |
| --- | --- |
| Module | Representative methods |
| --- | --- |
| `app.py` | `build_toolbar`, tool selection/delegation, `tick` |
| `renderer.py` | `draw_scene`, `draw_city_roads`, `draw_car`, `draw_speed_limits`, `redraw_world` |
| `viewport.py` | `world_to_screen`, `world_points`, `visible_world_bounds`, pan/zoom/reset methods |
| `interactions.py` | traffic controls, lane/sign hit testing and editing, unit selection |
| `files.py` | `save_state`, `load_state`, `new_world`, exports, `exit_app` |
| `dashboards.py` | analytics, recent changes, debug window, callback reporting |

The reusable tool lifecycle, toolbar JSON, automatic synchronizer, watcher,
and hand-coding example are documented in [`TOOLS.md`](TOOLS.md).

## Tick and file formats

`tick()` reschedules through `root.after(16, self.tick)` (about 60 Hz). It caps elapsed time at 0.1 seconds, advances running merge traffic by `dt * simulation_speed`, removes exited car items, redraws cars, raises signs, refreshes labels/debug every frame, and refreshes dashboards at most once per second.

World JSON uses the `lanesimulator.world` format and a numeric schema version.
It includes terrain, hierarchical roads, road-port movement controls,
parcels/buildings, display units, and camera state. Lane paths and structural
lane addresses are regenerated from their parent road centrelines during load.
Runtime cars, analytics, and
Tkinter canvas IDs are not saved. Legacy `merge_demo` JSON is rejected with a
visible error. **New world** replaces the `TrafficSimulation` and `CityMap`,
clearing the previous traffic, signs, metrics, and events before returning to
the empty city-builder view. CSV exports `simulation_seconds`, an `average_mph`
or `average_km/h` column based on the active display setting, and
`exits_per_minute`. The fixed 800×380 SVG contains the graph frame and blue
average-speed polyline labeled with the active unit; unlike the interactive
chart it omits flow and event markers.
