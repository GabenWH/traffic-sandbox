# Freely rotating 3D city view and elevated roads

## Intent and success criteria

The city builder needs a freely rotating view in which roads can be drawn at different heights, including ramps and overpasses. Road construction uses Page Up and Page Down to change the height of the next point, in the style of Cities: Skylines or Workers & Resources. A road crossing another road at a different height stays separate in routing and traffic. The existing Tkinter toolbar, menus, and inspector remain the controls.

Success means a user can draw a ground road, draw a ramp and overpass across it, orbit to inspect the separation, route traffic over both roads without a false junction, save, and reload with the same geometry and connectivity. Existing ground-level saves still load.

## Rendering and application boundary

Panda3D renders the world inside a native child window hosted by a Tkinter frame. Tkinter controls remain; panels now overlaid on the Canvas move to a dock beside the viewport so they remain visible above the native render window. The launcher remains freeway_simulator.py. Tk owns the application loop and advances Panda3D through its task manager. City and traffic models remain independent of either GUI library.

An initial integration step proves that the embedded viewport displays, resizes, and receives pointer and keyboard input in the current Tk window on the target system. If same-window embedding fails, stop for a design revision; a separate 3D window does not meet this design. Panda3D becomes a documented runtime dependency.

A scene registry accepts providers of world objects and presentation adapters for their types. Each adapter creates, updates, and removes its 3D nodes and, when appropriate, declares a pick target and highlight behavior. The camera and picker do not contain a fixed list of object types. Terrain, trees, roads, junctions, buildings, signs, traffic, route highlights, and construction previews are the first adapters, not the complete set. Static geometry is rebuilt when its source changes; moving objects update their transforms each tick. Roads have visible decks and edges, elevated spans have supports, and buildings have simple extruded forms. Existing model positions and dimensions continue to use feet. The legacy merge scene is drawn on a flat ground plane from its existing simulation data.

The perspective camera orbits around a map target with right-drag, pans with middle-drag, and moves toward or away from the target with the wheel. A right click without a drag still opens its context menu. Camera pitch is bounded so the ground remains usable for editing. The saved view records orbit target, orientation, and distance. Older camera saves map to a default angled view.

## Road elevations and topology

Road.centerline remains a list of 2D points. A parallel list of heights, one per centerline vertex, stores elevation above the flat ground plane. Existing roads default to zero at every vertex. Road splitting inserts an interpolated height at the split point and preserves heights on both pieces. Generated lane paths remain 2D for routing and vehicle behavior; a road-height sampling function supplies 3D positions for meshes, markers, and cars.

While Build road is active, Page Up and Page Down change the draft vertex height in 10-foot steps, with ground level as the minimum. The first point starts at ground level unless it snaps to an existing road endpoint, in which case it inherits that endpoint height. Mouse picking intersects the plane at the draft height to place the next point. The preview displays the selected height and the sloped segment leading to it. A completed road interpolates height linearly between authored vertices. Tunnels and grade limits are outside this scope; ramp length is controlled by point placement.

Crossing detection compares interpolated heights at the planar crossing. It creates or joins a junction only when heights differ by at most one foot. Endpoint and existing-junction snapping use the same height rule. Junctions, including derived cul-de-sacs, retain an elevation so vertically stacked junctions can be drawn and selected independently. Roads crossing at different heights do not split or connect, so route search and intersection controls never treat them as a shared junction. Cars on a ramp receive visible height from their current road section; cars traversing a junction interpolate between its entering and exiting road heights. Traffic logic retains its current 2D lane progress and occupancy.

## Tools and input

A viewport-facing interaction API supplies world picking, screen projection for labels, highlights, and temporary geometry to tools. A pick returns a common hit record: world position and height, surface normal, distance, and a reference to the hit model object when there is one. Tools may filter hits by model capability, such as inspectable, buildable connection, or traffic endpoint, rather than requiring the picker to know each concrete type. Ground clicks use a ground-plane ray intersection; selectable objects supply their own hit geometry through their presentation adapters. Road construction uses the selected draft-height plane, so an overpass can be drawn across a road underneath it. Existing Build road, Build building, Inspect, Test route, Test traffic, and context-menu actions are the first consumers of this API. New object types can register a provider and adapter, then participate in drawing and picking without changes to the camera or picker. Tk panels continue to edit the same model objects.

## Saves and compatibility

Increment the world format version. New saves include per-road heights, junction heights, and 3D camera state. The loader accepts the current version 4 format, assigning zero heights and a default angled camera. It validates that every new road has exactly one finite, nonnegative height per centerline point. Derived lanes and cul-de-sacs are rebuilt on load as now. Runtime scene objects and Panda3D handles are never persisted.

## Verification

Headless tests cover height interpolation, road splitting, same-height versus grade-separated crossings, endpoint snapping, vertically stacked junctions, route connectivity, car height sampling, and version 4/new-format save loads. Tool tests cover Page Up/Page Down state, height-plane picking, preview values, and a registered example object that can be drawn and picked without changing camera or picker code. A manual graphical check covers Tk embedding, resize, panel visibility, orbit/pan/zoom, right-click behavior, construction from different camera angles, traffic on an overpass, and save/reload. The existing test suite continues to pass.

## Integration risk

Tkinter Canvas is a 2D drawing surface, so the current world drawing calls cannot become 3D through a projection change alone. The main implementation risk is native child window and input integration. Panda3D documents parent window handles and screen-to-scene picking, but the target system must be verified before model and tool migration proceeds.

References: [Tk Canvas](https://tkdocs.com/tutorial/canvas.html),
[Panda3D window handles](https://docs.panda3d.org/1.10/python/reference/panda3d.core.WindowHandle),
[Panda3D object picking](https://docs.panda3d.org/1.10/python/programming/collision-detection/clicking-on-3d-objects),
[Panda3D main loop integration](https://docs.panda3d.org/1.10/python/programming/tasks-and-events/main-loop).
