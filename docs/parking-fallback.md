# Parking fallback, loading trucks, and idle fleet updates

This change addresses the parking-admission failure reported against
`689803efe3210068293a02acb1b280da40f8b4ce` on
`feature/background-commute-routing`.

## Cause and resulting behavior

The report's 208 cars blocked by full destination parking at 09:00 were still at
home. Admission required a free space at the exact destination. Full lots were
retried every 30 simulated seconds, inaccessible endpoints every 0.25 seconds,
and an outbound trip could disappear after the shift deadline. The fleet also
scanned parked records during ordinary observation and space availability checks.

Personal car trips now try the destination's lot and nearby public parking with
an actual pedestrian route to the destination. Parking capacity remains finite:
a space is claimed before road admission, including reservations held by cars
still in transit. Buildings sharing a lot share its capacity. Residential and
explicitly private parking are excluded from public overflow candidates.

After parking, the person walks from the physical space to the building. Work
attendance and shopping begin after that leg arrives. Return trips walk back to
the same car. Save/load preserves the car, space claim, pedestrian leg, and
destination. Trips between buildings sharing a lot leave the car where it is and
use a real walking leg.

When a usable car trip cannot be admitted, a feasible walk/transit trip can be
used. The car stays at its actual location and the resident's preferred mode is
retained. If no usable alternative exists, the trip waits on a parking-capacity
or access change. Unchanged full/inaccessible trips are not periodically retried.
Temporary route planning, road admission, and departure-rate limits still use
the existing scheduler.

Expired outbound waits produce explicit unmet-trip outcomes. An interrupted
return or walking connection retains a recoverable wait and its original
deadline; it can resume when access or capacity changes. Saves preserve both
waits and the latest unmet outcome for each person. Capacity released immediately
before a save is checked once after restoring.

## Parking geometry and policy

The implementation adds finite roadside parking bays using the existing
`ParkingLot` representation. It does not add a new moving-lane type. Bays are
outside the protected road deck and sidewalk, with short driveway connections.
Candidate geometry is checked against buildings, roads, junctions, existing
parking, and driveway surfaces.

Inference uses eligible walkable roads with at most two moving lanes and speeds
at or below 35 mph. Motorways, trunks, primary roads, elevated segments, and
segments without pedestrian access are excluded. Rows have up to six 22-by-10
foot spaces. IDs are stable; adding another destination can fill unused frontage
without moving existing parked vehicles or replacing their lots.

These are inferred gameplay parking spaces, not surveyed Arcata parking data.
Adding them deliberately changes the available supply. On the bounded Arcata
smoke scenario, supply increased from 2,964 lots / 8,990 spaces to 4,985 lots /
14,764 spaces: 2,021 additional curb lots and 5,774 spaces.

Two configurable `CommutePolicy` defaults bound alternatives:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `parking_walk_seconds` | 300 | Maximum planned walk for an alternate parking connection and car retrieval |
| `fallback_trip_seconds` | 1,800 | Maximum planned walk/transit fallback trip |

The parking search radius is derived from the walking budget at 4.4 feet/second;
an actual route and the selected stall's walking connection are checked before
admitting overflow parking. These defaults are gameplay choices, not calibrated
travel-behavior estimates.

## Trucks block the lane while loading

When a delivery destination has no geometrically fitting parking bay, a truck
can drive to a nearby safe loading position on its driving lane. A fitting bay
that is merely occupied retains ordinary parking-capacity waiting behavior.

At route completion, the native engine atomically changes the truck from a
moving actor to a stationary physical body. The body participates in following,
intersection clearance, merge observations, admission overlap checks, and nearby
pedestrian checks. It is excluded from the moving-driver update loop. Successful
departure consumes the same obstacle and starts at the same physical position;
failed departure leaves the obstacle in place.

Loading positions stay on a straight run with `truck_length / 2 + 4` feet of
clearance to each end or bend. The center can move at most one truck length plus
eight feet from the requested position. If no safe run fits within that range,
loading there is rejected. This fixes the reviewed case in which a truck exactly
on a right-angle bend intruded into the opposing lane.

Restore reinstates safe loading bodies and in-flight stopping flags. If an edit
removes the road or makes a saved stop unsafe, the truck retains its recorded
pose and cargo but stays suspended, with inaccessible departure. It is never
teleported onto a replacement road.

## Constant work for unchanged idle vehicles

Fleet occupancy and reservations are indexed by physical lot and space. The
ordinary observer visits active vehicles and changed records, and capacity
notifications wake relevant waiters. With no such changes, observation performs
constant work independent of the number of parked cars or parking waiters.
Stationary loading trucks are indexed native obstacles and receive no moving
driver updates.

This guarantee applies to unchanged idle simulation bookkeeping. Rendering,
explicit reporting, save/load, index rebuilds, and processing an actual change
can scale with population. Finding a physical stall still depends on the number
of spaces in that lot. Moving cars, including cars temporarily stopped in a
traffic queue, remain in the active traffic simulation.

### Controlled idle measurements

