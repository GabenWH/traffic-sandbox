# One-day synthetic town integration

`town_simulation.py` joins the existing C++ traffic and pedestrian engine,
`TransitSimulation`, real `Building.inventory` buffers, and a new logical
`PersistentFleet`. It is a controlled integration test, not a calibrated
Arcata town or a survival forecast. Scenario geometry is one synthetic
6,000-foot street with 40 residential buildings and one kitchen/grain store.
All roles, quantities, rates and operating hours are fictional.

The default run has 1,000 residents (600 workers), 40 household cars, two trucks
and two buses. Native actors move at physical speeds on a 0.05-second clock;
there is no compressed travel time. Economy and dispatch run every five seconds.
No production is credited until workers have physically arrived. Grain converts
to food at an invented one-to-one rate, limited by on-site grain and workers.
Household food demand is three units/person/day, charged to home inventories
regardless of the person's current location. This is household provisioning,
not a modeled sequence of individual meals or shopping journeys.

## Persistent vehicles

`persistent_fleet.py` owns `FleetVehicle` records independently of transient
native road actors. A car completing a trip parks the same record at the
actual destination. Its ID, location, fuel, cargo, dimensions, driver ID and
trip count persist. Later dispatch uses that record; it cannot depart again
while already driving, exceed cargo capacity, leave without fuel for its leg,
or start from a different site. Road access checks both travel directions and
uses the shortest valid route, without adding a permanent node per building. Cars have resident drivers. Source-generated
diagnostic traffic retains its existing source/sink behavior; it is not a
household fleet and is not silently converted into owned cars.

Parking sites have finite capacities. On road completion a vehicle waits in
an assumed off-road staging area until a space is available. Native parking
maneuvers, access turns and spillback onto the street are not modeled.

Trucks reserve finite kitchen food, queue for a single handling bay at each
site, load, drive to a household, queue/unload, and return empty. Cargo remains
on the vehicle/staging ledger until unloading finishes. Loading uses a
material/vehicle rate of 10 units/sec and a five-second setup. Fuel is charged
on actual distance traveled. Depot refueling is not modeled. Bus/truck drivers
and loading workers are still assumed available; they do not consume the
resident workforce. This is an explicit remaining staffing limitation.

Commuters use persistent cars, walk, or compare walking and one-line bus travel.
At the scheduled end of work they return home. A late worker first finishes
its outbound trip, then requests its return. Off-map activity is event based;
waiting bus passengers are queues and riding people are seats, not duplicated
pedestrian actors. Walking-route queries are cached across shared origins and
destinations. Idle periods can skip to service events only when there are no
native moving actors and no source-generated traffic.

## Reproduce and inspect

```sh
python tools/run_town_demo.py --population 1000 --out town-run.json --checkpoint town-checkpoint.json
python -m unittest tests.test_town_simulation tests.test_transit -q
```

The observed 24-hour run completed in about 132.5 seconds on this capture machine.
All 600 workers arrived, all 1,000 residents were home at the end, and all 44
vehicles remained registered with zero active road actors. Each household car
completed exactly two trips. Trucks completed 89 deliveries. The ledger records
about 105.53 unmet food units out of 3,000 daily demand, starting around hour 4:
initial kitchen food is exhausted before production starts, leaving some homes
without replenishment. No resource is conjured to hide that shortfall.
Food plus grain plus cargo plus consumption balances to within 0.00000003 units.
Unmet demand is not translated into illness, death or a population forecast.

`report()` exposes demand, production, consumption, unmet food, fuel, arrivals,
vehicle count and the resource balance error. The private app replays the
minute-sampled capture. Minute sampling can omit brief trips visually; active
movement itself was per tick.

## Quiescent checkpoints

`checkpoint()` saves authored world geometry, sites, resident and vehicle
records, inventories, bus state, pending schedule events, counters and clock.
It rejects moving actors, queued/active cargo jobs, onboard passengers and
unfinished resident trips. `from_checkpoint()` reconstructs the world, binds
routes to its newly generated lanes and restores logical state. The demo saves
the end-of-day state to JSON and verifies that the restored report matches.
This is not arbitrary mid-tick native save/load, and the current work schedule
covers one day; a resumed second day needs another schedule.

Other remaining limits include a synthetic corridor rather than a calibrated
multi-street town, inferred pedestrian crossings, no crowd collisions, no bus
transfers, no water/medicine/power/waste systems, no vehicle maintenance or
mortality, and assumed transit/freight staffing. Those need separate models
before drawing conclusions about long-term survival.
