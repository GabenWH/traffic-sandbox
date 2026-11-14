# Arcata Python economy investigation — 7 November 2026

The 60-second economy timer already exists. Repeated event settlements still
ran full household-consumption scans between those timer events. The local
patch separates household consumption from attendance-driven production and
service settlements. No timer was added, and no merge or push was performed.

## Provenance and workload

GitHub `fix/parking-cache-preference-scaffold` was verified at
`c6daaffe5fb371a037e869886b76ac86272bb33e`. Local `cf92cafcd4d39ac960283d4b5e866744482efa27`
has exactly the same full tree: `a1532faebd9ac11a2102ea425968ff2fc304e893`.
Other unpushed work was left untouched. The patch applies to that published tree.

All measured runs use imported Arcata roads/buildings, 16,000 residents, 8,000
workers, 4,000 households, 1,000 cars, seed 42, a 120-minute departure window,
20 starts/second, and 50-millisecond updates. The measurement is a fresh-seeded
08:00–08:10 window: departures due before the starting clock are immediately
eligible. It is not a replay of an already warmed 07:00–08:00 commute and is not
an all-day speed result.

The first diagnostic run writes an initial unpopulated map cache. Every following
comparison loads exactly that map, then seeds a fresh simulation. Scenario
configuration and job assignments match across all six runs. Map import/cache
loading, setup, reports, and serialization are outside update timers. Runs are
sequential for timed updates, after the test suite completed, with no simultaneous
benchmark updates.
Native background routing remains asynchronous, so traffic trajectories and
event counts can vary slightly even with the same seeded demand.

The diagnostic baseline uses only `household-instrumentation.patch`, a helper
extraction of the unchanged household loop so it can be timed independently.
That extraction was removed for the uninstrumented baseline runs. Earlier pilot
runs and interrupted runs are excluded from the comparison.

## Measured call frequency and costs

| Settlement caller | Calls in diagnostic baseline |
|---|---:|
| _run_event:economy | 11 |
| _safe_depart | 9,370 |
| _arrive_person | 256 |

Zero-elapsed calls do not execute `_economy`. Multiple movements and departure
attempts at a shared timestamp still create positive settlements frequently.
The periodic event at the initial clock includes an overdue event left by setup;
the 10-minute window therefore contains 11 periodic event dispatches.

These are inclusive instrumented seconds. Rows overlap and must not be added.
The raw phase files also supply exclusive seconds, which partition total update
time. Instrumented times diagnose costs; plain runs below measure speed.

| Phase | Baseline calls | Baseline seconds | Optimized calls | Optimized seconds |
|---|---:|---:|---:|---:|
| Total update | 12,000 | 83.0891 | 12,000 | 32.4797 |
| Economy settlement | 9,637 | 41.3292 | 7,358 | 0.8477 |
| Actual economy updates | 6,739 | 41.2986 | 4,999 | 0.8327 |
| ServiceTown economy | 6,739 | 40.1892 | 4,999 | 0.8134 |
| Household consumption loop | 6,739 | 38.4360 | 10 | 0.0548 |
| Logistics | 11 | 0.2376 | 11 | 0.0867 |
| Shopper selection | 11 | 0.1028 | 11 | 0.0269 |
| Live incoming queries | 88,000 | 0.0589 | 0 | 0.0000 |
| Incoming aggregate builds | 0 | 0.0000 | 22 | 0.0001 |

## Measured whole-update comparison

| Run | Total update seconds | Mean tick ms | Maximum tick ms |
|---|---:|---:|---:|
| baseline-clean-1 | 65.643 | 5.4702 | 567.3 |
| optimized-clean-1 | 31.829 | 2.6524 | 584.5 |
| baseline-clean-2 | 81.489 | 6.7907 | 586.0 |
| optimized-clean-2 | 40.016 | 3.3347 | 850.5 |

Median of the two run means: **6.1305 → 2.9935 ms/tick**,
or **51.2% less update time (2.05× throughput)** in this window.
Two repetitions are a limited sample; no confidence interval or threefold
whole-simulation improvement is claimed. Maximum ticks remain much larger than
50 ms; the patch does not establish a remedy for those stalls.

All runs completed exactly 600 simulated seconds and 12,000 updates. Expected
household food consumption was 333.333333 scenario units, unmet food was zero,
and consumption/resource-balance deviations were below 0.0001 units.

## What changed and what remains

