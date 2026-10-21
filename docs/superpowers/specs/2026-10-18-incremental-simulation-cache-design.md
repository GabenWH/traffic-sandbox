# Incremental simulation caches

Date: 2026-10-18

Status: cache foundation and junction lookup implemented; remaining subsystem
migrations are proposed. See `docs/SIMULATION_CACHES.md` for the usable API.

Reviewed base: `perf/persistent-lane-occupancy`, commit `e3e377d`.

## Goal

Retain derived simulation data until the inputs that determine it change. Apply
small changes to maintained indexes instead of rediscovering their contents every
tick. Preserve the branch's traffic decisions, deterministic ordering, physical
clearance checks, and fixed position snapshot during observation.

Success is fewer map/route scans, cache builds, and lane sorts with identical
vehicle-state results. A particular timing improvement is not assumed in advance.

## Decision and alternatives

Add a small, standard-library `simulation_cache.py` module containing explicit
source revisions and lazy cached values. Keep domain-specific collection updates
in their owning systems. A cached function and an incrementally maintained index
solve different parts of this problem.

| Option | Useful capability | Fit for this simulator |
| --- | --- | --- |
| `functools` / `cachetools` | Memoized calls; `cachetools` also provides bounded cache storage and eviction policies. | Useful for pure lookups. The application still has to supply correct keys and invalidation for mutable simulation state. Expiry by elapsed time is unsuitable for correctness-sensitive traffic state. |
| `reaktiv` | Lazy computed values with automatic dependencies between signals. | The closest existing alternative. Its documentation explicitly says that in-place changes to mutable objects are not detected. Adopting it would still require mutation ownership and snapshot rules, and would not incrementally maintain lane lists. |
| Local revision cache, recommended | Explicit source dependencies, lazy replacement, and guarded mutations. | Fits the existing topology revision and mutation methods; adds no runtime dependency or reactive callbacks to the tick loop. |

This recommendation concerns the integration requirements. It does not claim a
measured speed advantage over `reaktiv`; that has not been benchmarked.

