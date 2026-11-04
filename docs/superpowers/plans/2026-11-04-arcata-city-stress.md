# Citywide Arcata stress run

User target: import all mapped Arcata buildings and stress the updated simulator
with exactly 10,000 residents. Make the same test runnable on the user's machine.

- [x] Retrieve and cache a citywide extract with provenance and no new runtime dependency.
- [x] Import 4,500 municipal building records, including courtyard buildings; preserve land-use categories and voids.
- [x] Seed exactly 10,000 residents in existing capacity, 5,000 workers, and 1,000 simultaneously persistent cars. Randomize job assignments reproducibly.
- [x] Add a timed headless runner with 50-ms updates, live metrics, retained partial results, and stack diagnostics.
- [x] Remove repeated full-city scans from parking grouping and nearby-road search; keep disconnected sites visible in the results.
- [x] Run a real 10,000-resident smoke scenario, not independent replay trials.
- [x] Finish final regression checks and commit locally; publishing requires the user's GitHub approval.

Data: `benchmarks/arcata/arcata-buildings-citywide-2026-11-04.json.gz` plus adjacent
source metadata. Buildings are filtered against bundled municipal relation 112123.
Road geometry remains the cached June network to keep its coverage reproducible.

This benchmark tests commuting, shared parking, and household consumption. It
does not assign fictional cafes/farms/services to real mapped buildings. It is
distinct from the older synthetic 6,000-person resource benchmark.

Validation evidence: initial full suite 668 tests, no failures, two display skips;
targeted tests cover exact population, capacity refusal, fixed steps, partial
duration, wall limits, courtyard geometry, compressed data, and diagnostic thread
shutdown. Independent Shapely checks agree with all 12 source courtyard buildings
to within 1.2e-11 square feet.

Independent review found two regressions: a rejected courtyard could reappear as
its filled outer way, and a midpoint-only road index could disconnect dispersed
source groups. Both have reproducing tests and fixes. The final suite includes
those tests and the safe Python diagnostic watcher.

Final regression suite: 671 tests run, no failures, two display-dependent skips (353.650 s).
Full-city geometry QA checked 2,930 nonempty lot surfaces and all 8,990 spaces:
no lot/building or lot/road intersections, no overlapping lots, and no overlapping
spaces. All 1,019 Panda3D roof triangles for the 12 courtyard buildings remain
inside the filled building geometry, leaving courtyard voids empty.

The native 180-second smoke run completed in 331.70 wall seconds including map
setup. It found a 43.59-second departure spike; later median ticks were around
15 ms. Stack sampling shows Python vehicle-route graph copying/A* work. That
routing cost is a measured remaining bottleneck, not a solved performance claim.

An exploratory C-level faulthandler timer crashed while dumping a stack during
world restoration. Restoration without it succeeded. The shipped diagnostic uses
a tested Python watcher that captures only the main thread stack and does not
read or mutate world state; its actual 10,000-person diagnostic run completed.
