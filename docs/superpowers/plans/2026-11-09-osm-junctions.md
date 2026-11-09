# OSM junction import repair

**Goal:** Import real roundabouts as dedicated roundabout intersections and
preserve stop/yield/signal controls as working, persistent movement policies.

**Architecture:** Keep topology and tag interpretation in the OSM importer.
Use existing intersection geometry, shared merge behavior, native drivers and
fixed-time signal controllers. A persistent intersection flag opts into a
generated default signal plan; explicitly supplied runtime plans take priority.
OSM does not supply phase timings: defaults use 20 seconds green, 3 yellow,
1 all-red, one incoming lane per phase (including lane-specific movement IDs).

**Scope:** Repair `build_city`, used by all Arcata scenario/import commands.
Closed roundabout components (including split ways) become one intersection;
incomplete rings retain source geometry and are reported. Mini-roundabouts use
the same dedicated type. Untagged local multi-arm junctions receive inferred
all-way stops; highway merge/continuation nodes retain shared yield behavior.
Mapped approach signs affect their downstream junction and travel direction.
No invented traffic lights. Roundabout entries retain yield control.

## Tasks

- [x] Reproduce ring-as-roads and discarded-node-controls failures with small
  real importer fixtures, including split/incomplete rings and directional signs.
- [x] Add focused `tools/osm_junctions.py` topology/control helpers; retain and
  merge node tags, collapse closed rings before building roads, and apply
  controls after movement generation. Report mapped/inferred counts.
- [x] Persist the map's default signal opt-in and initialize its conflict-safe
  plans at network binding, preserving explicit runtime overrides and missing
  controller fail-closed behavior for other signals.
- [x] Verify import/save/reload and actual native movement; run the repository
  test command and audit the bundled Arcata map. Document source limitations.
- [x] Review the final diff, fix significant findings, and commit the branch.

## Review focus

Split OSM ways must produce a single ring. Boundary-truncated rings must not
collapse. Upstream signs must not control reverse traffic or unrelated nearby
junctions. Roundabout controls must not become all-way stops. Signals must
survive world saves and eventually give every protected movement green.

## Evidence and decisions

- Baseline `test_intersection_controls.py`: 10 tests pass.
- The bundled June road extract has 14,258 nodes, all without tags. Node tags
  cannot be recovered from that file; mapped lights require tagged input.
- Work is on `fix/osm-junctions`, based on `26bd72c`, in a fresh checkout.
- OSM API bulk node retrieval succeeded for every one of the 10,078 road-node
  IDs. The offline supplement includes 146 stop/yield/signal nodes and 76
  turning-circle/loop nodes. Geometry coordinates remain from the road file.
- Repaired Arcata: 1,141 roads, eight roundabouts, 199 terminal turnarounds,
  six signal junctions, 100 mapped sign junctions, 384 inferred stop junctions.
- Twenty-one focused regressions pass, including actual C++ red/green movement,
  multilane signal conflict validation, boundary holes, split-way signs and
  save/reload. All six Arcata signal programs passed every phase's validation.
- Road/building import regressions: 12 pass. A previous exact road-count
  assertion was updated because roundabout arcs are now generated ring lanes.
- Whole-branch review found sign propagation against a one-way road and through
  two-approach roundabouts. Three new regressions reproduced those cases, then
  passed after restricting propagation to legal ordinary-road continuations.
- Actual Arcata native smoke: eight roundabout trips admitted and all eight
  completed, including a 5,997-foot route; no vehicles remained (343.6 seconds).
- Full suite on the implementation: 946 tests, no failures, three display-only
  tests skipped (287.851 seconds). Matching Panda3D SDK and Eigen were supplied.
- Latest main bus/waiting-rider changes (`23ec1fd`) integrated without conflicts;
  119 focused import, control, native signal, cache, bus and gameplay checks
  passed on the combined result (52.856 seconds).
