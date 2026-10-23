# Signalized intersection control

## Goal

Make `ControlType.SIGNAL` behave as a real fixed-time signal in routed road traffic. Signals use simulation time, explicit movement sets, and scheduled plan changes. Red and clearance aspects hold traffic at the existing control line; green permits a movement to request the existing intersection occupancy claim. A claim survives phase changes until the vehicle's rear clears the junction.

## Scope

- Add reusable phase, plan, aspect, and scheduled-plan-change types in `intersection_controls.py`.
- Let `RoadVehicleSimulation` map controller IDs to fixed-time controllers; missing or unconfigured signal programs fail closed.
- Integrate both legacy and data-first update paths, keeping signal traffic out of stop/yield arrival ordering and preventing deadlock recovery from overriding red.
- Add red and green behavior to `CarBrain` without applying stop-sign dwell to red signals.
- Add unit and integration tests for timing boundaries, schedule changes, red blocking, green admission, and claim clearance in both update modes.
- No UI editor or real-world performance claim is included.

## Implementation sequence

1. Add failing tests for signal timing, scheduling, coordinator claims, and car behavior.
2. Add controller and claim primitives.
3. Integrate signal aspects and claims in both traffic update paths.
4. Run focused tests, then the full unittest suite; fix any regressions.

## Safety contract

- A signal movement is green only when its controller exists and its ID is in the active green phase.
- Yellow and all-red do not admit new movement claims.
- Green never bypasses an active conflicting movement claim.
- Once admitted, a vehicle may clear its claimed movement even if the phase changes.
