# Incremental cache migration verification

The migration retains route metadata/geometry, source selections, spawn timers,
and sorted roster views, and publishes changed vehicle occupancy instead of
discovering changes through a full-roster rebuild. The default update mode is
unchanged. Intersection-local claim/arrival caching remains a later migration.

## Initial sustained comparisons

All runs below alternate baseline/candidate update order and compare every tick.
Traffic distance, speed, brain state, heading, merge plans, claims, arrivals,
completion IDs, RNG state, source order, spawn timers, and deadlock state match.
Leader queries match a full reference rebuild; overlapping vehicle pairs match.
World-position differences stay below 1e-8 feet (rounding from retained rulers).

| Scenario | Baseline | Simulated seconds | Peak cars | Median tick, before → after | P95 tick, before → after |
| --- | --- | ---: | ---: | ---: | ---: |
| Arcata, data-first, extended | `6fe1084` | 600 | 200 | 28.29 → 12.42 ms | 43.02 → 19.91 ms |
| Arcata, data-first | `e3e377d` | 300 | 200 | 22.45 → 12.10 ms | 35.68 → 19.96 ms |
| Slip lanes, data-first | `e3e377d` | 300 | 38 | 2.22 → 2.31 ms | 3.82 → 4.05 ms |
| Slip lanes, legacy | `6fe1084` | 300 | 37 | 5.06 → 2.68 ms | 7.77 → 4.49 ms |
| Dense gauntlet, data-first | `6fe1084` | 300 | 200 | 13.92 → 14.21 ms | 37.72 → 37.99 ms |
| Dense gauntlet, legacy | `6fe1084` | 300 | 200 | 116.16 → 15.86 ms | 171.54 → 38.97 ms |

Timing statistics cover the second half of each run. Arcata increases its cap
from 100 to 200 at the midpoint; its mean population in that second stage was
185.4 cars. The small slip-lane network peaks below its cap.
These initial measurements precede the final guarded route-hit optimization.
They are host measurements, not a universal speedup: long Arcata routes benefit
substantially from retained geometry, while short routes pay cache/index overhead.
Concurrent validation can affect timing tails. No timing result overrides parity.

All listed runs recorded **zero full occupancy rebuilds, zero full lane sorts, and
zero overlap pair-ticks**. Small coordinate updates and adjacent-order checks
still occur as vehicles move. Admission/removal/resize/route replacement maintain
membership explicitly. Full rebuild remains available for recovery and lab reorder.

## Guarded final-build comparisons

The final guarded Arcata runs matched all 12,000 ticks over ten simulated
minutes, including a five-minute 200-car-cap stage. Data-first median tick time
fell about 60%. The legacy-mode comparison also completed: at a mean population
of 192 cars in stage two, median tick time fell 92.5% (127.74 to 9.61 ms), and
median update-only time fell from 120.84 to 7.86 ms. The legacy-mode run
completed 59 trips and recorded zero overlap pair-ticks, full occupancy
rebuilds, or full lane sorts. Maximum world-position error was below 4e-11 feet.

| Scenario | Baseline | Simulated seconds | Peak cars | Median tick, before → after | P95 tick, before → after |
| --- | --- | ---: | ---: | ---: | ---: |
| Arcata, data-first | `e3e377d` | 600 | 200 | 28.16 → 11.30 ms | 39.55 → 18.24 ms |
| Arcata, legacy update mode | `e3e377d` | 600 | 200 | 127.74 → 9.61 ms | 139.64 → 11.67 ms |
| Slip lanes, data-first | `e3e377d` | 300 | 38 | 2.25 → 2.20 ms | 3.81 → 4.00 ms |

The Arcata legacy-mode update-only median was 120.84 → 7.86 ms (P95 131.99 →
9.17 ms). Stage-two mean population was 192.0 cars. Exact state matched every
tick; the run spawned 259 cars, completed 59, and ended with 200 active. The
data-first and legacy-mode runs use the same base, seed, network, and staged
load; their traffic counts differ because update modes produce distinct valid
outcomes.

## Integration decisions

- Explicit lab roster reordering uses full synchronization to replace tie order;
  ordinary ticks remain incremental. This costs O(roster) only on manual reorder.
- Legacy post-tick occupancy is compared with a fresh full reference over the
  completed roster, since the old implementation can retain a completed car until
  the next tick. In-tick decisions and completion order must still match exactly.
- Source selections are pruned on source revision as well as topology changes.
  This fixes the warmed-cache stale-ID crash and adds one constant-time stamp
  check per source-view lookup.

Route reads retain immutable facts while still checking their source on every
read. Two tests reproduced missing dependency/mutation guards in the first fast
path before restoring `RevisionSource.stamp()`. Three more tests establish that
new vehicles support declared composed caches, route replacement invalidates an
outer cache before its next read, and a route read phase rejects replacement
before live vehicle fields or claims change. All five tests passed after fixes.
The general one-source `CachedValue` fast path retains its original guards.

## Additional correctness checks

- Complete suite: 368 tests run, 17 skipped, no failures.
- Independent review: no other confirmed production correctness defects.
- 819,000 randomized historical route/control/signal/incoming-lane comparisons.
- 72,000 historical occupancy and hypothetical exit-gap comparisons through 1,200
  lifecycle steps, including mixed lengths, resizing, claims, rewinds, route
  replacement, repeated lanes, removal, and recreating the same vehicle ID.
- Independent reviewer also exercised 4,000 delta lifecycle states and 100,000
  route/control queries.

The reviewer found a warmed-source-cache regression: selecting a stale/foreign
junction could raise `KeyError`. The new regression test reproduced it in both
modes, then passed after source pruning was keyed to source-selection revision
as well as lookup identity. The full suite passed after the fix.

The sustained generated scenarios use uniform vehicle sizes. The separate
mixed-length lifecycle comparisons provide that coverage. Completion payloads
are not serialized wholesale by the harness; traffic state is compared while
active, and completed IDs/order and resulting roster/coordinator state are checked.

## Reproduction

```sh
python -m unittest discover -s tests -q
python tools/compare_cache_migrations.py --base e3e377d --network arcata --mode data_first --seconds 300 --output /tmp/cache-arcata.json
python tools/compare_cache_migrations.py --base e3e377d --network arcata --mode legacy --seconds 600 --output /tmp/cache-arcata-legacy.json
python tools/compare_cache_migrations.py --base e3e377d --network slip_lanes --mode data_first --seconds 300 --output /tmp/cache-slip.json
python tools/compare_cache_migrations.py --base 6fe1084 --network slip_lanes --mode legacy --seconds 300 --output /tmp/cache-slip-legacy.json
python tools/compare_cache_migrations.py --base 6fe1084 --network gauntlet --mode data_first --seconds 300 --output /tmp/cache-gauntlet.json
```

The harness retains `6fe1084` as its default baseline (the cache-foundation
commit); always supply `--base e3e377d` when comparing the complete cache work
with the original persistent-occupancy branch. The cache-foundation baseline
isolates the subsystem migrations from the earlier junction-lookup change.

## Legacy timing scope

The Arcata legacy-mode comparison is saved as
`benchmarks/cache-migrations/arcata-legacy-final.json`. It uses the original
pre-cache revision `e3e377d` and measures the final guarded build with legacy
update ordering. This complements the data-first measurements above; the two
update modes are reported separately because their traffic counts differ.
