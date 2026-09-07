# Roundabouts and junction traffic

## Try it

Run `python3 freeway_simulator.py`. Build two roads that cross, select the
intersection with **Inspect**, and set **Junction type** to `roundabout`.
Use `standard` to change it back. A standard junction with **All-way stop** set
to `no` uses the new uncontrolled-intersection rules.

Choose **Test traffic**, then click at least two outer cul-de-sacs or junctions
as sources/sinks. Select all four outer ends to exercise competing arrivals.
Use **Inspect** on a car to see its state, desired speed, signal and wait reason.
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
3. **`merge_behavior.py` decides whether the joining lane has a gap.** It examines
   approaching cars' planned routes to the named target lane. This includes cars
   on previous connected sections. It is a finite, distance-limited search, so a
   circle does not need special wraparound arithmetic. A freeway entrance can use
   the same function by supplying its target lane in `LaneConnection.merge_target`.
4. **`intersection_controls.py` shares right-of-way information.** Active claims
   block conflicting movements. Compatible uncontrolled movements may run together.
   Estimated arrival order handles separated arrivals; arrivals within 0.75 seconds
   yield to the right, and left turns yield to opposing non-left turns. If everyone
   is waiting for someone else, one stable winner breaks the cycle. Existing
   all-way stops retain their conservative one-car-at-a-time policy.
5. **`car_brain.py` makes the individual decision.** A yield permits rolling entry
   when priority and space are available. A stop still requires the full stop dwell.
6. **`traffic_testbed.py` applies motion.** It checks exit space, grants claims close
   to entry, and releases them only after the rear clears. Roundabouts slow cars to
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
