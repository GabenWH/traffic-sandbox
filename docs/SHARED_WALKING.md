# Shared walking destination trees

Walking queries share the existing native reverse-Dijkstra tree implementation
used by car route planning. Each pedestrian network revision owns its own graph,
destination-tree cache and endpoint-projection cache. Edits replace the snapshot;
an old snapshot remains valid for a reader already using it.

Endpoint projection still snaps to pedestrian lanes, never junction connectors.
The two directions of the snapped lane supply the tree roots/origin choices.
Queries also compare the direct partial lane path. Off-network access distances
are added at both ends. Selected routes reconstruct their lane slices and the
existing crossing metadata; parking eligibility reads only a distance.

The caches retain at most 8,192 endpoint projections and 256 destination trees.
The tree limit is also reduced to keep their distance/next/root arrays within
64 MiB (with at least one tree). Both caches evict least-recently-used entries.
Geometry and edge metadata use numeric arrays; trees use native numeric vectors.
Readers hold their own tree references and output buffers during eviction.

Transit compiles its walking snapshot during service initialization, so graph
compilation does not wait for the first moving pedestrian. A cache miss builds
a native destination tree synchronously; warm queries reuse it. This change
does not make every transit itinerary or geometry reconstruction asynchronous.

Parking alternatives share a per-movement-quantum query allowance, including
event fragments and wait registration. If registration has not finished checking
the alternatives, the trip remains queued for another planning attempt rather
than becoming an idle waiter with an incomplete list of eligible lots.

Commute admission carries the status of the current departure attempt alongside
its success value. A failed walking departure cannot inherit a preceding car's
`full` status. Walking service returns also use their own retry path. Real car
capacity waits retain their deadline, lot indexes and change-driven recovery.

## Verification

```sh
PYTHONPATH=.:tests python -m unittest discover -s tests -q
python -u tools/profile_commute_phases.py --hours 1.4166666667 \
  --start-hour 7 --population 16000 --cars 1000 --seed 42 \
  --report-every 300 --stack-every 60 --output /path/to/new-results
```

The regression checks compare shared-tree costs and reconstructed lengths with
the previous native A* and reference Dijkstra, including reverse curved lanes,
junctions, disconnected networks, zero-length inputs, revisions, concurrent
readers and eviction. Cost-only queries forbid path reconstruction. Parking
regressions exercise cold wait registration, stale car statuses, save/load and
capacity-release recovery.

The Arcata attribution run covers 07:00–08:25, not a full day or 500,000 active
vehicles. Its phase timings include instrumentation overhead. Compare wall time,
main-thread CPU time, all-thread GC overlap and commute/resource outcomes before
claiming an improvement. Cold setup and remaining GC pauses are separate from
the recurring parking-alternative search spikes.

## Arcata result, November 7, 2026

The same seeded 16,000-resident, 1,000-car scenario completed 102,001 updates
covering 85 simulated minutes in both runs. These are instrumented timings.

| Measurement | Before | Shared walking trees and admission fixes |
| --- | ---: | ---: |
| Average update | 1.931 ms | 1.643 ms |
| Updates over 50 ms | 23 | 2 |
| Updates over 100 ms | 19 | 2 |
| Updates with over 50 ms of walking/journey CPU | 19 | 0 |
| Longest update, including cold start | 372 ms | 490 ms |

Average update time fell 14.9%. The remaining slow updates were the initial
490 ms tick (including 128 ms of generation-2 GC and 339 ms of exclusive
`transit.update` work) and a 157 ms tick with 149 ms of generation-2 GC.
The recurring walking-search CPU spikes did not recur in this interval.

Both runs ended with 3,368 departures, 1,241 people at work, 2,127 commuting,
62 active road vehicles, identical food consumption and zero resource balance
error. Reported waiting rose from 40 to 53 as failed walking attempts retained
their retries; explicit blocked waits fell from 38 to 10 after removing stale
car statuses. Fuel used differed by 0.005 liters, consistent with small changes
in background admission timing; full deterministic transport identity is not
claimed. This comparison does not isolate the contribution of each fix.

The full regression run completed 838 tests, with 20 environment skips. A final
129-test focused recheck also covers the departure allowance for a car owner walking
back from a construction site. That positive-status label correction followed
the timed run; the benchmark has no construction-site returns.
