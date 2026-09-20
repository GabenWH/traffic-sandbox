# Merge lab

The merge lab is a deterministic place to make the car brains uncomfortable.
It runs headlessly, so the same seed, scenario, time step, and initial intent
produce a directly comparable frame trace after a behavior change.

Run it from the repository root:

```bash
python3 tools/run_merge_lab.py --list
python3 tools/run_merge_lab.py roundabout-continuous-pressure --seed 42 --seconds 80
python3 tools/run_merge_lab.py slip-lane-short-link --seed 7 --seconds 80 --trace /tmp/slip-trace.json
```

The current matrix deliberately varies the traffic *facts*, not just the map:

| Scenario | What it tests |
| --- | --- |
| `roundabout-clear-entry` | Empty entry should not create a needless stop. |
| `roundabout-circulating-leader` | An entrant paces itself around real traffic already on the ring. |
| `roundabout-simultaneous-entry` | Competing requests must resolve priority without list-order accidents. |
| `roundabout-queued-ring` | A slow queue checks both the front and rear of the offered gap. |
| `roundabout-continuous-pressure` | Four approaches, mixed brain styles, sustained load. |
| `slip-lane-short-link` | A close upstream junction must not hide the next yield. |

Each frame records the car's state, wait reason, movement, priority/claim facts,
observed merge vehicles, and before/after speed and distance.  It also records
four wall-clock timing buckets:

- `spawn`: route/source spawning work.
- `observe`: occupancy and approach observations before any car moves.
- `decision`: time spent inside `CarBrain.decide` (intent selection).
- `resolution`: claims, acceleration limits, final movement, and occupancy refresh.

`total` includes all of the above and small bookkeeping gaps. `overlap_pair_ticks`
is the collision alarm: it uses oriented car rectangles, so cars in adjacent
lanes are not reported merely for being close together.

The app's **Simulator debug** window now shows the newest trace frame and its
decision/total time. The lab keeps up to 10,000 frames for export; the app keeps
the latest 600 frames so normal editing does not accumulate an unlimited log.

This does not yet fabricate a separate freeway-ramp geometry. That is intentional:
the current simulator's real merge primitive is the generic `merge_target`,
currently instantiated by roundabout entries. When a freeway-ramp builder is
added, it should register its map in this same matrix and automatically gain the
same clear, leader, simultaneous, queue, and load tests.
