# Shared City Road Vehicles

## Goal

Every vehicle on the city mobility network uses one road traffic simulation. Construction trucks carry material or workers, but use the same lane following, intersection priority, stop, yield, and merge rules as routed cars.

## Ownership

The routed traffic simulation owns vehicle position, speed, occupancy, and intersection claims. It accepts both user-enabled test cars and externally scheduled construction vehicles on routes between supported mobility endpoints. A vehicle's size participates in clearance calculations. Construction keeps ownership of demand, payloads, the regional departure queue, and building work; it does not advance a truck along a route itself.

All app vehicles expose the `Vehicle` read interface: identity, position, heading, dimensions, speed, color, and `VehicleAppearance`. The appearance carries semantic kind separately from the body shape and cargo display data. City road users are `RoutedRoadVehicle` actors in `RoadVehicleSimulation.vehicles`; construction trips reference those actors while active. The older freeway demo car implements the same read interface but retains its separate road network and movement simulation. Canvas, 3D, and Inspector read vehicle state through this interface. Generated test traffic is identified by its source type, so clearing it does not remove externally admitted road users that happen to look like cars.

The app holds one routed traffic simulation for the city map and passes it to construction. A construction departure enters that simulation only when the west access lane has room. A blocked departure stays at the head of the queue. The first available trip departs immediately; successful departures are spaced by 20 simulated seconds across the shared regional port. Test traffic source selection controls generated test cars only.

When a construction vehicle reaches its building lane destination, the traffic simulation reports it as completed. Construction then applies its material or crew payload exactly once, removes the active trip, and starts or advances work when building requirements permit. There is no return route or finite truck fleet in this construction slice.

## Presentation and lifecycle

Routed cars and trucks share road behavior but retain their current distinct visuals. Queued trucks are not rendered. Material and crew truck catalog lengths and widths shrink by approximately ten percent; the same dimensions are used for traffic clearance and drawing. Clearing traffic or replacing the city clears active and pending construction trips so a later update can reschedule outstanding demand from persisted building state. Runtime routes and trips remain unsaved.

## Required behavior

- A truck follows and is followed by other city vehicles, including another truck, without overlap.
- Trucks participate in the same stop, yield, merge, and intersection coordinator as cars.
- A truck cannot enter an occupied west access point; its cargo remains reserved while it waits.
- Each successful departure resets the 20 second regional departure timer.
- Material and crew delivery occurs only after the shared road vehicle reaches its destination.
- Only one city road traffic simulation advances vehicles on each app tick.
