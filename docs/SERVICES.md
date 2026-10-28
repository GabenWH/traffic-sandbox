# Arcata food, care and transit integration

Run `python tools/run_arcata_services.py --out arcata-services.json --duration 3600`.
The cached real Arcata OSM graph has 1,181 road segments and 971 junctions.
154 segments carry numeric posted-speed tags; other segments use a shared
25 mph fallback. Limits apply in C++ to cars, trucks and buses. Higher posted
limits are ceilings, not a requirement to exceed the global cruise setting.
The network remains based on the June 1, 2026 extract; inferred walkways are
not a survey of sidewalks, and campus footways have not been imported.

There are 1,000 fictional residents and 600 workers distributed among eight
fictional businesses: two farms, two bakeries, two cafes, a central food market
and a clinic. Premises use preflighted access positions on real roads, sometimes
co-located with a residential access. They are not actual business or farm
locations or capacities. Co-located commutes need no road trip. Other residents
commute by walking, persistent car or transit. Job assignment determines where
a resident works; only arrived workers contribute to that site's operation.

Farms convert finite standing crop into grain; recipes are one-to-one abstract
resource units. Bakeries/cafes convert delivered grain into food. A market
requests food and supplies household requesters. Four persistent trucks reserve
stock at its source, travel empty if necessary, load through single-site FIFO
bays, deliver/unload and return. Reserved stock remains at its source until
loading completes and is included separately in the conservation ledger.
Handling rates depend on the resource. Requests without a supplier stay unmet;
medicine is finite initial stock, not conjured by a fake supplier.

Twenty residents request clinic visits and twenty workers request cafe meals.
Visitors travel through the same native walking and bus engine. The clinic
requires arrived staff, permits at most four simultaneous care slots, uses one
medicine unit to start a visit, and completes after 120 simulated seconds of
staffed service. These are fictional service units, with no diagnoses, actual
treatment protocols or health outcome claims. Cafes require food and on-site
workers to serve a meal. A served meal gives the household a provisioning
credit against future home demand, avoiding a second food charge for it.
Visitors return to their previous site and resume work where applicable.

Three looping bus lines share a central market transfer stop. There are 14
served stops and two 60-seat buses per line. Buses use fixed route geometry on
vehicle lanes. Stop queues are FIFO and specific to each line. Alighting at a
transfer removes the person from the first bus before joining the next queue.
Capacity adds actual waiting even when the planner's estimated wait is shorter.
The captured run reached exactly 60 passengers on some buses and never exceeded
it. Queued people are not active per-tick walking actors; boarding/alighting
moves their identity among the queue, seats and native walking engine.

The planner's graph includes walking access/egress time at 4.4 feet/second,
nominal ride time, expected half-headway boarding wait, and transfers. Dijkstra
(zero-heuristic A*) searches the time-weighted graph. Direct walking competes
with every transit option. No maximum walking cutoff, live queue-delay forecast
or live congestion ETA is provided. Actual vehicles obey posted limits, but
nominal ride-time estimates do not integrate those limits or congestion yet.

Observed one-hour capture, including setup: about 203 seconds on this machine.
All 600 workers arrived at their jobs at least once; at the end 584 were at work,
with others on service visits/return walks. There were 81 transit transfers,
28 deliveries, 16 cafe meals and 20 completed clinic visits. Production was
1,215.34 grain units and 935.27 food units. Person count remained 1,000 and
stock+cargo+reservations+consumption+medical sinks balanced within 0.000000001
units. This is an integration result, not evidence of daily or long-term food
sufficiency. Return commutes are scheduled after the capture.

Quiescent service checkpoints extend the prior town format with business
recipes, provisioning credits and service counters. Active visits/cargo/native
movement are rejected rather than discarded. Driver/loading workforce, bus
bay geometry, crop growth, prices/money, utilities, maintenance and mortality
remain outside this scenario. The private app replays minute-sampled frames;
C++ movement used 50 ms ticks and economy/dispatch used five-second updates.
