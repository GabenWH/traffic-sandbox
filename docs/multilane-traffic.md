# Multilane traffic

Constructed roads now retain separate lanes through ordinary junctions. Road-to-road controls and save-file movement IDs remain the authoring interface; the vehicle graph derives lane-specific ports and connectors from those policies. Same-width through movements preserve lane order. Widenings expose the additional lanes, and lane drops use the existing shared-target merge system. Existing road-to-road turn permissions remain reachable from each approach lane; conflicting turning paths retain normal junction arbitration. Roundabout approaches connect each lane to the existing shared single circulating lane with continuous measured geometry.

C++ chooses the least occupied reachable entry lane, breaking ties outside/right first. A three-lane road therefore fills outside, middle, inside before putting another vehicle behind the outside vehicle. This applies to generated traffic and external junction-to-junction requests, including construction and commute trips. A precise lane-position origin remains exact.

A faster follower can request the adjacent lane on its left. Stopped queues can redistribute into an adjacent lane with fewer cars ahead. Drivers return right when the downstream gap is clear. Changes preserve the remaining sequence of roads and the requested destination; a lane needed for a turn or an exact destination cannot be abandoned without a reachable route. Short approaches conservatively keep their lane when there is insufficient distance to complete a change.

## One phantom merge policy

`native/traffic/merge_policy.h` contains the shared arrival projection, gap acceptance, phantom-leader selection and speed-matching policy. Existing ramps/roundabout entries/lane drops and new parallel-lane changes call the same `merge_choice` and `gap` methods. The lateral adapter supplies observations from the target lane's ordered occupancy index. Its moving joining ruler covers the three seconds spent occupying both lanes; fixed connectors retain their existing joining ruler and regressions.

Cars reserve both source and target lanes throughout a lateral move. Later requests observe those reservations, so simultaneous lane changes cannot claim the same space. Following constraints apply to both lanes. Smoothstep interpolation moves the displayed vehicle over three seconds, and its heading and turn signal follow the transition. A five-second interval between starts prevents oscillation.

`native/traffic/multilane.h` holds adjacency, lane choice, cached alternative routes and lateral geometry. This is distinct from the shared merge policy: it chooses where to attempt a merge, rather than defining another merge strategy. All driving decisions remain in C++. Python supplies static topology and materializes route-change events for renderers, inspection and optional occupancy queries.

The boundary case where two uncommitted vehicles stop exactly at their common yield line is handled as waiting traffic. They do not become phantom priority vehicles merely because their front reaches the line; claims still arbitrate entry.

## Route and state integrity

Route cache identity includes whether the destination is a junction or an exact lane position. Spawning unrelated traffic cannot relax another vehicle's destination. Engine recreation retains a live lane change and its reservations. Explicit placement or route replacement cancels the old transition; speed/control edits preserve it. Original road-policy signal IDs and derived lane-movement IDs both work, with conflicting protected permissions still rejected.

The C ABI is version 5. The binding recompiles the native library automatically when its sources change. Reloading an existing Arcata save regenerates lane topology; the map/scenario does not need reauthoring. Benchmark results need a new run because traffic distribution changes. The initial feature branched from main at `7748cf8` and has since been integrated with the current native viewer, routing, parked-vehicle and caching changes.

## Validation

```sh
python -m unittest discover -s tests -p 'test_multilane.py' -v
python -m unittest discover -s tests -p 'test_native*.py' -v
python -m unittest discover -s tests -v
```

The new cases cover three-lane entry order, external trips, exact origins/destinations, six cars forming two rows at red and clearing green, lane drops, fast rear traffic, phantom speed matching, left passing and right return in both travel directions, curved paths, dense body clearance, multilane roundabout geometry/traffic, signal aliases, engine recreation, and explicit placement. Existing native tests compare trajectories against the Python reference across ramp, slip-lane, roundabout, stop and signal cases.

The full suite can run headlessly with `env -u DISPLAY`; display-dependent tests then skip. No wider Arcata performance claim is made by these focused tests.

Verified 2026-11-09: **19 new multilane tests passed**. The complete discovered suite ran all **598 tests**, grouped by module across four isolated headless processes: **581 passed, 17 skipped, 0 failures/errors**. Skips require a display and/or Panda3D. Native compilation uses C++17 with `-Wall -Wextra -Werror`. That count and result describe the initial feature branch; the subsequent integration with current main is verified separately.

The integration checks also cover stopped trucks and buses in either lane, resuming a stopped vehicle at the original position, signal-policy edits without per-tick connection scans, exact versus flexible route endpoints, and invalidation of recycled native route slots.

After integration with main at `43e227a`, the complete headless suite ran **925 tests: 922 passed and 3 display-dependent tests were skipped**. Additional coverage checks persistent fleet and bus mileage, trip learning, viewer metadata, and saving and restoring lane changes.

Known existing limitation: vehicles in neighboring lanes can overlap on sharp 90-degree bends. This also reproduces on the pre-integration main branch and requires a separate road-geometry fix.
