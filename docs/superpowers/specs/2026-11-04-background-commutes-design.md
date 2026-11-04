# Background commuter routing and learning

Grace authorized implementation and a GitHub push after discussing this design.
Existing civilians have priority over planning new trips. Commuters learn better
routes for the next day; ordinary congestion does not replace an active route.

## Behavior

- Use one low-priority native routing worker behind a bounded request queue.
  The worker reads an immutable vehicle graph and builds reusable destination
  shortest-path trees. It never reads or changes live actors, inventories or
  parking reservations. No simulation update waits on a routing future.
- Return paths to the owner thread, validate topology/access and then reserve
  parking and admit the vehicle using the existing native admission checks.
  Reject stale results after a road edit. Keep parked residents at home while
  waiting. Road-edit recovery remains mandatory and keeps actor identities.
- Assign repeatable workplace/person departure offsets across a configurable
  two-hour window. Shift ends move by the same offset. A zero-width window is
  an explicit synchronized stress case.
- Bound departure processing, route submissions, global trip starts and vehicle
  starts at each parking entrance. Defaults: 32 departure checks and 4 route
  submissions per update, 20 trip starts/second with burst 4, one car/second per
  lot, 2,000 active road vehicles, and at most 128 outstanding route requests.
  Here an update budget means one 50-ms simulation movement quantum. Event
  fragments share that allowance; a bulk advance processes multiple quanta.
- Observe travel time along completed route links. Shared smoothed estimates
  become routing costs on the following simulated day, with no feedback into
  today's route choices. Keep each driver's familiar route unless a candidate
  beats it by a stable individual improvement threshold (10–20%).
- Persist scheduling policy, queued logical departures, learned link times and
  familiar routes. Native trees/futures are disposable caches and are rebuilt
  after loading. Old saves receive defaults without losing actors or resources.
- Expose queue/admission/learning counters in the Arcata benchmark. Preserve the
  synchronized test and add realistic spread settings. Verify one runtime with
  10,000 residents, 5,000 workers and 1,000 cars.

## Approach

The measured update spent 34.92 of 44.82 seconds copying a Python graph for 766
route searches. A dedicated immutable native graph removes these copies and
allows ctypes calls to run without holding Python's GIL. Reverse Dijkstra trees
share search work among trips to a destination. A Python thread around the old
Python search would still compete for the GIL; a cooperative main-thread search
would require a different resumable search API. The native worker follows the
approved background-worker design and the existing native walking ABI pattern.

The legacy standalone TownSimulation API and explicit fleet dispatch outside
an update retain synchronous behavior for callers that request an immediate
result. All authored-city fleet dispatch during an update is nonblocking.

This change does not introduce live GPS rerouting, personal road-information
models, new dependencies, UI rendering changes, or a separate simulation owner
thread. Existing native movement remains owned by the simulation thread.
