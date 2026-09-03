# All-Way Stop Car Brain Design

## Goal

Give constructed-road test cars an inspectable decision layer and make selected
standard intersections operate as all-way stops. Cars decide when and how to
move; intersections expose control facts and arbitrate conflicting movement
claims.

## Scope

- Add a brain to `RoutedTestCar` with explicit, debug-visible behavior states.
- Let the Inspector toggle a standard intersection between uncontrolled and
  all-way stop by applying the same control to every incoming lane connection.
- Make routed test cars approach, fully stop, wait for priority, claim a
  movement, traverse it, and release it after clearing.
- Preserve control configuration through the existing lane-connection
  persistence and geometry-rebuild mechanisms.
- Draw stop lines and expose car brain state and wait reason for debugging.
- Leave legacy freeway cars, traffic signals, roundabouts, lane changes, and
  driver personalities unchanged.

## Responsibility Boundaries

`CarBrain` owns behavioral choice. It observes route progress, the next
controlled movement, nearby cars, and the coordinator's public snapshot, then
returns a desired speed and state. `RoutedTestCar` owns physical progress and
applies the brain's decision. `AllWayStopCoordinator` owns only shared runtime
facts: stopped arrival order, active movement claims, movement conflicts, and
claim cleanup. It never advances a car or commands one to move.

`Intersection` continues to own persistent geometry and `ControlDefinition`.
An all-way stop is represented by setting every standard lane connection to
`ControlType.STOP`; no extra persisted controller object is required for V1.

## Behavior

A car cruises at its route speed until it enters the braking range of its next
stop-controlled lane connection. It brakes to the connection's first point,
which is the stop line, and must remain fully stopped for 0.5 simulated seconds.
It then registers its arrival and asks to claim its intended movement.

Claims are granted to the earliest eligible stopped arrival. Arrivals within a
small timestamp tolerance are ordered clockwise by incoming approach angle;
car ID is the final deterministic tie-break. A claim is denied while its path
conflicts with any active claim. V1 serializes same-intersection claims for
safety; the conflict API remains explicit so compatible simultaneous movements
can be added later without changing car brains.

Once granted, the car enters and traverses the connection. Its claim is
released when route progress passes the connection. Cars also maintain a
minimum following gap behind a car ahead on the same route geometry. V1 uses a
simple bounded acceleration/deceleration model rather than instantaneous speed
changes.

## Debugging and UI

The Inspector presents an `All-way stop` boolean-like text field on standard
intersections. Accepted values are `yes/no`, `true/false`, `stop/uncontrolled`,
and `1/0`. Applying it updates all generated lane connections and redraws the
world.

Routed test cars become selectable by the Inspector. Their inspection rows show
brain state, wait reason, current speed, desired speed, route progress, and any
claimed movement. The renderer draws a stop bar across each controlled incoming
road port. The debug window adds one compact line per routed test car.

## Testing

Headless tests cover brain attachment and state visibility, stopping before the
line, dwell time, first-arrival ordering, clockwise deterministic ties, claim
release, safe queuing, all-way control application, persistence, and unchanged
legacy tests. UI behavior is exercised with existing lightweight host/canvas
fakes.

