# Native Panda3D Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Share native Panda3D scenes between 2D and 3D and remove Python fleet presentation loops.

**Architecture:** C++ scene library with a small ctypes ABI, bulk immutable map
uploads and synchronous reads of the existing native traffic buffers. Python
retains Tk controls and a retained editor-overlay adapter.

**Tech Stack:** C++17, Panda3D 1.10.16 SDK/runtime, NumPy, ctypes, Tkinter, unittest.

**Spec:** docs/superpowers/specs/2026-11-08-native-panda-viewer-design.md

## Global Constraints

- 2D behavior takes precedence for conflicting controls.
- Preserve world saves, existing gameplay and the traffic ABI.
- Never borrow native traffic buffers across mutations or threads.
- Use local spatial batches and native actor updates; no per-frame Python fleet loop.
- Native viewer errors are explicit. Do not merge or push without authorization.

## Review Focus

- Engine recreation must not leave stale borrowed pointers or metadata.
- Ramps, connectors and stacked roads must use the actual route height.
- Switching projections must retain editor selection and both saved camera states.
- Empty/replaced fleets and changed parked state must remove old visuals.
- Right-click and wheel behavior must follow 2D controls in both views.

### Task 1: Native scene and build boundary

Files: native/viewer/{scene.h,scene.cpp,actors.cpp,abi.cpp}, native_viewer.py,
tests/test_native_viewer.py, native/viewer/README.md.

Interfaces: NativeScene(root, overlay_root, camera), replace_static(triangles,
lines), register_vehicle(handle, visual, heights), update_native(engine,time),
replace_parked(records), stats(), close().

- [ ] Write and run failing real-scene tests for map replacement/batching,
  native actor buffers and route-height interpolation.
- [ ] Implement SDK discovery, safe ABI validation, native batching and instancing.
- [ ] Run the real-scene tests against the installed runtime; record evidence.

### Task 2: Model compilation and revision-based synchronization

Files: ui/scene_buffers.py, ui/scene_presenter.py, persistent_fleet.py,
traffic_testbed.py, tests/test_scene_presenter.py.

Interfaces: compile_city(city) -> triangle/line arrays; route_heights(city,car)
-> distance/height array; ScenePresenter(scene).update(city,simulation).

- [ ] Write failing tests for ramps, overpasses, roster invalidation, appearance
  changes, parked state and clearing/replacing the native engine.
- [ ] Implement static compilation and change-driven metadata publication.
- [ ] Verify unchanged fleet updates consume native buffers without Python actor reads.

### Task 3: Shared viewer and editor integration

Files: ui/view3d.py, ui/native_canvas.py, ui/app.py, ui/renderer.py,
ui/gameplay.py, ui/viewport.py, ui_tools/{buildables_panel.py,tools/inspect_tool.py},
freeway_simulator.py, tests/test_native_view_controls.py.

Interfaces: shared PandaWorldView with map/perspective modes, retained canvas
overlay API, existing editor callbacks and saved camera state.

- [ ] Write failing control/projection and hidden-world-drawing regression tests.
- [ ] Switch native mode to one scene and camera projections; preserve the editor
  overlay/panel contract and use 2D controls where behavior conflicts.
- [ ] Remove hidden canvas actor work and unconditional extra frame delay.
- [ ] Verify existing GUI wiring, picking, preview, save and mode-switch behavior.

### Task 4: Rendering, performance and delivery

Files: tools/benchmark_native_viewer.py, docs/NATIVE_VIEWER.md, README.md.

- [ ] Render both camera modes through real headless Panda/EGL and inspect output.
- [ ] Measure fixed active fleets and Arcata geometry with separate native-update
  and graphics timings; verify instance and geometry counts.
- [ ] Run the complete regression suite and review the whole change independently.
- [ ] Commit the completed work locally and report measurements and remaining gaps.
