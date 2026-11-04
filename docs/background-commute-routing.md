# Background commuter routing handoff

The simulation owns actors, parking and inventories. A separate low-priority
worker builds destination shortest-path trees on an immutable native vehicle
graph; ctypes releases the Python GIL during the native search. The worker
returns a plan, and the owner checks current access and parking before native
admission. Replacing the road graph discards stale results. The simulation owner
itself has not moved to a separate thread.

Workers receive repeatable workplace/person departure offsets across two hours,
with the same offsets applied to shift ends. A zero departure window deliberately
creates synchronized demand. New commuters remain at home until admitted. Ready
driver plans receive an admission opportunity instead of rotating behind all
walking demand. Global trip starts, lot-entrance starts and active fleet road
vehicles are bounded independently.

Routing and departure-check allowances apply to fixed 50-ms movement quanta.
Event fragments share an allowance; an arbitrary bulk advance processes many
quanta and can consume many allowances. It is not a wall-time deadline. A frame
never waits on a routing future, but unrelated existing main-thread work can
still take longer than 50 ms.

Completed route links update observed travel times. Only partial lane traversals
are extrapolated to a full lane; road ports and junction links retain their own
measured times. Prior-day estimates are smoothed with weight 0.25 for new daily
observations. Drivers keep familiar routes unless alternatives beat a stable
individual threshold of 10–20%. Active routes do not change for ordinary
congestion; road edits still require recovery. The remaining-link index supports
finding active vehicles that still depend on a road.

Saves include logical pending trips, admission budgets, learned times, familiar
routes and active travel-observation progress. Native graph/tree caches and
futures are disposable. Seeded schedules repeat; asynchronous readiness can
change admission times slightly after loading or across runs. Accounting is
checked within floating-point tolerance. Resource/arrival fixtures explicitly
choose a zero-width window; independent tests verify the normal two-hour spread.

Explicit fleet dispatch outside a city update and the legacy standalone town
retain synchronous immediate-result behavior. Existing bus-leg and pedestrian
journey planning also retain their current APIs; this feature does not make all
application work asynchronous. No personal traffic-information model or live
congestion rerouting was added.

An independent review found inflated port observations and event-fragment budget
resets. Reproducing tests failed before the corrections and now pass. A separate
10,000-resident run exposed driver/walker queue starvation; a held-worker test
reproduces that case and verifies the completion-notification fix. Validation
also covers worker blocking with another moving vehicle, full/shared parking,
active limits, stale graphs, pending saves, repeated road edits and midnight.

The measured post-fix synchronized run uses 10,000 residents, 5,000 workers and
1,000 cars in one runtime. It completed 3,600 updates: mean 17.33 ms, maximum
689.23 ms, 412 cars moving and 124 parked at work at the endpoint. A 15-minute
spread run averaged 4.08 ms with a 344.03-ms maximum. Original synchronous
departure routing reached 43,590.30 ms. Admission policies and route costs differ;
these are scenario measurements, not an isolated algorithm-speedup claim or a
desktop guarantee. The spread run ends before the peak and neither covers a
full workday. See the saved configurations and metrics in benchmarks/arcata.
