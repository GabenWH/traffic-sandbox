# Roundabouts and junction traffic

## Try it

Run `python3 freeway_simulator.py`. Build two roads that cross, select the
intersection with **Inspect**, and set **Junction type** to `roundabout`.
Use `standard` to change it back. A standard junction with **All-way stop** set
to `no` uses the new uncontrolled-intersection rules.

Choose **Test traffic**, then click at least two outer cul-de-sacs or junctions
as sources/sinks. Select all four outer ends to exercise competing arrivals.
Use **Inspect** on a car to see its state, desired speed, signal and wait reason.
The **Merge style** field accepts `rolling` or `cautious` for that individual car.
New traffic uses four rolling drivers followed by one cautious driver. The
**Phantom target** field shows which circulating car a rolling driver is following.
Save and load to check the junction type is retained.

Converting a junction clears temporary cars (their routes describe the old
geometry), but keeps your source/sink selections. Let new cars spawn afterward.
Roundabouts have one circulating lane and right-hand traffic. Multi-lane spiral
roundabouts, zipper merging, driver personalities and traffic lights are outside
this version. The older fixed-freeway simulation is not migrated here.

## The code in plain English

1. **`roundabouts.py` builds roads.** It splits a counterclockwise circle at each
   entrance and exit. Cars going to different destinations reuse the same lane
   sections. Entrances are yield-controlled connectors; exits are ordinary splits.
2. **`traffic_occupancy.py` finds the car ahead.** Each lane section has its own
   distance ruler. The lookup translates positions onto the driver's route ruler,
   continuing across section boundaries. A short clearance shadow keeps a car
   visible just after a split, while the branches are still close together.
3. **`merge_behavior.py` reports traffic and provides two strategies.** The
   observer puts cars on one distance ruler: zero at the joining point, negative
   upstream and positive downstream. It searches connected sections with a speed-
   scaled look distance. `RollingMerge` adapts the original freeway demo's phantom
   spacing and relative-speed response, and adjusts approach speed to arrive
   behind the chosen leader. `CautiousMerge` waits for a larger gap. Both predict
   clearance throughout the joining interval, including possible acceleration by
   traffic behind. The old `merge_has_gap` function remains only for compatibility;
   the routed simulation does not use it as a universal permission check.
4. **`intersection_controls.py` shares right-of-way information.** Active claims
   block conflicting movements. Compatible uncontrolled movements may run together.
   Estimated arrival order handles separated arrivals; arrivals within 0.75 seconds
   yield to the right, and left turns yield to opposing non-left turns. If everyone
   is waiting for someone else, one stable winner breaks the cycle. Existing
   all-way stops retain their conservative one-car-at-a-time policy. Merge entries
   do not join that arrival queue: claims only stop two cars occupying a conflicting
   entrance together. Each driver's brain decides whether through traffic leaves
   enough space. Circulating cars retain priority.
5. **`car_brain.py` makes the individual decision.** It first applies its driver's
   following preference, then asks the selected merge strategy using that speed.
   This prevents reserving a gap at cruise speed while actually queued. A yield
   allows rolling entry; a stop still requires the full stop dwell.
6. **`traffic_testbed.py` applies motion.** It checks exit space, grants claims close
   to entry, rechecks merge reservations until the nose enters, and releases them
   after the rear clears. A four-foot physical following guard is separate from
   the driver's comfortable following distance. Roundabouts slow cars to
   12 mph, and cars signal right on the final ring section before their exit.

The observation and merge code is generic; the geometry builder knows that the
road is a roundabout. This separation is the starting point for reimplementing
other merges without copying roundabout-specific driving behavior.

The prototype refreshes occupancy after each moving car so later decisions in
that tick see the new position. This favors clear behavior at the existing
60-car limit. Larger simulations would benefit from incremental index updates.

## Verification

`python3 -m unittest discover -s tests -v`

The new tests cover cross-section following, crossing traffic, compatible
movements, simultaneous-arrival deadlock, blocked exits, upstream merge gaps,
shared roundabout routes, signals, speed, conversion and persistence. A sustained
four-source test checks oriented car rectangles for overlap and verifies that
cars keep reaching their destinations. No extra packages are required.

## September 9 behavior comparison

In the same four-arm scenario, with seed 42, all four sources spawning every
2.5 seconds over 80 simulated seconds, the first version completed 22 trips and
accumulated 187.05 vehicle-seconds stopped near entrances. The revised mixed-driver
version completed 31 trips and accumulated 99.9 stopped vehicle-seconds. This is
one reproducible prototype comparison, not calibration against real traffic.

Tests also place a rolling entrant behind an actual circulating leader and check
that it adjusts speed, enters without stopping, and does not overlap the leader.
The cautious and rolling brains are separately given identical observations to
verify that their choices differ. Standstill queues block both strategies, and a
reservation cannot survive a delay before the car enters the connector.

## Closely spaced junctions

A car has two different jobs: its nose obeys the next entrance, while its rear
keeps the previous junction occupied. A seven-foot link cannot hold a fourteen-
foot car. Waiting for the rear to clear before looking at the next yield caused
an actual overlap on `tests/fixtures/slip_lanes.json` at 15.05 seconds.

Claims are now stored per car AND movement, so one car can occupy two junctions.
Each claim is released independently when the rear clears. Once the nose enters
with permission, the brain can consider the next stop or yield. It still matches
circulating traffic's speed while completing a merge; looking ahead must not
cancel phantom following midway through entry.

Before an ordinary intersection, the simulator also looks through short links
for a downstream merge. If the predicted gap is blocked, it waits upstream
instead of treating that short link as storage. This prediction does not reserve
the circle: the actual yield is checked again on approach. Conditions can change,
so a car that must wait after entry still retains its upstream occupancy claim.
A later stop sign still requires its own stop; occupancy does not waive it.

Run the uploaded-map regression with:

```sh
python3 -m unittest discover -s tests -p test_chained_junctions.py -v
```

The regression checks oriented vehicle rectangles every 0.05 seconds and also
requires completed trips, so making every car stand still cannot pass it.

## September 11 merge safety corrections

The cause-isolation audit found that entry permission was based on a speed plan
which the driver did not keep. Entry now carries an explicit speed plan, used
from the approval update until the rear has joined. Phantom following chooses
approach speed; it no longer freely changes the approved plan halfway through
entry. Normal following can still brake for a real vehicle ahead. Near-zero
queue speeds do not qualify as a committed joining plan: the minimum is six
feet per second, or the road's lower cruise speed.

Waiting drivers at other entrances no longer count as circulating traffic.
However, a driver already completing a merge creates a downstream reservation:
a later entrant cannot race around the circle into that joining point before
it clears. The check allows for acceleration after the later car finishes its
own merge. Predictions also allow circulating cars to accelerate from a queue
back to road speed, rather than assuming their current low speed persists.

Zero phantom influence now allows free acceleration. This fixes the isolated
restart failure that could strand a car over 160 feet before its yield line.
The painted yield line and control target now share a position farther into the
entrance curve. On the uploaded plain roundabout it is about ten feet closer
to the circle. A radial buffer and a test of stopped-car clearance against
circulating vehicle rectangles protect the reference 14-by-6-foot test cars.

`tests/test_merge_safety.py` includes the audit's failed approval observation,
restart and classification regressions, downstream-reservation checks, yield
clearance, and the uploaded roundabout's 80-second collision/progress test.
The earlier slip-lane map regression remains enabled. These are tested scenarios,
not proof that arbitrary layouts and traffic conditions can never collide.
