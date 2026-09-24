# Building Construction Needs and Deliveries

## Goal

Place buildings as active construction projects whose material and worker
needs arrive by truck from one abstract source. Exercise partial shipments,
worker assignment, construction progress, and completion without implementing
resource production or a finite provider economy.

## Building demand

Building templates define:

- `construction_needs`: required quantities by material;
- `construction_workers`: the number of workers needed on site; and
- `construction_work`: total work, measured in worker-seconds.

Placing a building immediately sets its phase to `under_construction`. Material
and worker deliveries may arrive in any order. Construction work begins when
all materials and the required workers are on site. The existing work order
consumes construction materials when it begins. Its progress advances by
`assigned_workers * elapsed_simulation_seconds`, with `construction_work`
measured in worker-seconds. The building becomes operational when the work
order completes.

The dispatch system treats construction materials as satisfied once the
construction work order has begun, because `Buildable.begin_work()` consumes
the delivered material inventory. It must not interpret that consumed
inventory as a new shortage and dispatch duplicate loads.

## Abstract source and shipments

The logistics system requests deliveries through a provider boundary. For this
slice, one non-placeable, unlimited virtual provider supplies construction
resources and workers from an access point at the west map edge. It has no stock,
production, finite fleet, or separate economy state.

Resource identity and physical properties are independent of supply: buildings
request resource IDs, while providers decide which requested resources they can
supply. Trips retain the provider ID and supplied resource ID. Later, mines,
quarries, and factories can provide those same resource IDs from their own map
access points and finite stock or production, without changing building demand
or shipment payloads. Provider stock reservation, extraction, and production
are future work; the initial virtual provider reports unlimited availability.

The regional port emits at most one truck every 20 simulation seconds across
all material and crew trips. It sends the first queued truck immediately when
ready, then keeps that minimum spacing even if the queue temporarily empties.
Queued trips reserve their material or worker demand so later updates do not
create duplicate shipments.

Each material shipment carries exactly one material. Resource definitions
are supplied to the logistics system rather than hard-coded into the
dispatcher. A `ResourceSpec` includes a resource identifier, unit, weight per
unit, volume per unit, and optional visual key. A `TruckSpec` defines maximum
payload weight, payload volume, crew capacity, vehicle dimensions, and an
optional visual key. A load amount is:

```text
min(remaining_need,
    truck_max_weight / resource_weight_per_unit,
    truck_max_volume / resource_volume_per_unit)
```

Further trips carry the remaining amount. Starter material and truck values
are calibrated so each starter material need takes at least two shipments;
larger or heavier needs can take more. Trucks for different resources do not
share a mixed manifest in this first slice. Before dispatch, in-transit cargo
is reserved against the need so concurrent trips cannot over-deliver.

Worker trucks carry up to their configured crew capacity. If the required
worker count exceeds one truck's capacity, more than one crew is sent. Workers
remain assigned at the building while the work order runs, then are released
when it finishes.

Material and worker trucks route over the existing road mobility graph from a
virtual provider gate on the west map edge. The gate must attach to the road
network at a lane position or junction; a two-way road ending at the boundary
already receives a cul-de-sac junction and can serve as that gate. A road
endpoint must still connect into the network for routes to continue beyond it.

Each building uses a virtual delivery access at its nearest road lane alongside
the parcel. Route candidates are checked across lane directions, since a
position on a one-way lane is only reachable in its travel direction. A
cul-de-sac is not required for a roadside building. Buildings with no road
access remain unserved until a road is built nearby. The final curb-to-building
movement is abstracted for this slice; deliveries apply when the truck reaches
the lane access. If no route exists, demand remains outstanding and is retried
when the road network changes.

## Runtime and presentation

A construction logistics system schedules trips from material shortages and
worker deficits after subtracting active and queued commitments, advances
truck routes, applies deliveries on arrival, and advances active construction
work. Runtime trucks use a native, flat-shaded cab-over model in 2D and 3D:
material trucks show an open flatbed with resource-specific cargo, and crew
trucks show an enclosed passenger compartment. Both face their current route
direction. Truck and trip state is runtime-only. Delivered material,
construction work progress, and assigned worker count are saved; after
loading, outstanding trips are regenerated from the saved building state.

The building Inspector shows required, delivered, and remaining material,
required and assigned workers, and work progress. The world view distinguishes
under-construction buildings from operational buildings. Resource and truck
visuals use visual keys so supplied art can be connected without changing
simulation data.

## Validation

Tests cover catalog requirements, loads limited by both weight and volume,
multiple partial shipments for one material, crew capacity and assignment,
work progress, construction completion only after materials and work are
satisfied, unroutable demand, and save/load during partial construction.

## Non-goals

- Placeable depots, mines, quarries, contractors, or finite providers.
- Resource production, processing chains, or ongoing economic inputs/outputs.
- A general workforce market or finite truck fleet.
