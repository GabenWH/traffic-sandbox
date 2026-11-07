# Commute preferences and walking retention

The mode-preference system is scaffolding. Current `Resident.mode` still controls
car, walking, or bus trips. The new data model never selects a transport mode or
changes a resident's mode, and existing immediate fallback rules remain in place.

`runtime.parking_trips.preferences` owns neutral `ModePreferences` weights for
`car`, `walk`, and `transit`, plus parking observations. Weights are finite,
nonnegative relative preferences reserved for a future selector. `profile(id)`
returns a neutral profile; `set_profile(id, ModePreferences(...))` stores custom
weights without applying them.

Outbound commute attempts record an observation when parking is full,
inaccessible, or requires overflow; failed final walking access can also be
recorded. Retries of the same daily home/work trip are deduplicated. Shopping and
return journeys do not become outbound-commute observations, including when a
new purpose reuses the same endpoints as an earlier limited attempt.

`prior_parking(id, home=..., workplace=..., day=D)` returns immutable observations
for the same home/work pair from the preceding 14 days, excluding day D. The
model retains at most 14 observations per resident. No population scan runs on
each movement update. A future mode selector can consume this data at next-day
departure planning; probability, generalized travel costs, habit decay, and the
tradeoff between walking and available transit are intentionally not implemented.

Profiles and history are saved under `gameplay.commutes.parking.preferences`.
Older saves without that block load an empty model. Invalid weights, IDs,
schemas, duplicate records, and observations later than the saved day are
rejected. Observations naming a former home/workplace can remain in the bounded
history, but never match a different current trip.

## Retained walking data

`WalkingRouteCache` retains at most 512 full query paths and 65,536 geometry
units by default. A unit counts a route point, route link, or link point
reference; it is a retention budget, not a byte estimate. Oversized routes are
returned to their caller without entering the cache. Least-recently-used
entries are evicted incrementally. Active passengers and the native engine own
the routes they still need, independently of cache retention.

Registered native pedestrian lanes are indexed by exact binary float geometry
and crossing position. Their Python lookup no longer keeps graphs of point
tuples alive. Save files still contain their original coordinate arrays, and
restore reconstructs the compact lookup; identical restored/new walks share the
same native lane.

Parking searches yield the destination lot first. Cold alternative eligibility
queries share the existing four-query movement-quantum budget. A restored
capacity waiter checks its saved physical lots directly, then resumes normal
bounded admission instead of rebuilding every walking alternative in its wake
callback. Exact stall walking checks and explicit synchronous calls outside a
city update are separate from the alternative-eligibility allowance.

GC stays enabled. These changes bound hypothetical Python path retention and
remove eager search bursts; they do not guarantee that all city/GC updates fit
50 ms, or bound total registered native lane bytes over an arbitrary run.
`tools/benchmark_walking_retention.py` compares real cold Arcata admissions,
actual 50 ms updates for a difficult destination, and deliberately forced full
collections with a matched retained-query workload. It is a controlled
component experiment, not a completed two-hour commute throughput test.
