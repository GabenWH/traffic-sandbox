# Native Panda3D viewer scenes

Authorized by Grace's request to migrate viewer scenes to C++ Panda3D, following
the shared 2D/3D renderer discussion. Where controls conflict, 2D behavior wins.

## Outcome

One Panda scene serves the top-down orthographic map and perspective view. C++
owns Panda geometry, spatial batches, vehicle/pedestrian presentation, height
interpolation and instance-buffer updates. Python retains the existing editor,
gameplay, save format and Tk panels. Constant-cost Python window/event plumbing
is acceptable; per-frame Python iteration over the active fleet is not.

## Boundary

Python compiles immutable static model geometry to contiguous numeric buffers on
world edits. C++ creates and owns the resulting Panda meshes, grouped into local
500-foot cells. Actor appearance and route-height rulers are registered when the
roster, route, appearance or map changes. The native presenter reads the existing
traffic ABI's numeric state buffers synchronously and never retains borrowed
engine buffers across calls. Parked presentation is republished only on fleet
changes. Existing native engine recreation and world replacement invalidate
presentation bindings. No global nearest-lane search occurs during presentation.

Cars, trucks and pedestrians use shared model geometry and GPU instancing.
Turn indicators derive from simulation time and per-instance signal bits.
Static map buffers and parked snapshots have explicit ownership; failed uploads
must leave the previous scene intact. Empty fleets clear the previous actors.

The Python Panda bindings retain the embedded window and camera integration;
the C++ scene shares that exact Panda runtime. Building requires matching Panda
SDK headers, a C++17 compiler and Eigen when the runtime uses it. Missing build
dependencies are explicit errors, with setup instructions. A legacy Tk mode is
available explicitly for compatibility and diagnosis, without silent fallback.

## Interaction and compatibility

Middle-drag pans, wheel zoom preserves the world point under the pointer, right
click opens the existing context menu. Perspective orbit uses Alt+middle-drag.
Existing keyboard shortcuts, inspector/build panels, route overlays, endpoint
picking, building placement and saved 2D/3D camera states remain supported.
Editor overlay primitives are retained separately from world geometry and
render through Panda rather than a second hidden canvas renderer.

The native viewer is the application default. The shared world scene is not
rebuilt on a projection toggle or camera motion. Tk dynamic world drawing is
disabled in native mode. Frame scheduling subtracts work from the target frame
interval instead of adding an unconditional 16-ms delay.

## Approaches

The chosen approach is C++ Panda3D, reusing the existing engine and geometry
contracts. SDL3 with a custom native renderer would also permit shared views,
but requires replacing rendering, resource management and editor integration.
Keeping both independent world renderers would preserve duplicate presentation
work and was rejected in the discussion.

## Validation

Real C++ scene tests cover batching, empty/replaced scenes, route heights on
ramps/stacked roads, copy/shared traffic state, engine recreation, parked changes,
signals, pedestrian removal and ABI input validation. Integration tests cover
orthographic/perspective projection, 2D control precedence, editor overlays and
suppression of hidden Tk world drawing. Headless EGL renders verify both camera
modes. Arcata and fixed-fleet benchmarks separate metadata, native presentation,
render submission and total frame cost; software-render results are identified.

Full regression tests remain required. Desktop-only gaps must be stated rather
than described as visually verified.
