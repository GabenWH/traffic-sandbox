# Execution ledger — native-panda-viewer

Base: 091eab9c90de78a1b897e88ac5e10dc5ed62723c.
Branch: feature/native-panda-viewer in an isolated worktree.
User authorized implementation and specified 2D controls as authoritative.

- SDK probe: matched Panda 1.10.16 headers to the wheel's C++ runtime and old
  libstdc++ string ABI; native NodePath creation succeeds. Eigen is required.
- Preflight: all tasks share NativeScene and retained overlay contracts; no
  incompatible interfaces identified. Python window plumbing remains constant
  work and is outside the per-vehicle presentation loop.
- Baseline: focused viewer/camera/geometry/gameplay tests executed; an initial
  command named a nonexistent test_viewport module and was corrected.
- Ruling: execute the user's chosen migration directly; preserve Python editor
  plumbing and move scene work through a native C ABI. Cost if wrong: editor
  integration may require an additional native host later; no gameplay rewrite.
- Ruling: use Alt+middle for perspective orbit, preserving 2D right-click menus.

- Task 1: native scene, atomic static uploads, native height rulers and C ABI implemented.
- Task 2: static buffers, route-aware elevation, metadata revisions and direct native
  pose reads implemented. Real pose-property rejection test passes.
- Task 3: shared native map/perspective window, retained editor overlays and 2D
  control precedence implemented. Focused combined run: 36 tests passed.
- Headless EGL rendered both projections and native overlay text successfully.
- Embedded Tk/Panda verified using a virtual X display over local TCP. The final
  GUI run passed 12 checks, including elevated construction, endpoint snapping,
  saved camera restoration, new-world replacement and retained route overlays
  following perspective camera changes.
- Independent review completed once against the whole migration. Its five
  Important findings were elevated roundabout heights, camera-driven overlay
  invalidation, missing map pavement/markings, parked appearance invalidation and
  missing bus queue labels. All were fixed with reproduction tests.
- Review's two smaller findings (editor stroke width/dash and truck/bus turn
  indicators) were also fixed. Width/dash affects road placement feedback;
  indicators communicate vehicle intent, so neither was deferred.
- Additional inspection found the live debug panel formatted every vehicle each
  frame to display eight. A failing ninth-record access test reproduced this;
  the formatter now receives only the eight displayed vehicles.
- Review-fix focused checks: 45 passed, followed by 17 checks covering the debug
  bound, truck/bus lamp geometry, blink buffers and existing car-brain behavior.
- Final whole-suite run: 880 tests in 249.473 seconds; 877 passed and three
  display-only tests skipped. All three passed in the separate 12-check embedded
  Tk/Panda run. No final review findings remain deferred.
- Python compile checks and `git diff --check` pass.
- Final matched benchmark runs both adapter orders, 80 samples per order, with
  real fixed fleets and pose parity assertions. Native steady-state means:
  1 car 0.00391 ms; 60 cars 0.00566 ms; 250 cars 0.01433 ms; 1,000 cars 0.05032 ms.
  Height-supplied legacy means: 0.01331 / 0.79220 / 3.67010 / 18.97803 ms.
  Initial publication is separate (1,000 cars: 5.88 ms); native p95 at 1,000 is
  0.08486 ms. These are presentation CPU measurements, excluding graphics.
- Final Arcata render inspected in both projections: 1,181 roads, 4,500 buildings,
  2,964 parking lots; 1,273 local static meshes, 310,866 triangles, 40,053 lines.
  Static compilation/upload 1.365 s; llvmpipe render/sync means 9.35 ms map and
  14.22 ms perspective at 960x640. No active actors in those graphics cases.
- Raw samples, source hash and runtime identity are committed at
  benchmarks/native-viewer-2026-11-08.json. Linux EGL/GLX verified; macOS graphics
  and target desktop GPU frame time remain unmeasured. The setup guide records
  matching SDK/Eigen requirements and the current compiler/platform boundary.
- Delivery stays on feature/native-panda-viewer; keep the isolated worktree.
  No remote push, merge or PR is authorized in this request.
