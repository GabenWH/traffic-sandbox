# Passenger bus prototype

`transit.py` adds persistent bus records and passenger state to the road-owned
walking and vehicle networks. `TransitSimulation` owns the shared clock and
uses `RoadVehicleSimulation`'s C++ engine for both bus and walking movement.
Only service events and route selection run in Python. Waiting passengers are
FIFO queues, not ticked moving agents. Riding passengers occupy seats rather
than walking actors. Bus records, IDs, capacity and fuel survive every stop;
each road leg has a native road vehicle with the bus's same ID. At stops that
road actor is removed and the bus is held in an assumed off-road bay.

## Setup

1. Construct the city, including road-owned sidewalks and standalone paths.
2. Create `TransitSimulation(city)` or supply existing shared traffic.
3. Add `BusStop` objects with a precise vehicle `LanePosition` and a pedestrian
   access point. Stop geometry is authored, not inferred curbside legality.
4. Add a `BusLine` with at least two distinct stop IDs. The stop sequence loops;
   every consecutive leg, including the return leg, must have a vehicle route.
5. Add `Bus` records. `service_at` delays initial boarding. Capacity, dimensions,
   speed and fuel consumption are scenario settings, not real fleet data.
6. Call `request_trip(person_id, origin, destination)` and `update(seconds)`.
   Advance the shared traffic only through this coordinator.

The journey planner searches a graph of stop, onboard-line, boarding, riding
and alighting states. Shared stops connect lines and allow passenger transfers.
It compares complete journeys with direct walking. Costs use 4.4 feet/second walking, posted
line speed, dwell, and nominal headway/2 expected wait. This uses shortest expected-time search with a zero heuristic. It is not a
timetable-aware or congestion-aware forecast. There is no hard maximum walking
distance; walking access time can make a bus journey lose to walking directly.
Buses cannot traverse pedestrian-only paths because legs route exclusively on
vehicle lanes. Headway enforces the minimum interval between line departures
from the first stop; congested or long loops can result in longer actual waits.

Walking completion enqueues a person at a stop. Boarding consumes a seat and
extends dwell by boarding time. Full buses leave remaining passengers queued.
Alighting frees seats and starts the final walk in C++. A passenger arrives
only when that walk completes. A zero-distance walk is an immediate transition.
Fuel is charged by actual native distance traveled, in liters per mile. A bus
without enough fuel to finish its next leg stays at the stop, `out_of_fuel`.
Fuel supply/refueling and recovery from that state are not modeled yet.

## Reproduce the demonstration

```sh
python tools/run_transit_demo.py --out benchmarks/transit-demo.json
python -m unittest tests.test_transit -q
```

The synthetic 6,000-foot corridor has four passengers, one two-seat bus and two
stops. The first pair arrives around 201–204 seconds; the second pair arrives
around 559–561 seconds. Recording at one-second intervals is display sampling;
native movement uses 0.05-second steps. `TransitSimulation.events` exposes waits,
boarding, departures, docking, alighting, arrival and fuel failure.

Road edits or replacement of the native engine fail explicitly rather than
silently stranding or teleporting existing passengers. An externally advanced
shared clock is rejected. Rebuilding transit after edits requires caller-owned
migration of active people and buses.

Not included: accessible boarding, driver/workforce needs,
fleet/world save/load, idling fuel, bus stop bay geometry/capacity or pull-in
maneuvers, timetable-aware routing, and live browser simulation. Pedestrian
crossings retain the existing inferred/first-crossing-only limitations. The
private Site provides playback of the recorded native run, not a C++ runtime.

Default buses now seat 60. Their road driving is shared with cars and trucks.
The service's nominal speed is used only for planning; it is no longer passed
as an arbitrary bus driving cap. Numeric OSM maxspeed tags set native limits
by canonical lane/road-port occupancy key. A native lookahead brakes before
a lower-limit section; admission starts within the current road limit. All
vehicle types use this same code. Missing limits retain the simulation-wide
cruise fallback (25 mph in the captured scenarios).
