# Editor resize regressions

**Goal:** Exercise real editor behavior across representative window sizes and
window lifecycle transitions; fix failures demonstrated by those checks.

**Scope:** Resize/building-placement hang, 2D road construction, 3D cul-de-sac
geometry, and depth fighting reported on Linux/NVIDIA. Software GLX is available
for local integration tests; it cannot prove NVIDIA/compositor behavior.

1. Add a real Tk/Panda editor test matrix in `tests/test_editor_resizing.py`.
   Check both projection modes, all registered canvas tools, selection and
   overlays, road completion/cancellation/elevation, building placement,
   camera/picking round trips, dashboard windows, save/load/new, hide/show,
   rapid configure events and shutdown. Bound graphical checks by a subprocess
   timeout so a native hang fails the test rather than wedging the suite.
2. Add focused failing regressions for any confirmed geometry, camera or
   lifecycle failure before changing implementation. Run on the old code first.
3. Fix only demonstrated failures in `ui/view3d.py`, `ui/app.py`,
   `ui/scene_geometry.py` and `ui/scene_buffers.py` as necessary. Preserve
   simulation behavior and the shared map/perspective scene.
4. Run the resize matrix, the entire existing suite, and inspect rendered
   map/perspective frames. Document how to run display tests and the remaining
   hardware coverage limit.

The resize matrix includes 1x1, narrow, wide, tall, ordinary, large, queued
resizes, unmapped views, restore, and close with resize pending. This is a finite
set of representative boundary conditions, not every possible pixel size or
driver interleaving. Pure UI helpers remain covered by the existing unit suite.

## Findings and verification

- Reproduced the freeze with rapid resizing and building previews. A projected
  off-screen corner became `-1e9`; expanding its dashed outline generated
  invisible geometry until the process stalled. A guarded reproduction proved
  the call chain through `NativeCanvas.flush` and `GeometryBuffer.stroke`.
  Projection now preserves coordinates outside the viewport, and strokes clip
  before tessellation, retaining dash phase and recompiling on viewport changes.
- The initial matrix caught Tk dropping synthetic Enter after unmap/restore.
  The native key bridge restores a Tk keyboard target before dispatch.
- Hidden/closed views no longer render or publish actors. Output validity uses
  the common Panda graphics-output API, including offscreen buffers.
- Asphalt and curb share one angular partition and have disjoint interiors.
  Perspective depth precision scales with distance, capped by visible foreground
  depth so low-angle cameras still work in tall windows.
- Each confirmed failure was observed before its fix. Review found three
  additional failures (foreground clipping, offscreen buffer compatibility, and
  mismatched curb chords); separate regressions reproduced all three before
  correction. The resulting focused suite passed 19 tests. Final whole-suite
  verification passed all 984 tests in two independent 492-test batches, with
  zero failures, errors or skips.
- Inspected rendered map and perspective frames. Native OS input delivery,
  compositor minimize/maximize behavior, and the user's NVIDIA driver still
  require desktop verification. Tests use real Tk/Panda integration and direct
  editor/messenger events, with withdraw/deiconify covering parent unmapping.
