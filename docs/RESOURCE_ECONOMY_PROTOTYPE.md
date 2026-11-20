# Resource economy prototype

**Scope:** opt-in data model and testable ledger. Does not change existing construction, native driving, routing, player UI, or saves.

## Existing systems retained

- Construction resource IDs and truck definitions remain in `ui_tools/construction_resources.json` and `resources.py`. The economy data repeats existing IDs with the same construction mass/volume values so a future unified catalog can replace the duplication without changing gameplay IDs.
- Existing buildings use `models.ResourceInventory`; pass the exact `building.inventory` instance to `ResourceNode` to avoid parallel stock ledgers.
- `construction.ConstructionSimulation` and `UnlimitedConstructionProvider` remain active as before. Connecting the new economy to that provider is future integration work, not silently enabled.
- `CitySimulation` and the native road fleet remain unchanged. Reusing its coarse 60-second economy scheduling is the intended integration point, **not** the 50-ms vehicle tick.

## Model

Resource kinds:

1. `cargo`: finite goods shipped by truck; every spec gives kg/unit and m³/unit, with at most one cargo type per order in this prototype.
2. `utility`: electricity, potable water, wastewater; ledger values are placeholders for later power/pipes. They do not spawn trucks.
3. `emission`: air pollution and carbon emissions; generated amounts accumulate in an output counter, not building inventories. Pollution dispersion is out of scope.

A node may have many recipes and store many cargo types. A scheduled recipe atomically consumes **all** inputs and adds **all** products and byproducts. A zero-input recipe models extraction or natural growth. The supplied example concrete plant consumes gravel, sand, cement, power and water and outputs concrete, solid waste, wastewater and air pollution. Recipe quantities are illustrative gameplay numbers, not physically calibrated measurements.

Normal producer inventories are finite, including byproducts; stock can run out. An import/export node is a special outside-world **source** for any configured set of cargo IDs, with unlimited availability and no stored external stock. Multiple categories may share the same port. Whether ports accept outbound goods for export remains **undecided**; no export sales or sinks are implemented.

## Freight lifecycle

1. A requester with a material shortage identifies a supplier; a call to `reserve_delivery(...)` creates one order limited by available stock and truck weight/volume.
2. Multiple reservations subtract from remaining available finite stock so no two trucks claim the same load.
3. When a truck actually loads, call `pickup(order.id)`, which deducts stock for finite producers. External import supply remains unlimited.
4. Give the order and cargo to the existing road vehicle routing system. Do **not** call `deliver` until arrival is reported.
5. On arrival call `deliver(order.id)` to credit the receiver's existing inventory; on route cancellation call `cancel(order.id)` to release/restore undelivered stock.

Production and logistics decisions run only on scheduled events. The prototype itself does **not** create vehicles, plan routes, enforce loading times, choose suppliers, persist orders, or automate deliveries. It deliberately leaves real fleet integration and infinite external sinks for a later phase.

## Minimal smoke test

```sh
python -m unittest discover -s tests -p test_resource_economy.py
```

(Requires the repository root on Python's import path.)

## Proposed next integration step

Replace virtual construction material sourcing with an adapter selecting a real `ResourceNode` (including the external port), reserve before dispatch, and bind the new freight order to each existing `ConstructionTrip`. Only then add the concrete plant and other producer buildables to the UI. Run full construction/city persistence and transport regression tests before merging.
