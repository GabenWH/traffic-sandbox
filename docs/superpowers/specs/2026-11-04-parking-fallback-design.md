# Parking fallback and idle vehicle processing

## Intent
Fix the 16,000-resident Arcata admission failure on `689803e`: full workplace
parking kept people at home without alternatives or a recorded missed trip.
Grace also requested parking lanes with walking access, trucks occupying driving
lanes while handling deliveries, and constant idle work for stopped cars.

## Decisions
- Retain reservation-before-driving. Search finite, physically accessible public
  parking near the actual destination; never use unrelated residential parking.
  Curb parking is represented as real spaces outside driving lanes. Validate the
  final pedestrian route (default maximum 300 seconds / 1,320 feet).
- Track driving and walking legs separately. Arriving at parking does not count as
  reaching work or a shop. A return trip walks back to the same persistent car.
- If no parking option works, allow a walking/transit fallback whose planned trip
  is at most 1,800 seconds. These are policy defaults, not calibrated behavior.
- If no route is feasible, keep the departure in an indexed wait queue. Parking
  releases and network changes wake waiters; an explicit deadline records an unmet
  trip. Do not retry a static failure every 0.25 or 30 simulated seconds.
- Maintain parking occupancy and active fleet indexes. Unchanged parked/waiting
  records require O(1) fleet work per update, plus actual arrivals/active cars.
  Geometry construction, changed capacity, routing and reporting may do more work.
- A truck without a fitting bay may stop at its actual routed lane endpoint for
  service. Native stationary occupancy blocks following/admitted traffic until a
  successful departure; it participates in no moving-car decision loop.
- Save/load and road edits preserve car location, trip legs, capacity claims,
  blocked trip outcomes, cargo and stationary truck occupancy.

## Approaches considered
Increasing lot capacities would hide the failure and lose finite physical space.
Retry backoff alone would reduce CPU but still strand trips. The implementation
uses real alternative parking and walking, bounded mode fallback, and change-driven
queues because those address both resolution and idle cost.

## Verification
Reproduce full-lot and missing-access failures before changes. Cover overflow
walking and return retrieval, shopping inventory, single-space contention,
missed shifts, save/load, road edits, truck blocking/clearance, and operation-count
checks independent of idle fleet size. Run the existing complete unit suite and a
bounded scenario; report controlled timing separately from the interrupted week.
