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
- Virtual desktop attempt encountered denied Unix socket listeners; trying a local
  TCP X display to verify the embedded Tk/Panda behavior without escalation.
