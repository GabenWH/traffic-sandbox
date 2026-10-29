# Authored city gameplay

Start the program with `python freeway_simulator.py`. Build roads and buildings using the existing build menu. Completed homes provide housing capacity; cafes, bakeries, farms, food markets and clinics become operating sites after their construction deliveries and work finish. Nothing is populated merely because a footprint was placed.

## Play a settlement

1. Build homes and workplaces connected to pedestrian lanes and vehicle roads. Standalone pedestrian paths remain available to walkers.
2. Inspect a completed home, then choose **Simulation → Move in household**. The command admits 1–4 newcomers and, where road access exists, one persistent household car. An apartment can hold several households. Resident IDs appear in the home's inspector.
3. Workers take reachable vacant jobs automatically. To change an assignment, select a workplace and use **Simulation → Assign worker**, entering a resident ID while that person is at home.
4. Select a building and use **Import supplies** for an explicit external delivery, for example `seed 400`, `grain 200`, `food 100`, or `medicine 40`. These imports are recorded. Farms consume finite seed, bakeries turn grain into food, and households consume three scenario food units per person per day. Recipes and rates are editable in `ui_tools/buildables.json`.
5. Select an accessible building and **Commission truck**. Trucks fetch available supplies for operating businesses and occupied homes, retain their identities, fuel and cargo, and use the shared construction/vehicle engine. Household food deliveries use markets as their suppliers.
6. Build and complete bus stops. Select **Build bus line**, click stops in travel order, then press Enter. The line repeats, with two 60-seat buses and a ten-minute departure headway. Lines can share stops for passenger transfers. Stops show waiting counts; moving buses show occupancy. Select a stop/building and **Refuel** to import fuel for its parked vehicles.

The inspector shows actual occupancy separately from capacity, staff present, stocks, household desirability and the household's current moving buffer. The canvas shows the city clock and active native walkers; the optional 3D view displays walkers as simple figures.

## Persistent households and housing

A newly completed house is a vacancy for existing households. Population admission is a separate player command. Household members keep their IDs, work assignments and car through relocation. A move reserves destination capacity, transports members through the native engine, and transfers the household's proportional food share once. The address changes after every member arrives. A household must be together at home to begin a move.

Desirability combines housing quality (15%), available food access (40%), household workplace access (30%) and a staffed/supplied clinic (15%). Access uses network travel time, including walking, expected bus waits and transfers, with a 30-minute decay scale. These weights are provisional gameplay values. Walking entrances and stop bays are inferred.

The household moves only when a reachable vacancy improves desirability by more than its moving buffer. The buffer responds exponentially over a two-year time scale, toward a satisfaction-dependent target between 10 and 80. It starts at 40 and resets to 75 after a move. Persistent poor access erodes it; improving conditions rebuild it. The stored anchor and elapsed simulation time determine the current value without updating it each tick.

Monthly assessments are staggered. Building changes queue reassessments; the planner evaluates at most 32 vacancy candidates per household assessment. Route estimates are cached. Households reassess later if they are away when a suitable home opens.

## Clocks and saves

Active motion uses the existing C++ engine in steps of at most 50 ms. Economy runs on minute events and settles before staffing/occupancy changes. Native completion events apply arrivals at the same simulation time regardless of rendering or update chunk size, so production cannot include time before arrival. Cafes have a service budget of one meal per worker per simulated minute, with at most one prepared meal per worker. Construction coordination runs on one-second events, observing completions from the same transport clock. Work/return journeys and meal visits recur daily. Housing and job decisions run on scheduled events, rather than on rendered frames.

World version 8 stores building operation rules and a separate logical gameplay snapshot. JSON saves preserve household memory, membership, vacancies, fleet fuel/cargo, service queues, and active town walking/bus/car progress. Loading rebinds them to saved geometry. Road edits replan from recorded positions; unreachable journeys remain pending rather than removing people or cargo. Construction's existing save behavior requeues undelivered construction loads.

## Scope and checks

This is a gameplay integration, with synthetic production/food/service units and rates. Immigration is explicit; health, mortality, rent, money, aging, driver staffing and loading staffing are not modeled. Transit wait predictions use expected headways rather than live congestion/capacity forecasts. Sidewalk junctions and the first crossing check retain their existing inferred geometry and one-way vehicle awareness.

The reproducible headless integration scenario uses the real BuildingTool, construction deliveries, recurring jobs, finite stocks, 60-seat buses, truck deliveries, a JSON checkpoint and a household move:

```sh
python tools/run_city_gameplay.py --output docs/city-gameplay-run.json
python -m unittest discover -s tests
```

`tests/test_city_gameplay.py`, `tests/test_households.py` and `tests/test_city_gameplay_ui.py` cover the authored lifecycle, ledger conservation, active saves, closures, scheduling, housing competition and app command wiring. A display/Panda3D installation is required for interactive visual inspection.
