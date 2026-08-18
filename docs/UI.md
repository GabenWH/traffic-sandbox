# UI reference

`ui.py` contains the Tkinter presentation layer. `FreewaySimulator` owns the windows, widgets, camera, canvas rendering, dialogs, and exports. Traffic behavior remains in `simulation.py`; model types remain in `models.py`.

## Startup scene

The constructor sets up `TrafficSimulation` and `CityMap`, enables `blank_map`, centers the camera at 1×, builds the toolbar and primary canvas, binds mouse input, calls `draw_scene()`, creates debug/recent-events windows, and starts `tick()`.

`draw_scene()` first creates grass using `city_map.terrain.grass_color`, then draws trees within `visible_world_bounds()`. While `blank_map` is true, it adds centered instructions and returns. Road surface, edges, lane markings, and labels are drawn only after loading a `merge_demo` save.

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
**Simulation**, **Units**, **Inspect**, **Reset view**, and a camera-use hint by default.
File and Simulation are standard dropdown menus; Inspect opens the live
editable panel in the canvas's bottom-left corner. Reset view restores the
appropriate default camera. The order and enabled state come from
`ui_tools/toolbar.json`; each concrete tool lives in its own module under
`ui_tools/tools/`. Adding a module and running `python3 -m ui_tools.sync_toolbar`
appends it to that JSON without needing changes in `ui.py`.

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

| Input | Handler | Result |
| --- | --- | --- |
| Left click | `handle_tool_click` | Delegates the click to the selected canvas tool; does nothing when no tool is selected. |
| Right click | `show_lane_menu` | Opens sign actions when a sign is hit; otherwise lane actions. |
| Middle press/drag/release | `start_pan` / `pan_camera` / `end_pan` | Pans the camera. |
| Wheel / Button 4 / Button 5 | `zoom_camera` | Zooms around the pointer. |

The lane menu edits gap or creates a sign using the currently selected speed
unit. The sign menu changes or deletes it. Sign hit testing takes precedence
over lane hit testing.

## Coordinates and render order

World coordinates map to canvas pixels using `screen = (world - camera) * camera_zoom`; `screen_to_world` is the inverse. `world_points`, `world_box`, and `visible_world_bounds` support canvas geometry and tree culling.

Tkinter draws later-created items above earlier items. The canvas layers, from back to front, are:

1. Static scenery: grass, trees, blank text, road, edges, lane markings, lane labels.
2. Cars: wheels, body, headlights, windshield.
3. Speed-limit signs: rectangle and text.

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

## Method reference

| Methods | Responsibility |
| --- | --- |
| `__init__`, `build_toolbar` | Initialize state and create compact tool controls. |
| `select_tool`, `deactivate_tool`, `update_tool_buttons`, `handle_tool_click` | Maintain the active canvas tool and delegate clicks. |
| `draw_scene` | Replace static scenery for current camera and mode. |
| `world_to_screen`, `screen_to_world` | Convert one point between world and screen. |
| `world_points`, `world_box`, `visible_world_bounds` | Project geometry and derive current visible bounds. |
| `redraw_world` | Rebuild scenery/signs and update cars after camera change. |
| `start_pan`, `pan_camera`, `end_pan`, `zoom_camera`, `reset_camera` | Maintain camera interaction. |
| `draw_car`, `oriented_box`, `screen_oriented_box`, `create_car_details` | Create and position rotated vehicle visuals. |
| `add_car`, `clear_cars`, `toggle_running` | Manage the fleet and pause state. |
| `set_simulation_speed`, `set_traffic`, `select_lane`, `set_selected_lane_gap`, `set_unit_system` | Apply Inspector controls, preserve selected-lane state, and change presentation units. |
| `lane_at`, `show_lane_menu`, `speed_limit_at`, `show_speedlimit_menu` | Hit-test and display right-click menus. |
| `prompt_for_gap`, `add_speedlimit`, `change_speed_limit`, `delete_speed_limit`, `draw_speed_limits` | Edit and render lane/sign state. |
| `show_analytics`, `draw_analytics` | Open and render the metric graph. |
| `create_recent_changes_window`, `draw_recent_changes` | Open and render event timeline. |
| `report_callback_exception`, `draw_merge_debug`, `create_debug_window` | Capture errors and maintain diagnostics. |
| `export_csv`, `export_svg`, `save_state`, `new_world`, `load_state`, `exit_app` | Handle persistence, fresh-world reset, export, and shutdown. |
| `tick` | Advance traffic, update visuals/labels, refresh dashboards, schedule next frame. |

The reusable tool lifecycle, toolbar JSON, automatic synchronizer, watcher,
and hand-coding example are documented in [`TOOLS.md`](TOOLS.md).

## Tick and file formats

`tick()` reschedules through `root.after(16, self.tick)` (about 60 Hz). It caps elapsed time at 0.1 seconds, advances running merge traffic by `dt * simulation_speed`, removes exited car items, redraws cars, raises signs, refreshes labels/debug every frame, and refreshes dashboards at most once per second.

Save JSON includes scenario, time, lane gaps, signs, and cars; only `merge_demo` is accepted on load. **New world** replaces the `TrafficSimulation` and `CityMap`, clearing the previous traffic, signs, metrics, and events before returning to the blank-map view. CSV exports `simulation_seconds`, an `average_mph` or `average_km/h` column based on the active display setting, and `exits_per_minute`. The fixed 800×380 SVG contains the graph frame and blue average-speed polyline labeled with the active unit; unlike the interactive chart it omits flow and event markers.
