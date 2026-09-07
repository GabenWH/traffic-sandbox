# Lane Simulator

An interactive, dependency-free Python city and traffic simulator. The current
city-builder foundation supports authored polyline roads with generated lane
children and versioned JSON world saves. The older fixed freeway merge remains
in the traffic engine while its behavior is migrated onto constructed roads;
it is no longer the world-save format.

Run it with Python 3:

```bash
python3 freeway_simulator.py
```

Use the **Units** menu to switch between Imperial (mph/feet) and Metric
(km/h/metres). Change `DEFAULT_UNIT_SYSTEM` in `config.py` to select the default
for new windows. The model keeps one pixel as one foot of roadway. The existing
Simulation and traffic-Inspector controls still target the older traffic engine;
connecting that engine to constructed-road routes and intersection controls is
the next integration milestone. Geometric crossings already split roads into
explicit, persistent intersection objects. Intersections generate directed
lane-to-lane movements, and the city compiles those movements into a layered
mobility graph searched by a transport-agnostic A* implementation. See
[`docs/ROUTING.md`](docs/ROUTING.md) for the routing model and extension points.

The city builder starts on a 5,000 × 3,500 grassy terrain map with deterministic
trees. The **Build** dropdown opens a JSON-backed Buildables catalog for road
and building templates. Roads use click-to-place polyline vertices with Enter
to finish; buildings use one-click footprint placement. Edit
[`ui_tools/buildables.json`](ui_tools/buildables.json) to add templates, and see
[`docs/BUILDABLES.md`](docs/BUILDABLES.md) for the schema. Use the middle mouse
button to pan, the mouse wheel to zoom toward the cursor, and **Reset view** to
return to the starting view.

Use **Test route** to click a starting and destination lane on constructed
roads. It draws the shortest directed A* route, highlighting lane travel and
intersection movements, from the exact clicked positions without requiring cars
or building demand yet. Intersections have real lane setbacks, and every
unconnected two-way road endpoint derives a visible cul-de-sac with turnaround
routing. One-way roads keep ordinary terminal endpoints. Clicking an
intersection or cul-de-sac in the route tester uses that whole junction rather
than guessing a nearby lane.

Use **Test traffic** to toggle intersections and cul-de-sacs as temporary
combined sources and sinks. Once at least two are enabled, each periodically
spawns a lightweight car routed to another enabled junction. Cyan/red rings
mark active endpoints; click one again to disable it, and press Escape to clear
the test traffic setup. These endpoints and cars are intentionally not saved.
Routed test cars now own an inspectable behavior brain: they accelerate and
brake, queue behind cars sharing the same current lane even when their later
turns differ, and obey authored all-way stops. A linear-time longitudinal
occupancy grid supplies nearby-car observations and prevents overlapping
movement or spawning onto an occupied lane.
Select a standard intersection with **Inspect** and set **All-way stop** to
`yes`; white stop bars show the controlled approaches. Cars decide when to
request entry after a complete stop, while a runtime coordinator records
arrival order and prevents conflicting claims. Equal arrivals use deterministic
clockwise approach order. Select a routed car to inspect its brain state and
wait reason. Traffic lights and the legacy freeway-car migration remain future work. Routed cars automatically use perfectly compliant turn signals:
left/right indicators activate 100 feet before a turn, U-turns signal left,
and the signal remains active until the car clears the movement.

**Roundabouts and uncontrolled intersections:** use the intersection Inspector's
**Junction type** field (`standard` or `roundabout`). Uncontrolled intersections
now yield to conflicting traffic and check for space beyond the junction.
Single-lane roundabouts use shared circular lane sections, yield-controlled
entrances, a 12 mph circulating speed and exit signals. Changing type clears
temporary cars so their routes can be regenerated. See
[`docs/JUNCTIONS.md`](docs/JUNCTIONS.md) for testing instructions and a plain-English
walkthrough of the reusable merge logic.

Roads and buildings also share persistent lifecycle, local inventory,
condition, and active-work state as groundwork for worker-and-resource-driven
construction and maintenance. This state is not yet used to gate routing or
building operation.

**Save** writes the generic city world, including terrain, roads and derived
road-port movement controls, parcels/buildings, display units, and camera state.
**Load** accepts
that versioned world format and reconstructs derived lane geometry. Traffic
runtime and canvas item IDs are intentionally not persisted.

Use the **File** and **Simulation** dropdown tools just as before. **Inspect** opens its panel in the bottom-left corner of the main canvas; while it is active, left-click a car, speed-limit sign, or lane to inspect and edit supported fields, or click empty space for global stats. Fields use sliders, validated text input, or read-only labels. The toolbar order and enabled tools are editable in [`ui_tools/toolbar.json`](ui_tools/toolbar.json); each tool has its own module in `ui_tools/tools/`. Starting the app automatically runs `ui_tools.sync_toolbar`, which appends newly discovered tools without changing existing order or enabled settings. See [`docs/TOOLS.md`](docs/TOOLS.md) for the full tool workflow.

Requires Python with tkinter (included by default with most desktop Python installations).

Run the model and persistence tests with:

```bash
python3 -m unittest discover -s tests -v
```
