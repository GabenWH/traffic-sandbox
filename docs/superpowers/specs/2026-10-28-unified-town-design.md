# Unified city gameplay

Approved direction: user requested amalgamation of the building tools and town prototype, persistent households, desirability, reluctance to move changing over years, and keeping decisions out of the 50 ms movement tick. User said to proceed with the full integration.

## Architecture and approach
Extend the existing Building and template catalog with operational roles. CitySimulation extends the existing service coordinator, using its production, service queues, logistics, fleet and transit. The existing Building inventory remains the stock ledger. One RoadVehicleSimulation advances all active vehicles and pedestrians; construction observes the same completion events. A separate adapter with copied building inventories would create conflicting ownership; replacing the established building/construction architecture would discard useful tested behavior.

Existing residents/jobs template fields remain capacities. Actual occupancy is derived from persistent household membership. Completed new housing is vacant; an explicit invite action admits a household, separately from relocation. Households of up to four move together. Existing saved residential capacity does not silently create population. Empty/disconnected housing remains buildable and inspectable; disconnected operations wait for access rather than crash.

## Scheduling
Only active native movement and immediate transport interactions advance in <=0.05 s steps. Economy runs every 60 simulated seconds, construction coordination every second, job allocation daily/on building changes, staggered household assessments monthly/on relevant changes. Household memory is evaluated analytically from elapsed years; no per-frame resident, inventory, desirability or vacancy scans. Building placement/completion and graph edits invalidate relevant indexes. Vacation/migration are not mortality or health models.

## People and housing
Household and resident IDs persist. Households own an address and relocation buffer (0..100), with a two-year exponential response toward a satisfaction-dependent target. Relocation compares household-specific accessibility scores and requires an improvement greater than the buffer. Work, finite food/service access and crowding affect scores. Candidate search uses cached access estimates and bounded candidate batches. Moves reserve capacity, preserve membership and jobs, use native movement, carry their proportional food share, and relocate persistent cars; buffers reset high after arrival. No person/resource duplication. An occupied demolished/disconnected home remains represented until residents can move safely.

## Gameplay integration
The build menu includes cafe, bakery, farm, market, clinic and bus stop templates with construction costs and configurable operational rules. Businesses activate after construction and require actual workers and finite inputs. Daily work and return journeys repeat. Players can invite households, commission trucks, select bus stops to create repeating 60-seat lines and inspect occupancy/stocks/service state. Stops and walkers are drawn in the app.

## Persistence
World saves contain declarative roles plus a versioned gameplay snapshot: residents, households, memory, reservations, schedules, stocks (in Buildings), fleet, service queues and transit. Active journey progress is restored against the saved unchanged geometry. Native route data and movement decisions are rebuilt from saved state. Road edits invalidate routes and suspend/replan journeys while retaining people, vehicles and cargo. Construction's existing save behavior continues to requeue undelivered materials.

## Verification
Use real BuildingTool placement and lifecycle tests, whole household conservation/relocation tests, multi-year scheduling tests, recurring work/food/logistics checks, connected 60-seat transit tests, active journey save/restore and road-edit tests, UI command wiring tests, then the repository regression suite. Rates/scores are gameplay defaults, not calibrated empirical predictions.
