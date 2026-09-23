# 3D road view and overpasses

## Intent and success

Add a freely rotating 3D view for building and inspecting roads while keeping the existing Tkinter toolbar, menus, and panels. Road construction is the first use of height in the city world. Page Up and Page Down set the next road vertex's elevation, so a player can build ramps and an overpass. A road crossing below an overpass must remain separate in the mobility graph. Road heights and the 3D camera must survive save and load, and existing ground-level saves must continue to work.

This milestone covers roads. Building placement, inspection, test traffic, and other tools remain available on the 2D map. Selecting one of those tools returns to that map. The 3D scene is assembled through registered model adapters so later work can add pedestrians, transport, sewage, power, lakes and rivers, and depots with material piles or loading areas. Sewage and power retain separate domain rules. Those systems and 3D editing tools for them are future work.

## Tkinter and Panda3D boundary

Panda3D renders into a native child window inside a Tkinter frame. Tkinter still owns the application loop, toolbar, and road buildables panel; its timer advances Panda3D's task manager. The road panel docks beside the viewport because a Tk Canvas overlay cannot cover the native child window. The main launcher stays `freeway_simulator.py`. Panda3D is a documented dependency for the 3D mode, while the 2D mode can run without it.

The 3D camera orbits around a target with right-drag, pans with middle-drag, and zooms with the wheel. Pitch and zoom have usable limits. A scene registry maps model types to drawing adapters; the current adapters draw flat terrain and roads. Road decks follow authored heights, with visible edges, dividers, and supports for elevated spans. Additional systems can register scene adapters without changes to the camera. Model-specific 3D picking and editing APIs can be added when those systems are implemented.

## Road height and connectivity

`Road.centerline` remains a list of planar points. A parallel `elevations` list stores one finite, nonnegative height per vertex, in feet. Existing roads default to zero. The rendered deck interpolates between vertex heights. Splitting a road interpolates the split height and preserves it on both pieces. Generated lane paths remain planar for current routing and vehicle behavior.

While Build road is active, Page Up and Page Down adjust the next vertex height by 10 feet, with ground level as the minimum. Clicking an existing road endpoint to start a road inherits that endpoint's height. Screen picking intersects the current height plane, and the preview shows the draft segment at the selected height. Enter completes a road; Escape clears the draft. Ramp length follows the placed vertices. Tunnels and automatic grade limits are outside this milestone.

Road crossings create a junction only when their interpolated heights differ by at most one foot. Endpoint and junction snapping use the same height rule. Junctions and derived cul-de-sacs retain elevation, allowing vertically stacked roads to remain separate for routing. The current traffic simulator and its vehicle drawing remain in the 2D view.

## Persistence and verification

World format version 5 stores road and junction elevations and optional 3D camera state. Version 4 worlds load with all roads at ground level and a default angled 3D camera. Scene nodes and Panda3D handles are runtime objects and are never saved.

Headless tests cover height interpolation, splitting, crossing separation, stacked junctions, save compatibility, camera state, and road-tool height controls. Live graphical tests cover the embedded child window, picking an elevated endpoint, Panda key events, the Tk road panel, and clearing old geometry for a new world. A visual check confirms that the overpass and ground road render at separate heights. The full existing test suite must continue to pass.

References: [Tk Canvas](https://tkdocs.com/tutorial/canvas.html),
[Panda3D window handles](https://docs.panda3d.org/1.10/python/reference/panda3d.core.WindowHandle),
[Panda3D object picking](https://docs.panda3d.org/1.10/python/programming/collision-detection/clicking-on-3d-objects),
[Panda3D main loop integration](https://docs.panda3d.org/1.10/python/programming/tasks-and-events/main-loop).
