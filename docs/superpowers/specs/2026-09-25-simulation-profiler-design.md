# Simulation Profiler Design

## Goal

Expose simulation work per tick so performance issues can be separated from Tk/Panda3D frame cost and from the detailed per-car debug trace.

## Design

- Add a reusable, standard-library `SimulationProfiler` that records bounded tick samples. Each sample contains a system name, tick index, simulated time, elapsed simulation step, entity counts, and named block timings in milliseconds. The default history is 600 ticks.
- Compute mean, median, p95, p99, and maximum for each block from the retained samples. Export the same samples and summary as JSON, and samples as a wide CSV suitable for stress-test analysis.
- Instrument the routed traffic update at phase boundaries. The data-first path reports spawn, snapshot, observe, intent generation, conflict resolution, movement application, occupancy rebuild, post-update work, and total time. The legacy path reports its available coarse phases without adding per-car timers to the new profiler. Detailed per-car decision timing remains in the existing debugger.
- Add a separate simulation-performance window launched from the existing UI Performance window. It displays selected phases as a stacked per-tick graph; clicking a tick shows its block timings and entity counts. The existing UI frame graph stays separate.
- Keep the recording API generic so other systems, including later construction-vehicle systems, can submit a system name, counts, and block timings to the same profiler.

## Constraints

- No new runtime dependency.
- Timing history is bounded and stores no vehicle object references.
- The profiler measures phase boundaries every tick and does not add per-vehicle timing.
- `total` is shown in statistics and tick details but is not stacked with its component phases.

## Verification

- Unit tests cover bounded storage, statistics, validation, generic entity counts, and JSON/CSV output.
- An integration test confirms routed-traffic ticks populate the profiler when the detailed debugger is disabled.
- Dashboard tests cover phase selection and stacked timing data; run the complete `unittest` suite after implementation.
