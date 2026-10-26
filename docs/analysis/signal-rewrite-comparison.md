# Signal rewrite: old/new comparison

> Historical full-flow results from the initial occupancy rewrite, before the CPU follow-up. Updated CPU measurements are in [signal-permission-cache-comparison.md](signal-permission-cache-comparison.md); full-flow throughput was not rerun for that follow-up.

Baseline: upstream main `fa6fe8203ddf9f1c982d4e8e87b18c1b090a6c50`, whose signal implementation is unchanged from `f0ae7aa`. Rewrite core: `b2110c753afd40eeec6f940bfb4864e48f960e2f`. Raw measurements and source fingerprints are in [signal-rewrite-comparison.json](signal-rewrite-comparison.json).

The app uses `data_first`: median completed trips increased **52%** for straight traffic and **50%** for mixed turns. Fixed-state CPU medians increased **20–27%** at 32–128 cars in this experiment; paired CPU differences were noisy and sometimes reversed. All new flow runs had zero observed red entries and overlap pair-ticks.

## Behavior

Signals no longer acquire movement claims. Green admits following traffic; red stops new entry. Actual entered bodies remain visible until their rear clears. Yellow makes a latched comfortable-stopping-distance decision. Scheduled changes wait for current clearance, and updates split at signal events. Conflicting protected green/yellow groups are configuration errors. Stop/yield arbitration remains in place; signal admission is rechecked after same-batch claims. Signal-controlled merges retain their checked speed and target-lane body projection.

## Method

- Both update engines, three paired seeds (0/1/2), isolated processes, counterbalanced old/new order.
- Flow: two crossing through-traffic phases (18 s green + 3 s yellow + 1 s clearance each), and mixed-turn traffic with four approach phases (12 + 3 + 1 s each).
- Each flow run lasts 180 simulated seconds at 0.05 s outer updates and receives 450 identical requests. The mixed-turn distribution is 55% through / 25% right / 20% left. Failed admissions remain in FIFO source backlogs; no demand is discarded.
- CPU: identical frozen traffic states at 32/64/128 cars, 20 warmup updates excluded and 50 samples per run. Restoring states, source admission, and safety checks are outside timing.
- Times below are process CPU milliseconds per update, summarized as the median of the three run medians. Frozen starting states isolate car-count differences; flow CPU has naturally different vehicle positions and queues.
- This is a saturated finite-horizon experiment, including startup and unfinished backlog, not a calibrated steady-state capacity or crash-rate estimate. Whole-movement physical clearance remains conservative for conflicting traffic.

## data_first

### Fixed-state CPU cost

| Cars | Old CPU ms/update | New CPU ms/update | Change | Paired change range |
| ---: | ---: | ---: | ---: | ---: |
| 32 | 1.986 | 2.514 | +26.6% | -8.6% to +61.5% |
| 64 | 3.787 | 4.541 | +19.9% | -11.2% to +121.0% |
| 128 | 8.129 | 9.718 | +19.6% | -9.6% to +78.8% |

Negative CPU changes mean less update cost. Median frozen-state cost increased at every tested load in this experiment. Paired differences vary widely and sometimes reverse; these measurements do not establish a CPU-speed improvement.

### Traffic results

| Scenario | Old completed / 180 s | New completed / 180 s | Completion change | Old / new veh/h | Old / new flow CPU ms/update |
| --- | ---: | ---: | ---: | ---: | ---: |
| straight | 75 | 114 | +52.0% | 1500 / 2280 | 2.496 / 2.714 |
| turns | 40 | 60 | +50.0% | 800 / 1200 | 2.759 / 2.674 |

Across the six flow runs per implementation: red entries **30 old / 0 new**; overlap pair-ticks **0 / 0**; reported hard-gridlock seconds **0.00 / 0.00**.

## legacy

### Fixed-state CPU cost

| Cars | Old CPU ms/update | New CPU ms/update | Change | Paired change range |
| ---: | ---: | ---: | ---: | ---: |
| 32 | 4.521 | 7.307 | +61.6% | -5.3% to +109.1% |
| 64 | 14.263 | 23.333 | +63.6% | +6.0% to +119.9% |
| 128 | 55.658 | 79.665 | +43.1% | -21.4% to +78.2% |

Negative CPU changes mean less update cost. Median frozen-state cost increased at every tested load in this experiment. Paired differences vary widely and sometimes reverse; these measurements do not establish a CPU-speed improvement.

### Traffic results

| Scenario | Old completed / 180 s | New completed / 180 s | Completion change | Old / new veh/h | Old / new flow CPU ms/update |
| --- | ---: | ---: | ---: | ---: | ---: |
| straight | 75 | 116 | +54.7% | 1500 / 2320 | 10.288 / 9.253 |
| turns | 40 | 60 | +50.0% | 800 / 1200 | 10.243 / 9.510 |

Across the six flow runs per implementation: red entries **30 old / 0 new**; overlap pair-ticks **0 / 0**; reported hard-gridlock seconds **0.00 / 0.00**.

## Verification and review

Full unittest suite: **346 tests run, 329 passed, 17 skipped**, no failures. Skips are existing environment-dependent UI tests. `git diff --check` passed.

Test-first regressions cover streams through green, stoppable pre-entry cars, yellow braking/continuation, physically occupied opposing movements, blank/missing controllers, scheduled changes and latest pending requests, decimal boundaries, and removal. Independent review identified same-batch signal/yield entry, decimal aspect rounding, and conflicting cross-controller yellow/green permissions; each was reproduced with a failing test and fixed. Additional failing/passing regressions cover signalized merge projection and entry-speed retention.

## Decisions and limits

- Yellow uses the existing comfortable-braking model; calibrated driver reaction variability was not added.
- Physical signal occupancy is observed from front/rear positions and does not reserve future entry. Conflicting whole movements still wait for rear clearance; same-approach followers stream normally.
- Active incompatible green/yellow permissions raise a configuration error, rather than being silently serialized by claims.
- The fixed-count study uses 32/64/128 cars, matching the 128-car flow cap. An initial 256-car stress run was discarded because legacy cost dominated runtime; its samples are not included.
- No UI phase editor, pedestrian phases, calibrated human behavior, or alternative native backend was added. The benchmark covers this Python routed simulation.

## Reproduce

Use an unchanged checkout of the baseline commit for OLD, and this branch for NEW:

```bash
PYTHONDONTWRITEBYTECODE=1 python tools/compare_signal_systems.py \
  --compare /path/to/OLD /path/to/NEW \
  --seconds 180 --counts 32,64,128 --samples 50 --seeds 0,1,2 \
  --output docs/analysis/signal-rewrite-comparison.json
```

Runtime: Python 3.12.14; Linux-6.18.55-x86_64-with-glibc2.39. Absolute timings depend on the host. The completed-vehicle gains are consistent across all three seeds; CPU changes are mixed.
