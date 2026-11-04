# Shared building resources and resident labor

## Agreed behavior
Construction and ongoing consumption share building inventories and resource
operations. Residents can collect supplies and carry them home, receive deliveries,
or consume meals and services at the provider. Workers remain persistent residents.
A buildable construction company employs residents and sends them to temporary
construction sites. Only workers actually present contribute labor.

## Architecture
ResourceInventory is authoritative for construction and operation. Shared methods
handle finite transfers, shortages including inbound goods, and input-limited
recipes. Construction and consumers use the same physical resource catalogue and
material_load weight/volume calculation.

Regional one-way construction trucks and persistent local delivery trucks remain
transport adapters. Replacing local trucks with regional trips would lose parking,
loading and persistent vehicle identity. Importing the resource-economy prototype
wholesale would introduce a third runtime. Its finite-recipe and physical-load
concepts are incorporated into the existing building system instead.

Gameplay stays on its existing coarse Python event scheduler; C++ owns movement.
Attendance changes occur at arrival/departure events. Dispatch uses cached site
commitments and available builders, not a full population scan on movement ticks.

## Collection and consumption
Reservations are removed from spendable source stock and counted as inbound until
receipt. Delivery and shopping share shortage calculations, avoiding duplicate
orders. Shopping adds home stock only on return. Visits persist reserved/carrying
amounts and survive save/load and road-network rebinding. Failure to route reserves
nothing; a closed market returns an uncollected reservation to its source.

Automatic shopping selects a resident at home and a reachable market. The current
scenario carry limit is three units. Existing meals and clinic behavior remains.
A shopping trip spanning shift start schedules the missed commute upon return.

The prototype branch's food/grain/medicine quantities are in tonnes. The authored
city already uses portions/batches/doses, so this change preserves those units.
Physical values are illustrative scenario data, not calibrated measurements.
Utility networks and emission recipes are outside this migration.

## Construction company
Residents keep a permanent workplace ID and a separate temporary worksite ID.
They commute to the company, travel to a site, work there, and return to the company
for another assignment. At shift end they return via the company, retrieving any
parked personal car before going home. Site trips use existing walking/transit.
Blocked dispatches and returns retry on coarse scheduled events.

Regional crews bootstrap a new city until residents and an operational company
exist. The switch is persistent: deleting the company does not restore unlimited
regional building labor. Old queued regional crew arrivals cannot add anonymous
labor after the switch. Road demolition retains its existing regional crew adapter.

Production and work settle elapsed time before staffing changes. Construction work
and departure timing have separate clocks. Old saves retain defaults for new fields;
active site assignments, employer identity and dispatch commitments restore.

## Scope limits
Wages, skills, dedicated crew vehicles, C++ economy migration, and utility networks
are not included. Current construction material transport remains regional;
company workers travel through the existing pedestrian/transit system.
