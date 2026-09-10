# Roundabout cause-isolation audit

Scope: local commit `e8c8c0c`, published equivalent `37b99db`, on Grace's
`roundabouttest.json` (preserved as `tests/fixtures/roundabout_test.json`).
Runtime implementation was not modified by this audit.

## Conclusion

This is a combination of local bugs and a systemic coordination problem. The
reproduced entry collision is best explained by approval of one trajectory and
execution of a different trajectory. It is not explained by the circulating car
being invisible or solely by a coarse timestep. Excessive caution sometimes
masks the unsafe entry behavior; removing caution is not sufficient.

## Confirmed causes

1. **Local restart bug — `RollingMerge.decide`.** Outside the 128-foot phantom
   influence region, influence is zero but the leader branch requests current
   speed instead of free acceleration. For a stopped driver with a projected
   leader, desired speed remains zero. A map-free probe reproduces this; removing
   the leader or selecting the cautious strategy instead requests 17.6ft/s.
   In the baseline map, one driver remained stopped for 18.3 seconds with its
   nose 166.13 feet before the yield line and no indexed leader within 128 feet.

2. **Observation classification bug — `observe_merge`.** Other waiting
   entrances can be included as circulating-priority traffic because their
   future routes contain the target lane. At 76.70 seconds, removing just those
   observations from the same decision changes rejected entry to accepted entry.
   This demonstrates an unnecessary veto, not permanent deadlock.

3. **Prediction/execution contract failure — merge decision and traffic update.**
   At 11.70 seconds, car8 gets permission based on desired speed 0.474ft/s.
   The predicted conflict begins 49.49 seconds later and ends 93.78 seconds
   later. Car8 actually accelerates to 2.22ft/s at 12s, 7.14ft/s at 13s, and
   11.34ft/s at the 15.50s collision. Car1 is present in the relevant observations.
   Rechecking the identical approval-time observation at 17.6ft/s rejects the
   gap and predicts conflict 2.21–3.41 seconds later. Subsequent sampled active
   merge decisions reject entry, but the committed movement applies their speed
   recommendation without enforcing the renewed gap result. The collision occurs
   13.48 feet before the join, within the model's existing 14-foot conflict onset.
   Fixing only the initial observation or speed constant cannot establish safety.

4. **Stopping-line placement.** Rendering and control both use the beginning of
   the 30.45-foot entry connector as the yield line. A stopped car's center is
   therefore 37.45 feet before the join. This contributes to apparent early
   stopping but does not explain the 166-foot freeze. The appropriate closer
   control point requires a vehicle-clearance check, not an arbitrary offset.

## Confounder checks

All runs use seed42, all four endpoint sources, default1.5-second spawning,
14×6-foot cars, and oriented-rectangle collision checks. Distances are feet.

| Change from baseline | Duration | First overlap | What it establishes |
|---|---:|---:|---|
| None, dt0.05s | 80s | 15.50s | Reproduces reported failure |
| Halve dt to0.025s | 20s | 15.525s | Smaller steps alone do not remove failure |
| Reverse car-processing order | 20s | None in window | Trajectories are order-sensitive; no general safety conclusion |
| Permit free acceleration outside phantom zone | 80s | 15.50s | Reproduced long-range freeze disappears, first collision remains |
| Exclude waiting entrants from merge observations | 20s | 13.05s | Correcting classification alone does not prevent collisions |

Baseline recorded 50 overlapping pair-ticks, not 50 distinct crashes. Raw overlap
counts cannot be compared across different timesteps or observation durations.
Reversing order eventually changes spawn success as trajectories diverge, so it
is a sensitivity check rather than matched-state proof that ordering causes the
original collision. In the free-acceleration experiment, the longest observed
stop without an indexed leader was 7.2 seconds at the yield line.

An additional isolated dependency check shows that adding an unrelated fast car
changes which upstream traffic is observed: the observation window uses the
maximum speed of *all* cars. This is a real global dependency and a potential
confounder; it has not been established as the cause of the first collision.

## Reproduction

```sh
python3 tools/analyze_roundabouts.py --isolated
python3 tools/analyze_roundabouts.py
python3 tools/analyze_roundabouts.py --dt .025 --seconds 20
python3 tools/analyze_roundabouts.py --experiment reverse_order --seconds 20
python3 tools/analyze_roundabouts.py --experiment free_acceleration
python3 tools/analyze_roundabouts.py --experiment exclude_waiting --seconds 20
```

The experimental switches change one dependency in the analysis process and
restore it afterwards. They are probes, not vetted driving fixes. The script
prints JSON; recorded results and approval/sample observations are in
`roundabout_audit.json`. Existing slip-lane collision coverage remains relevant
for any eventual correction.

## Recommended correction order

First define how entry permission constrains subsequent motion: either validate
the range of motion the driver can execute or maintain a safety constraint while
approaching the actual conflict boundary. Simply stopping a committed car after
it is already in the conflict can also be unsafe. Then correct the restart and
observation-classification bugs, followed by geometry-based control placement.
Verify both uploaded maps with collision, progress, and premature-stop checks.

Deferred editor requirement: generated slip-lane junctions include unwanted
movements. A future detailed intersection editor should permit individual
lane connections to be enabled/disabled and assigned controls. This audit does
not change those connections or implement the previously discussed road-priority
numbers.