Production, café service, care, and construction retain event-triggered settlement
ordering. Household food and relocating-household cargo consume at the existing
minute event. Household balances also flush before food imports, shopping
decisions/receipts, direct logistics passes, meals, household invitation,
relocation changes, building synchronization, and saves. Flushes at the same
timestamp are no-ops.
Food values between those boundaries have minute-level granularity.
The existing `counters['economy']` still counts nonzero service/production
settlements; it is not a count of household-consumption scans.

The new household clock is persisted and validated. Legacy saves default it to
the original economy clock, preserving any unsettled interval. Save serialization
flushes gameplay before serializing building inventories.

Incoming totals are ephemeral. Shopper prechecks use one grouped snapshot.
Actual shopping reservations still use live `incoming()` checks, and a successful
reservation refreshes that home's snapshot entry. The logistics shortage loop
builds a fresh snapshot after shoppers and after job-stage/unloading changes.
There is no persistent inventory cache or cache state to serialize/invalidate.
Returning jobs are excluded; shopping reservations are included exactly as before,
including cancelled visits until their reserved amount is released. Grouped sums
preserve the original independent job/visit summation order.

## Inventory scaling probe — measured separately

Synthetic workload: 8,000 queries over 4,000 site/resource keys, seven repetitions,
including aggregate construction in every grouped trial. These are query costs,
not whole-Arcata speedups. Every queried value matched live `incoming()` exactly.

| Jobs | Visits | Queries | Live median ms | Grouped median ms |
|---:|---:|---:|---:|---:|
| 0 | 0 | 8000 | 4.094 | 0.199 |
| 10 | 100 | 8000 | 30.685 | 0.394 |
| 100 | 1000 | 8000 | 283.433 | 1.061 |
| 200 | 2000 | 8000 | 560.408 | 1.795 |

The morning Arcata workload has no outstanding jobs or visits, so its repeated
incoming calls scan zero rows. Their cost is small compared with household scans.
The synthetic result demonstrates scaling once those collections become large;
it does not prove they dominate a production/evening Arcata workload.

## Expected complexity — separate from timings

Let E be positive economy settlements, M the minute events plus required household
resource/membership boundaries, S sites, H households, B businesses, T target
queries, J jobs, V visits, and A actual shopping reservation attempts.

* Household scans: O(E(S+H)) → O(M(S+H)). Production/service work remains tied to E.
* Broad incoming queries: O((H+T)(J+V)) → O(H+T+J+V) for read passes.
  Live reservation attempts and successful-home refreshes still add
  O(A(J+V)); this is not an O(1) claim for the whole logistics pass.
* Grouping temporarily uses O(J+V+K) memory, where K is distinct site/resource
  keys. Per-key amount lists preserve Python's float-summation behavior.

## Validation and reproduction

`python3 -m unittest discover -s tests -q`: **822 tests, 802 passed, 20 skipped**.
Fourteen new tests cover batching, stock boundaries, meal credit, shared-home
reservations, grouped sums, job stages, save/load and legacy/invalid clocks.
A separate code review found no remaining actionable correctness issues.

From a clean checkout at the verified published commit:

```bash
git switch -c perf/economy-incoming c6daaffe5fb371a037e869886b76ac86272bb33e
git apply --check economy.patch
git apply economy.patch
python3 -m unittest discover -s tests -q
python3 tools/profile_arcata_economy.py --hours 0.16666666666666666 --start-hour 8 --population 16000 --cars 1000 --seed 42 --report-every 300 --stack-every 0 --output economy-phases
python3 tools/profile_arcata_economy.py --plain --hours 0.16666666666666666 --start-hour 8 --population 16000 --cars 1000 --seed 42 --report-every 300 --stack-every 0 --output economy-plain
python3 tools/benchmark_incoming.py --repeat 7 --output incoming-micro.json
```

Use a different new output directory for every run. Add `--write-world-cache
arcata-initial-world.json` to the first run and `--world-cache
arcata-initial-world.json` to subsequent runs to share the initial map.
For a baseline comparison, copy the profiling script to an unmodified checkout
at the same published commit. Apply only `household-instrumentation.patch` when
independent baseline household timing is wanted; leave it off for plain timings.
The native engine builds automatically with the existing C++ compiler. No new
Python dependency is required. Add `--cprofile` only for a separate diagnostic run;
do not use cProfile timings as speed measurements.

Sources:
* https://github.com/GabenWH/traffic-sandbox/commit/c6daaffe5fb371a037e869886b76ac86272bb33e
* https://github.com/GabenWH/traffic-sandbox/blob/c6daaffe5fb371a037e869886b76ac86272bb33e/city_simulation.py
* https://github.com/GabenWH/traffic-sandbox/blob/c6daaffe5fb371a037e869886b76ac86272bb33e/town_services.py
