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

There is one non-placeable, unlimited source for construction resources and
workers. It has no stock, production, finite fleet, or separate economy state.
The source is used only to generate deliveries in response to building demand.
Factories, mines, quarries, and production chains remain future work.

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
single virtual source access at the west map edge to the nearest reachable
roadside position for the building. If no route exists, the corresponding
demand remains outstanding and is retried when the road network changes.

## Runtime and presentation

A construction logistics system schedules trips from material shortages and
worker deficits after subtracting in-transit commitments, advances truck
routes, applies deliveries on arrival, and advances active construction work.
Truck and trip state is runtime-only. Delivered material, construction work
progress, and assigned worker count are saved; after loading, outstanding
trips are regenerated from the saved building state.

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
