# Constructed-road traffic consolidation

The application has one driver: `cpp`. Python supplies world edits and trip requests, C++ advances traffic, and Python consumes results/events. The old Python drivers are retained only in `tests/reference_traffic.py` and historical lab/comparison helpers for independent tests. They cannot be selected through `RoadVehicleSimulation`, the interactive app or the production merge lab.

## Conflict resolution and feature inventory

User rule: newest authored behavior wins; prefer data-first when dates do not decide a conflict. Explicit instructions for this consolidation take precedence over older behavior.

| Feature | Provenance / decision | Consolidated behavior |
| --- | --- | --- |
| Snapshot, intents, conflict resolution, batch movement | Data-first pipeline, retained by native port f5d0c4e (October 24) | C++ staged pipeline; list order does not select a driver mode |
| Following, speed caps, cautious/rolling merges, queue-front priority, stop dwell and compatible claims | Native port plus independent legacy/data-first regression scenarios | C++ decisions and clearance; Python unit helpers remain testable |
| Signal phase boundaries, scheduled plan changes, missing-controller closure | 3bee2f8 (October 26), newer than original cpp branch | Retained fixed-time controller policy and C++ aspect admission |
| Signal occupancy without approach reservations | 3bee2f8, newer than original fixed-time claim behavior | Body occupancy continues through yellow/all-red until rear clears |
| Signal merge entry speed | Newer Python signal rewrite; omitted in the initial C++ signal port | C++ now latches the admitted merge speed and caps it while physically inside |
| Yellow dilemma commitment | Native signal state plus Python import/mutation contract | ABI 4 carries the latch so world edits/backend recreation preserve it |
| Intentional red waits | Newer Python signal rewrite | C++ does not age signal-only waits into deadlock recovery |
| External coordinator reservations | Existing coordinator API and priority regressions | Imported as native world blockers and republished; explicit edits invalidate native state |
| Seeded spawning, capacities, clearance, graph routing, precise lane endpoints | f5d0c4e | Retained in C++; no Python routing/spawning fallback |
| Construction and road deconstruction delivery/export trips | fa6fe82 (October 25), newer than cpp branch | Retained, now dispatched to C++; completion events apply deliveries |
| Profiler and debugger | Native phase timings take precedence over old Python microphase names | Native stage timings, decision facts and per-tick traces retained |
| Shared-memory output | a8a1c13 (October 26) | Optional output representation, not another driving mode |
| Python occupancy mirror | Latest user instruction for this consolidation | Dirtied in O(1) on native ticks; refreshed only on a Python query or explicit editing publication |
| Vehicle edits, resize, route replacement, reorder, removals and network changes | Union of existing mutation APIs | Explicit edits invalidate/reimport native state without per-frame Python polling |

The original `cpp` history was merged while keeping the newer source tree: `main` already contained the native engine files plus later signals and road deconstruction. No cpp-only files were removed. This branch then applies the consolidation and behavior fixes above.

The older fixed-freeway demonstration and economy are separate from the three constructed-road drivers and remain Python. Signal scheduling is world policy supplied by Python; C++ makes every per-car admission decision.

## Validation

See tests/test_cpp_consolidation.py for sole-driver selection, fail-explicitly behavior, no Python driving/occupancy scans during ordinary ticks, current on-demand queries, world edits, yellow-latch preservation in both output representations and intentional-red deadlock handling. Existing road deconstruction, delivery, signal clearance, admission, route mutation and independent C++/Python differential tests remain enabled.

Native-profile phase names replace implementation-specific Python microtimings. Tests that formerly counted Python routing or per-car signal callbacks now require zero such calls while preserving motion/admission assertions.


## Results

The final complete suite ran 495 tests successfully, with 17 skipped. Independent review found and drove regressions for stale occupancy after scalar edits, a chained green-signal deadlock, retained old-brain callbacks, and live deadlock settings; all were fixed and tested. The native/reference differential tests remain independent.

The post-change 600-tick signalized-crossing trace recorded **zero calls** into Python occupancy query or maintenance methods during native updates. See `docs/cpp-occupancy-trace.json`; Python reference calls remain visible in that diagnostic report.

Three counterbalanced pairs against pre-consolidation commit a8a1c13 used fixed fleets, 5 warmup seconds and 30 measured seconds at dt .05. Both runs used copying output and read every car's position, heading and signal each update. Phase groups were ordered by geometry to avoid generated-ID variation. Compilation and setup were excluded. Active populations, completions and display-state checksums matched every pair. These are synthetic crossing loads; timings are process CPU on the shared runner and exclude actual UI drawing.

| Initial cars | Previous C++ CPU/update | Consolidated CPU/update | CPU reduction |
| --- | ---: | ---: | ---: |
| 60 | 0.5919 ms | 0.4044 ms | 31.7% |
| 1,000 | 9.3431 ms | 4.0157 ms | 57.0% |

Detailed per-run timings and measured source digest are in `docs/cpp-consolidation-profile.json`. Reproduce with `python tools/benchmark_cpp_consolidation.py --baseline-root <checkout-of-a8a1c13> --output build/cpp-consolidation.json`.

Admitted vehicle identity is read-only; replacing a vehicle uses remove/admit. Scalar and driver edits notify the simulation even while the backend is absent. Coherent route edits use `replace_vehicle_route`; direct route metadata edits invalidate the backend, but callers must keep geometry and movement metadata consistent. Detached/replaced brain objects cannot modify the former owner's occupancy. Python index private fields may remain stale until a public query refreshes them.