Measured with `tools/benchmark_fleet_idle.py`, using the same script against the
original commit and this worktree. Each case has one warmup and five repeats of
100 observations. Timing is the median of uninstrumented repeats; record reads
are counted in a separate pass. Setup, routing, native movement, and rendering
are excluded. Raw results are in `docs/parking-idle-validation.json`.

| Parked cars | Before: microseconds/observation | After: microseconds/observation | Before: record reads | After: record reads |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 5.127 | 0.356 | 200 | 0 |
| 1,000 | 47.431 | 0.457 | 2,000 | 0 |
| 16,000 | 750.369 | 0.398 | 32,000 | 0 |

Unchanged full-lot waiters at 100, 1,000, and 16,000 records measured 0.346, 0.362,
and 0.366 microseconds per observation, with zero record reads in each case.
No before-change waiter timing is claimed.

The native stationary-truck benchmark advanced one simulated day with either
zero or 128 stationary trucks. Both used 24 Python calls, zero native ticks, zero
driver visits, and zero obstacle-pose reads. Placement is excluded, and there
were no moving actors in this isolated benchmark. These measurements do not
measure total city speed.

## Validation

The original commit's suite passed 707 tests with 20 environment-dependent skips
in 360.593 seconds. After the final review fixes, the combined parking, fleet,
truck, and persistence regression group passed all 66 tests in 13.678 seconds.
Independent follow-up review confirmed both the bend collision and incremental
parking issues closed, with nine relevant regressions passing.

The existing post-visit retry regression now models a transient road-admission
blockage. Its previous zero-fuel fixture can legitimately walk home under the
new fallback policy. A separate regression verifies that walking return and
checks that the same car and physical parking claim remain at the bakery. Both
cases passed together in 3.386 seconds.

Final complete-suite coverage: **774 discovered tests verified: 754 passed,
20 skipped, zero failures or errors**. The skips require Panda3D and/or an X
display. The long-running final test session became unavailable before its
summary after recording 547 completed individual results. The remaining 227
tests passed in three disjoint groups (64, 93, and 70 tests). Source and test code
were unchanged during these segments. An exact test-ID manifest verifies that
all 774 discovered tests are covered, without omissions or duplicate counts.
The handoff includes all raw logs, group results, and the continuation runner.

Coverage includes one-free-space admission, no repeated static failures, return
car retrieval, shopping and delivery resource conservation, real walking legs,
saved attendance, saved waits/deadlines, release-before-save recovery, unsafe
road edits, physical truck blockage, and constant idle operation counts.

The save/load checks also exposed and fixed an existing validation mismatch:
operational worker attendance must be validated against operational job capacity,
not only a building's construction-worker requirement. Construction-phase
validation is unchanged.

### Bounded 16,000-resident smoke run

The imported Arcata map was initialized with 16,000 residents, 8,000 workers, and
1,000 household cars. Departures were deliberately synchronized at 08:00 instead
of using the original report's two-hour departure window. A 240-second total
wall-time budget included approximately 129 seconds of setup. The run completed
199.8 of the requested 300 simulated seconds, ending by the wall limit.

At that point, 3,999 commutes had started, 68 workers had arrived, and 316 cars
were driving. Fifty car trips had selected alternate parking and nine trips had
used mode fallback. The explicit wait index contained 12 blocked trips: one
waiting for parking and 11 for access. There were no expired-trip outcomes yet,
and resource balance error was approximately `4.91e-8`.

The remaining 4,001 not-yet-started commutes include the synchronized departure
backlog under the configured 20-starts/second budget. They must not all be
interpreted as parking failures. The legacy snapshot fields
`cars_blocked_by_full_destination` and `cars_blocked_by_missing_access` inspect
only the primary destination and can include trips not yet attempted or with
usable alternatives. Use `blocked_trips` and its grouped reason summaries for
actual static waits after this change.

This is a bounded behavior/scale smoke test, not a completed workday or week.
It ran alongside regression testing, adds inferred parking, and uses a different
departure schedule; its wall timings are not an apples-to-apples city performance
comparison with the original report. It preceded the final bend and incremental
inference fixes, neither of which changes this scenario's initial parking
inference or car-only workload.

## Reproduction

```sh
python -m unittest discover -s tests -q

python tools/benchmark_fleet_idle.py \
  --module-root /path/to/original-checkout \
  --label before-689803e --cases parked \
  --output build/idle-before.json

python tools/benchmark_fleet_idle.py \
  --label parking-fix --output build/idle-after.json

python tools/benchmark_truck_stops.py \
  --output build/truck-stop-idle.json

python tools/run_arcata_city_workday.py \
  --population 16000 --cars 1000 --start-hour 8 \
  --departure-window-minutes 0 --hours 0.08333333333333333 \
  --wall-seconds 240 --report-every 60 \
  --output build/arcata-16000-smoke
```

Diagnostics exposed by `CitySimulation.report()` include `blocked_trips`,
`blocked_by_destination`, `blocked_by_parking_lot`, `commute_unmet`,
`last_unmet_trips`, `stranded_trips`, `overflow_parking_trips`, and
`mode_fallbacks`. Detailed report construction is an explicit query, not part of
the constant-work idle observer.
