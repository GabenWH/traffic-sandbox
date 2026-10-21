# Persistent occupancy comparison

## Change

Lane-section lists and spatial-cell entries now persist between snapshots.
Each car has an advancing route window; ordinary updates visit only the
sections intersecting its body and 22-foot rear-clearance shadow. Membership
changes when cars cross boundaries, claims change, routes are replaced, or
cars enter/leave the simulation. Lane entries remain ordered by position.

Committed merge shadows transfer to ordinary target-lane occupancy without
double entries. Captured positions remain unchanged until the next index
synchronization, preserving the data-first frame snapshot. Leader queries
start at the retained lane entry when available and stop once even the longest
vehicle cannot have a closer rear bumper.

The historical `rebuild()` API now synchronizes retained data rather than
discarding and reconstructing it. Generic occupancy-car inputs remain supported.

## Validation

- Full suite: 317 tests run, 17 skipped, no failures.
- Nine focused regression tests cover entry persistence/order, exact section
  boundaries, merge-shadow removal/handoff, despawning, rewinds, route and
  object replacement, mixed vehicle lengths, snapshot positions, local route
  reads, and bounded leader queries.
- The production vehicle cursor test constructs 1,000 real lane links. The
  old method fails its steady-motion read limit (1,503 reads); the new method
  passes while preserving exact boundary, rewind, replacement, and endpoint results.
- Exact before/after comparison over 1,600 dense slip-lane ticks matched car
  positions, speeds, active claims, and completed vehicles on every tick.
- Exact before/after comparison of 40,000 leader queries on moving 200-car
  Arcata snapshots matched the selected leader and bumper gap.
- Read-only review found no critical or important issues. The missing direct
  production-cursor test identified during review was added and passed.

## Alternating index measurement

Both index implementations updated the same moving 200-car Arcata snapshots
for 200 frames. Execution order alternated each frame. Median index-update
time fell from **2.460 ms to 0.716 ms**, about **71% lower**. Both implementations
used the same vehicle-position method, isolating the retained-index change.
This excludes vehicle admission and route discovery.

## Matched simulator measurement

Before: [active-claims run](../active-claims-matched-300s-2026-10-17/report.md).
After: [persistent-occupancy run](report.md).

Both used the same Arcata network, seed 20261017, 16 portals, 0.5-second spawn
interval, 100-car cap for 150 simulated seconds and 200-car cap for 150 seconds.
Both spawned 213 cars, completed 13, peaked at 200, and averaged **184.76 cars**
in stage two. All values below are stage-two milliseconds per update.

| Phase | Before mean | After mean | Before P95 | After P95 |
|---|---:|---:|---:|---:|
| Total update | 34.930 | 28.902 | 58.077 | 51.819 |
| Snapshot | 5.243 | 1.918 | 6.037 | 4.225 |
| Occupancy section mapping | 6.403 | 1.197 | 7.399 | 3.065 |
| Occupancy position lookup | 1.379 | 0.398 | 1.695 | 1.262 |
| Occupancy bin maintenance | 0.687 | 0.174 | 0.853 | 0.402 |
| Occupancy finalize / lifecycle | 0.125 | 0.284 | 0.204 | 0.753 |
| End-of-batch occupancy update | 4.953 | 1.629 | 5.154 | 3.770 |
| Leader lookup | 1.971 | 0.852 | 2.839 | 2.373 |
| Exit-gap lookup | 2.699 | 1.257 | 3.564 | 3.195 |
| Movement application | 6.805 | 8.243 | 8.936 | 15.588 |

Internal occupancy phases sum the two frame synchronizations and overlap the
major snapshot/end-of-batch phases; do not add all table rows together.

Section mapping used about **81% less mean time**; total update used about
**17% less mean time**. The entire 300-second run took 121.639 wall seconds,
versus 146.582 before, excluding route precomputation. Lowest rolling update
rate was **18.761 updates/second**, with no 5-updates/second threshold breach.

These are individual runs on a shared host. The preceding run had a large
transient stall; this run did not. Some unrelated phase timings increased,
including movement application. Treat the total percentage as an observed
run comparison, not a guaranteed speedup. The alternating snapshot measurement
provides separate evidence for the occupancy-index improvement.
