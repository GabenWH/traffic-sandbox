# Multilane traffic implementation plan

Goal: use same-direction lanes outside-first, permit safe left passing and right return, and remove artificial junction funnels.

Architecture: preserve saved aggregate road movements and their control IDs, derive lane-specific routing connectors at graph compilation, and transfer lane adjacency to C++. C++ selects lanes and reserves both lanes during smooth transitions. Publish route changes as events rather than Python per-car driving decisions.

Constraints: feet/seconds, screen Y down, right-hand traffic, C++17 driver, no opposite-direction passing, retain destination and signal policy. Existing single-lane behavior should be unchanged. Lane choice must preserve the remaining road itinerary and exact destination. Adjacent lane movement only; keep front/rear clearance and prevent simultaneous conflicting requests.

Tasks:
- [x] Add real-engine regressions for three-lane distribution, nonconverging junction paths, passing/return, unsafe rear gaps and lane drops.
- [x] Derive lane-specific junction paths without changing saved road-port policies; synchronize original signal IDs to derived movements.
- [x] Register directional lane groups and implement native lane selection, route changes, smooth geometry and dual occupancy.
- [x] Publish changed routes and preserve transition state through native backend recreation.
- [x] Run targeted tests, full suite, dense multilane safety checks and review the diff.

Review focus: reverse direction lane ordering, curved geometry, partial external routes, live control edits, backend recreation during a lane change. Keep roundabout aggregate interfaces compatible with existing ring routing.


Implementation record:
- Shared phantom policy extracted to merge_policy.h; lateral observations use a moving joining ruler and finite occupancy duration, rather than a second driving strategy.
- Original signal-policy IDs remain compatible with saved worlds. Derived lane IDs also work.
- Fresh review reproduced four integration issues and a cache-identity issue; each received a behavioral regression: roundabout geometry, signal aliases, backend recreation, explicit placement and exact destination isolation.
- Additional external-trip admission test exposed entry-lane selection missing from externally supplied paths; native generated and external admissions now share best_entry_route.
- Final validation: 19 focused multilane tests pass. Complete unittest discovery executed all 598 tests in four isolated module groups: 581 passed, 17 skipped for display/Panda3D requirements; no failures/errors. Groups ran 159, 186, 29 and 224 tests, all exit 0. The earlier 60-test native regression run also passed.
- Existing road-to-road turn permissions are retained; lane expansion must not force detours for exact lane-position origins. Covered by an additional regression.
- Initial feature review findings were reproduced, corrected and regression-tested. The feature was subsequently integrated with newer main changes and checked again.
