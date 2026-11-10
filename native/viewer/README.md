# Native Panda3D scenes

C++ owns Panda geometry, 500-foot static batches, instanced actor meshes and
native traffic snapshot consumption. `native_viewer.py` builds a cached shared
library using the project's C++17 compiler and exposes its small ctypes ABI.

## Setup

Install the Python requirements and the matching **Panda3D C++ SDK development
headers**. The tested SDK/runtime is 1.10.16. The Python wheel supplies renderer
libraries but does not include development headers. SDKs built with Eigen also
require Eigen3 headers.

```bash
python -m pip install -r requirements.txt
export PANDA3D_INCLUDE_DIR=/path/to/sdk/include/panda3d
export EIGEN3_INCLUDE_DIR=/usr/include/eigen3
python freeway_simulator.py
```

`PANDA3D_SDK` can instead name a prefix containing `include/`, `include/panda3d/`
or `usr/include/panda3d/`. On macOS the official SDK headers normally reside in
`/Library/Developer/Panda3D/include`. Set `PANDA3D_LIBRARY_DIR` when the matching
runtime libraries live outside the installed Python `panda3d` package.

`CXX` selects a GCC/Clang-style C++ compiler; `PANDA3D_CXXFLAGS` adds build flags.
The loader detects the old libstdc++ string ABI used by Linux manylinux wheels.
SDK headers and runtime must have compatible versions and build options. The
build helper currently supports Linux/macOS toolchains, like the native traffic
build; an MSVC build configuration is not supplied.
The instancing shader requires OpenGL 3.3. This migration was verified on Linux
with EGL and embedded GLX windows; macOS graphics execution is not yet verified.

Missing dependencies and compilation failures are explicit errors. There is no
silent fallback. Use `--viewer tk` to select the legacy Tk map intentionally.

## Ownership

Map uploads copy contiguous XYZ/RGBA arrays into local native meshes. Invalid
geometry leaves the previous scene intact. Python compiles these buffers on
world edits, not on every frame. Appearance and route-height rulers are published
on roster/map/visual changes. Native presentation obtains pose buffers directly
from the traffic ABI, consumes them synchronously and never retains engine
buffers across calls. It does not search all lanes to infer vehicle height.

Vehicles, pedestrians and parked cars use shared instanced geometry. Parked cars
are republished on fleet changes and have local finite culling bounds. Simulation
time and native signal bits control lamps. Python retains the Tk/Panda window,
camera and editor command bridge; unchanged active fleets have no Python pose
iteration. Both engine operations and presentation run on the UI/simulation
thread; this migration does not introduce concurrent world mutation.

## Verification

```bash
python -m unittest discover -s tests -q
python tools/benchmark_native_viewer.py --output build/native-viewer/benchmark.json
python tools/benchmark_native_viewer.py --arcata --output build/native-viewer/arcata.json
```

Fixed-fleet benchmarks check pose parity and separate metadata publication,
steady-state presentation and graphics. Fixed snapshots do not advance traffic.
Headless Mesa graphics timings are software-render measurements, not desktop GPU
FPS or evidence of 500,000-vehicle capacity.

### Editor resize regressions

Run these with the matching Panda SDK and a display (your normal desktop display
also exercises your actual driver):

```bash
python -m unittest tests.test_editor_resizing tests.test_native_overlay_clipping tests.test_viewer_depth tests.test_cross_view_orientation -v
```

For a headless Linux runner, prefix the command with `xvfb-run -a`. The live
editor checks are skipped without `DISPLAY`; a headless run alone does not
verify them. Each editor scenario runs in a separate process with a 90-second
timeout and stack dumps so a native crash or a stalled event loop fails visibly.

The matrix covers every registered canvas tool in map and perspective modes,
eight window sizes from 1x1 through 1600x900, narrow/tall/wide layouts, queued
resizes, hidden and restored parents, and shutdown with a pending resize.
Behavior checks cover road completion/cancellation/elevation, building placement,
camera picking, inspection, routes, test traffic, bus lines, demolition,
new/save/load, graph/profile exports and secondary diagnostic windows. A rapid
stress case interleaves building clicks with 160 resize cycles. This finite
matrix is not exhaustive coverage of every function, pixel size, window manager,
GPU driver or event ordering.

Off-screen editor strokes are clipped before dash tessellation, preserving dash
phase without allocating geometry for invisible spans. In particular, the
regression uses a billion-pixel preview endpoint that previously froze the UI
while generating invisible geometry. Perspective depth precision and the cul-de-sac's disjoint
asphalt/curb surfaces have separate numerical and geometry checks.