References: [Python 3.12 functools](https://docs.python.org/3.12/library/functools.html),
[cachetools](https://cachetools.readthedocs.io/en/latest/),
[reaktiv computed](https://reaktiv.readthedocs.io/en/latest/api/compute-signal/),
[reaktiv mutable values and batching](https://reaktiv.readthedocs.io/en/latest/core-concepts/).

## Rules that make reuse safe

1. A cache declares every source that can affect its result. Dependencies are
   source revisions, never a cached value's last successful build number.
2. Each mutable source has one owner. Production mutations use that owner's
   methods; public container views are read-only. A decorator cannot observe an
   arbitrary assignment to `car.distance` or an in-place list edit.
3. Builders return immutable metadata or read-only snapshots, and have no random
   draws or simulation side effects. A frozen dataclass containing a mutable
   dictionary is not sufficient; use immutable contents or a read-only mapping
   over a private copy.
4. Position, speed, stopping distance, and numerical gap checks remain current.
   Small movements are not ignored using an epsilon or time-to-live policy.
5. Observation reads a coherent published occupancy snapshot. Partial movement
   application or partial index publication must not be visible to queries.
6. Claim arbitration may change claim state during resolution. Later claim
   requests must see earlier accepted claims immediately, while positions remain
   frozen. A single global 'freeze everything for a tick' rule would be wrong.
7. Cached entries belong to a world or vehicle incarnation. Despawning and
   recreating a vehicle with the same string ID cannot reuse its old state.
8. Exceptions never cause an old, invalid value to be returned as a fallback.
   Failed partial mutations invalidate dependent caches before propagation.
9. Full recovery is allowed for initialization, topology replacement, explicit
   rewind/route replacement, or a detected invariant failure. It is not normal
   frame maintenance.

## The small cache module

### Foundation interface

```python
class RevisionSource:
    def __init__(self, name: str) -> None: ...
    def stamp(self) -> RevisionStamp: ...
    def mutate(self) -> ContextManager[None]: ...
    def read_only(self) -> ContextManager[None]: ...

class CachedValue(Generic[T]):
    def __init__(
        self, name: str, *,
        dependencies: tuple[RevisionSource, ...],
        build: Callable[[], T],
    ) -> None: ...

    @property
    def dependencies(self) -> tuple[RevisionSource, ...]: ...
    def get(self) -> T: ...
    def clear(self) -> None: ...
    def info(self) -> CacheInfo: ...
```

`RevisionStamp` contains a unique source token and its monotonically increasing
integer generation. The source token is owned for that source's lifetime, not a
reusable raw `id()` integer. `CacheInfo` reports hits, builds, and failed builds.

Create cache slots once with their owners. `get()` compares the small tuple of
dependency stamps against the saved tuple. An unchanged tuple returns the saved
value. A changed tuple runs the builder once on demand and replaces the saved
value only after successful completion and a second dependency check. `None` is
a valid cached value, distinct from an uninitialized slot.

Changing a source is an integer increment. It does not walk a registry, notify
every subscriber, or rebuild anything immediately. No cache-wide sweep or
per-frame `clear()` is needed. A hit costs O(number of declared sources), which
must remain small and independent of the number of cars or route segments.

`mutate()` checks the write guard before the owner's data is changed, rejects
reads of dependent caches while open, and increments the generation on exit.
Nested mutation scopes for the same source coalesce into one increment. The
increment also occurs if the body raises, because the owner may have changed
part of its data. This is an invalidation scope, not transactional rollback.
Owners check for no-op changes before opening the scope.

`read_only()` prevents mutation of that source for the duration of a simulation
read phase. Cache builders may call other cache readers but cannot enter any
source mutation scope; recursive evaluation of the same slot raises a cycle
error. A builder error leaves the old slot invalid and propagates to the caller.
The first implementation runs on the existing simulation thread.

Dependencies remain explicit and flat. A composed cache includes the union of
its component caches' root source dependencies. Depending only on another
cache's last build would be unsafe if that inner cache had not yet been read
after an input changed. Dependency declarations are reviewed and tested beside
the corresponding owner mutation methods.

Example of the intended ownership pattern:

```python
active_sources = RevisionSource("active sources")
active_junctions = CachedValue(
    "active junctions",
    dependencies=(topology, active_sources),
    build=build_active_junction_tuple,
)

# Inside toggle_junction, only after establishing that the selection changes:
with active_sources.mutate():
    update_selected_junction_ids()

junctions = active_junctions.get()
```

Per-key consumers use owner-scoped dictionaries of slots and remove slots when
their owner disappears. Keep only the latest version of each logical entry;
including every historical generation in a memoization key would retain stale
generations unnecessarily.

## Source ownership and invalidation

| Source | Mutation boundary on this branch | Data retained until it changes |
| --- | --- | --- |
| Topology / world incarnation | Existing `CityMap.mobility_revision`, observed in `sync_network`; replacing the map creates a new source lifetime. | Junction-ID lookup, network metadata, existing spawn-route cache. Do not introduce a second independent topology revision authority. |
| Active sources | `toggle_junction`, clearing test traffic, and pruning selections after topology replacement. | Active junction tuple and destination candidates for each source. |
| Vehicle roster | `admit_route`, completed-vehicle removal, `remove_vehicle`, and clear operations. | ID-sorted observation tuple and vehicle-ID lookup. Test-traffic count is maintained on add/remove. |
| Vehicle route | Vehicle creation and a new owner method for route replacement. | Route starts/ends, controlled movement lookup, next-roundabout indexes, incoming-lane references, and signal boundaries. |
| Vehicle dimensions | Explicit dimension replacement. | Body-window thresholds and maximum-length bookkeeping; update the vehicle's occupied sections. |
| Per-vehicle route progress | Nose/rear crosses a relevant boundary; explicit placement or rewind. | Route, control, roundabout, and occupancy-window cursors. Ordinary distance arithmetic remains fresh. |
| Per-intersection and per-car claims | Coordinator claim/release/forget methods, only for effective changes. | Claims grouped by intersection and per-car claim snapshots. |
| Per-intersection arrivals | Adding/removing an arrival or replacing its movement. | Local queue and priority dependency facts, keyed by the actual request and relevant topology/claim revisions. Frozen arrival times retain their existing semantics. |
| Published kinematics | Accepted movement batch; include speed-only changes and merge-plan changes. | Dynamic merge facts only within the matching published epoch. |
| Per-lane membership/order | Section entry/exit, merge-shadow changes, admission/removal, route replacement, or actual order inversion. | Ordered lane entries and their neighbor/index relationships. Position changes alone do not imply a new membership order. |

Expose the mutable roster and coordinator dictionaries through read-only views;
route production writes through their methods. A roster replacement/reordering
API handles test/lab setup explicitly. Add `place_vehicle` for the direct distance
assignments currently used in `merge_lab.py` and tests. Shape and route replacement
must use equivalent owner APIs before their metadata is cached.

The network source adapts the existing `(map incarnation, mobility_revision)`
token. `sync_network` already checks that token once per update; preserve its
current route clearing and vehicle cancellation behavior when it changes.

Source-selection caching must preserve destination ordering and random draws.
Cache the base destination tuples, then copy and shuffle at the same scheduled
attempts as today, including capped attempts. Do not put random operations in a
cache builder or change the seeded traffic stream.

## Route data: cache facts and advance cursors

Introduce `traffic_route_state.py` to own immutable route metadata and a small
per-vehicle cursor state. Build incoming-lane and signal-boundary references once
with the route, rather than scanning backward or constructing a previous-segment
list in every observation.

Advance a cursor when the vehicle crosses its next boundary. Preserve separate
next-route-movement and next-controlled-movement semantics: a claimed movement
can be behind the nose while its claim remains active until the rear clears.
Claim acquisition/release can change which control is next even before a route
boundary is crossed. Rewinds and route replacement reset using indexed ranges.

For `_route_cruise_speed`, cache which roundabout range applies; calculate its
distance-dependent braking speed each tick. Do not cache the final speed result
solely on a route revision.

## Occupancy: update the index with deltas

The cache module does not wrap `rebuild()` and make its scans disappear. Extend
`TrafficOccupancyIndex` with `add_vehicle`, `remove_vehicle`, and
`publish_changes` operations. The existing `rebuild(cars)` remains for initial
load, exceptional recovery, and comparison tests.

After accepted movement, the simulation supplies changed vehicle records rather
than asking the index to discover changes by scanning the complete roster. Reuse
the retained entry objects. Update their captured positions for moving cars;
reevaluate section/cell membership only for moved, resized, rerouted, or
claim-changed vehicles. Maintain roster presence and length counts through
add/remove events instead of constructing a presence set and finding the maximum
vehicle length in every synchronization. Removing the last longest vehicle may
recompute the maximum at that removal event.

Normal motion updates coordinates without sorting the whole lane. After all
captured coordinates have been updated, validate adjacent ordering edges touched
by those updates. Repair inversions with adjacent swaps and update the two affected
indexes. Queue neighboring edges after a swap so the repair converges to the
existing `(position, order)` ordering. If repairs exceed twice the lane's entry
count, sort that affected lane as an exceptional fallback. Teleports, rewinds,
and large route replacements may directly use that fallback.

Remove departed members and repair surviving order before binary-search insertion
of new members. A membership insertion/removal may reindex the shifted part of its
lane once; it must not reindex every occupied lane each tick. Preserve existing
tie ordering, including explicit test/lab reordering through the roster owner.

Keep the current body/rear-clearance and committed merge-shadow behavior. A
vehicle may occupy multiple nearby sections. Its shadow must disappear on claim
release and transfer to ordinary membership exactly once at the target boundary.
The published dimensions used by gap queries must stay fixed during observation.

Retain the current nearest-bumper query logic. With different vehicle lengths,
the next center in a sorted list is not always the nearest rear bumper. Do not
cache a single leader or gap based only on lane membership/order; positions and
lengths can affect the answer even when that order is unchanged.

## Publication through a tick

1. Admission uses the previous completed index and inserts each accepted vehicle
   directly before checking the next candidate. It does not synchronize all cars.
2. Freeze topology, roster, and published kinematics during observation/intents.
   Read cached static facts and the current published occupancy entries.
3. Resolve requests with independently mutable coordinator sources. Accepted
   claims update their intersection/car revisions immediately. Position-dependent
   observations remain those of the fixed decision snapshot.
4. Apply accepted motion without occupancy queries. Collect moved vehicles,
   speed/plan changes, claim changes, and completions using the existing per-car
   passes. Do not add a new discovery pass over the roster.
5. Publish the collected occupancy changes after the full movement batch. Reject
   queries while publishing; mark the index unusable if publication fails, so a
   full recovery must occur before another query. Then expose the completed
   epoch and update roster-owned state for removals.
6. The next tick starts with an already-current index. Remove the unconditional
   start-of-tick synchronization only after all admission/removal/placement
   callers use the incremental APIs.

The legacy mode keeps its sequential decision semantics. Publish just the
changed vehicle and its claim/shadow changes after each legacy car moves. This
replaces its per-car whole-index synchronization without silently switching the
default update algorithm. Changing the default mode is outside this design.

Keep final brain decisions, following-gap arithmetic, time-dependent waiting
state, merge predictions, and follower travel relaxation outside cross-tick
static caches. Existing `MergeTrafficSnapshot` remains epoch-scoped until a
separate, measured change proves finer reuse is correct.

## Migration order and proof

These are migration boundaries. The foundation and first junction-lookup
consumer are implemented; the remaining route, roster, occupancy, and
coordinator work follows in later changes.

1. Add and verify `simulation_cache.py`, including mutation/read-phase guards.
2. Migrate network/source lookups and roster views first. Their inputs change
   infrequently and are already owned by clear methods.
3. Migrate route facts/cursors, using the existing route and boundary fixtures.
4. Add occupancy delta APIs and convert every admission, removal, movement, and
   placement caller in both update modes. Only then remove routine `rebuild()`
   calls. Retain a full reference rebuild for differential verification.
5. Maintain intersection-local claim/arrival indexes and cache only priority
   facts whose dependencies are explicit. Physical gap checks stay live.

The base suite was verified during the branch review: 317 tests run, 17 skipped,
no failures. New verification must establish:

- Unchanged sources reuse the same cached object; changed sources rebuild only
  on the next read; unrelated caches do not rebuild; cached `None` works.
- Nested mutation scopes coalesce; partial mutation errors invalidate; failed
  builders never return stale data; writes during a read phase/build are rejected.
- Composed caches name root sources and refresh even if an intermediate cache
  was not read first. Recreated owners with the same ID do not reuse old slots.
- Unchanged topology/source choices cause zero repeated map-lookup builds.
  Steady motion does not rescan completed route prefixes or rebuild signal lists.
- Ordinary motion within sections causes coordinate updates but no membership
  changes or full lane sorts. Boundary changes touch only affected vehicles and
  lanes. A stationary observer still sees another car's changing numerical gap.
- Route replacement, rewind, dimension change, exact section endpoints, multiple
  simultaneous claims, partial release, merge-shadow handoff, mixed vehicle
  lengths, repeated future visits to a lane, map replacement, and despawn/reuse
  preserve the current results. Speed-only changes refresh merge observations.
- Permuting the input car list retains existing data-first determinism.

Compare each migrated subsystem with the full-rebuild/reference path on identical
snapshots. Before accepting the whole migration, run matched five-minute Arcata
100/200-car stages and a sustained dense slip-lane/gauntlet scenario. Compare
per-tick positions, speeds, claims, completions, and relevant brain state against
`e3e377d`, and check overlaps and throughput. Alternating measurements on the same
moving snapshots isolate the cache/index costs from host timing noise.

Record cache builds/hits, route reads, membership changes, lane repairs/fallback
sorts, full rebuild calls, and median/P95 tick times. Counters are owner-local and
reported on demand; collecting them must not introduce a per-frame global scan.
Normal benchmark execution must show zero routine full occupancy rebuilds after
initialization. Safety and exact behavior parity are acceptance gates before
timing gains are considered.
