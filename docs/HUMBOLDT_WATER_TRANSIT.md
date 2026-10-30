# Humboldt Bay water-transit scenario (prototype)

This experiment compares electric passenger ferries, electric hovercraft and connecting electric buses for seven settlements: Arcata, Samoa, Eureka, King Salmon, Fields Landing, Fortuna and Ferndale. **There is no surveyed ferry or hovercraft corridor, permitted docking site or confirmed navigable route in this model.** Routes, positions, speed, frequency, battery use and demand are example input assumptions, not real-world findings or engineering predictions.

## What works now

- Event-based transit timetable and multimodal routing (no simulation-tick passenger searches).
- Daily synthetic OD demand from seven terminal zones, deterministic seeds, dwell/transfer penalties.
- Departures, seating limits, service availability and vehicle fleet sizing.
- Energy and vehicle miles by vehicle type and aggregate completed journeys/door-to-door times.
- Policies for sensitive northern routes, hypothetical Highway 101 closures, and hypothetical hardening/closing of selected shoreline terminals.
- Self-contained HTML map player with 288 **precomputed Python scenario runs**. It supports fleet comparison, demand, sea-level scenarios, sensitivity restrictions, hypothetical closure controls, route inspection, timetable playback and origin/destination routing.

## Run

From the repository root:

```sh
python3 -m unittest tests.test_humboldt_water_transit -v
python3 tools/build_humboldt_transit_app.py
# Open humboldt_transit_app.html in a browser.
```

From Python:

```python
from humboldt_water_transit import Configuration, simulate
result = simulate(Configuration(daily_trips=2000, fleet='mixed', road_closure=True))
print(result['served'], result['mean_door_to_door_min'])
```

## Important scope boundary

This is **not yet attached** to `TransitSimulation` and `RoadVehicleSimulation` or the native C++ car engine. Existing buses operate on a real `CityMap` lane graph, whereas water links need georeferenced navigable channels, terminal access links, a water-movement integrator and tide/wildlife masks. Those inputs do not exist in the current world maps. Modeling standalone scheduled watercraft routes avoids pretending a water corridor is a road. The HTML movement player interpolates service movement; it does not run C++ or physical hovercraft dynamics.

First integration milestone: add `WaterTerminal`/`WaterLink` overlays to `CityMap` with a pedestrian-connection point, expose link travel times to the existing journey router, and execute dock/board/alight via the shared event coordinator. Keep geographic land/sea paths separate from road lanes and run them only on departure or route-change events. Preserve the Python world-management versus C++ movement boundary.

## Assumptions and missing evidence

The terrain/water SVG is schematic. Lines and distances have not been checked against navigability or safe landing access. Wind, currents, high sea state, hovercraft disturbance to shorebirds, ground clearance, floodproof docking, charging losses, crew needs, capital expense and vessel accessibility are not measured. The model treats any unprotected King Salmon/Fields Landing terminal as offline in a +6ft *stress-test toggle only*, not a real flood-elevation prediction. `road_closure` closes selected bus services as an illustrative disruption, not a modeled NOAA road-water intersection. Ferries, hovercraft and buses use assumed 9, 13 and 2 kWh/mi respectively; these are placeholders and are not verified designs.

Ferndale is connected via Fortuna bus rather than a hypothetical Eel River ferry/hovercraft route, which requires separate feasibility analysis.