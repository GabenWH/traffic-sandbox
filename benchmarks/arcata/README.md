# Arcata traffic scale benchmark

This is a headless stress test of the `data_first` routed-car simulator on a
clipped Arcata street network. It uses the normal simulation update path;
the runner builds the input city and records timing without changing vehicle
behavior.

## Source data and coverage

- Boundary: OpenStreetMap administrative relation [112123, Arcata](https://www.openstreetmap.org/relation/112123), retrieved as OSM XML.
- Streets: Overpass API road extract, snapshot timestamp `2026-06-01T08:52:28Z`, filtered to motorways, trunk, primary, secondary, tertiary, unclassified, residential, and living streets. Service roads are present in the raw extract but excluded from the traffic network.
- The road extract query box was `40.82,-124.13,40.91,-124.02`. The exact city boundary is applied when clipping streets. This covers Arcata's urban road area; roads wholly outside the extract box in the city's far southern area are not included.
- The prior Unity project's Python generator and geographic input were not available in the searched project/library history. This input is OpenStreetMap road geometry, not vehicle GPS traces.

The OSM snapshot provides 681 clipped driveable ways, 1,181 routed road segments,
971 junctions, and about 88.4 miles of centerline. The benchmark chooses up to 16
boundary portals as combined car sources and sinks. The existing model applies
25 mph test-car behavior and OSM one-way/lane tags.

## Landscape and waterways

The starter world has fictional meadows, woods, fields, streams, a river and
scenic hills. The native map and perspective views share the same landscape;
ground and hills use a GLSL adaptation of Ferns-Forest's procedural meadow
shader. The hills are outside the buildable area, so they do not raise roads or
bury buildings. Landscape geometry is visual and does not block construction or
simulate water flow. It is saved with the world.

To add mapped landscape to an **existing Arcata save**, with a new Overpass
extract (network required):

```bash
python tools/import_arcata_landscape.py \
  --world arcata-homes.json \
  --download arcata-landscape.json \
  --output arcata-homes-with-landscape.json
```

Alternatively use `--landscape arcata-landscape.json` with an existing OSM
JSON, XML, or gzipped extract; repeat the flag to combine files. The command
creates a new save and preserves the source save, camera, and gameplay state.
It applies the same boundary and coordinate projection used by the Arcata road
importer; do not use it for a different city's save. To create a new Arcata
world with landscape and buildings in one step, add `--landscape EXTRACT` or
`--download-landscape EXTRACT` to `tools/import_arcata_homes.py`.

OSM forest, wood, meadow, grassland, farmland, park, wetland, water and
waterway tags are supported. Multipolygon holes are retained. Forest trees are
sampled deterministically for display and avoid existing roads and buildings;
individual tree positions and unspecified waterway widths are estimates.
The bundled road/building extracts contain no land-cover dataset, and no
Arcata elevation model is included; the importer does not invent Arcata hills
or claim that unmapped ground is water. Water and polygon geometry can extend
beyond the city boundary when the source feature crosses it.

## Import OSM buildings and parking

### Junction controls and roundabouts

The road importer now joins complete `junction=roundabout` rings, including
rings split across multiple OSM ways, into the normal dedicated roundabout
intersection. Approaches retain their geometry and use the existing shared
yield/merge behavior. Boundary-truncated or incomplete rings keep their clipped
road geometry and are counted in `incomplete_roundabouts`.

The bundled roads automatically load `arcata-road-controls-2026-11-09.json`.
This small offline supplement contains tagged nodes retrieved from the OSM API
for all 10,078 node IDs referenced by driveable source ways. Its `.source.json`
records retrieval, provenance and checksum. These are live node tags, combined
with the June road geometry; existing road coordinates are preserved.

The repaired map has 1,141 road segments, eight dedicated roundabouts, six
signal-controlled intersections, 100 intersections with mapped stop/yield
controls, and 199 terminal turnarounds. One ring is incomplete at the boundary.
Node tags apply to the matching topology and travel direction, including signs
at OSM way splits. `highway=mini_roundabout` is also supported. Road imports
accept JSON, OSM XML and gzip, so tagged supplemental extracts can be supplied
using another `--osm` argument.

Mapped lights receive working fixed-time programs that survive world saves.
The default program serves one incoming lane at a time, with 20 seconds green,
three yellow, and one all-red. These timings are simulation assumptions; OSM
does not provide the real signal program. Explicit runtime programs take priority.
Where controls are absent, local multi-arm intersections receive inferred stop
controls, with through-road priority based on road classification. Highway
merges and two-road continuations retain ordinary conflict/yield behavior.
`mapped_*` and `inferred_stop_intersections` metadata distinguish these cases;
the cached map has 384 inferred stop intersections. Boundary portals stay open.

`tools/import_arcata_homes.py` imports mapped building polygons into the same
Arcata road map and writes a normal city save. A small real OSM neighborhood
extract is included so the import can be tried offline:

```bash
python tools/import_arcata_homes.py \
  --buildings benchmarks/arcata/arcata-buildings-neighborhood.osm \
  --output arcata-homes.json
```

The sample covers only the box `40.860,-124.090,40.865,-124.085`, not all of
Arcata. It was retrieved from the OSM map API on 2026-10-31 and contains 169
building ways. It is separate from the road snapshot, which dates to June 2026.
Open the resulting file using the application's world-load command.

For a citywide extract, download tagged building ways and multipolygon relations
using Overpass, save the downloaded source for reproducibility, and create the
city in one command:

```bash
python tools/import_arcata_homes.py \
  --download benchmarks/arcata/arcata-buildings-overpass.json \
  --output arcata-homes-full.json
```

An existing Overpass JSON or OSM XML extract can instead be passed with
`--buildings`. The flag can be repeated to combine extracts. `--osm` and
`--boundary` select alternate road extracts and boundary XML. The importer
uses the center of each building's bounding rectangle to test city-boundary
membership, joins outer-way fragments in multipolygon relations, and avoids
duplicating a relation's tagged outer ways. Invalid or incomplete geometry is
skipped. Multipolygon courtyards are retained by splitting the filled building
area into simple polygons around each void. Invalid or incomplete courtyard
relations are reported and their outer ways cannot reappear as filled homes. The map service
requires network access and may be temporarily busy;
the offline sample does not require it. The importer will not overwrite an
existing extract or city save.

Mapped purposes now classify buildings as residential, commercial, or industrial.
Shops/offices and civic uses are commercial; warehouses and farm buildings are
industrial. Unknown `building=yes` uses fall back to residential. Garages and
sheds have no housing capacity. `building=no` is excluded. Original tags are
retained so assumptions can be reviewed. Every home defaults to capacity for four people; set
`--residents-per-building` to change the assumption. The homes start
operational, vacant, and without food. Use the normal household and supply
commands to populate them and stock them.

Buildings refer to persistent parking lots with individual oriented spaces.
Lots have 20-by-10-foot car stalls, 30-by-12-foot delivery bays, clearance between
stalls, and an 18-foot maneuvering aisle. A vehicle must fit a free stall;
departures reserve a destination stall before entering traffic. Failed road
admission retains the original stall. All buildings using the same lot share
its spaces and reservations; inventories, jobs, and housing stay per building.
Both views render the spaces and parked vehicles at their actual dimensions.

The building extract has no cadastral parcel boundaries. Lots and driveways are
**inferred**, not surveyed property data. Source site relations and matching
street/house-number tags group buildings; touching structures and nearby
outbuildings may also share. Where an independent lot cannot fit or connect,
a building may share a connected lot within 300 feet on the same side of the
road. Sharing does not increase capacity. Existing lots are never moved by an
automatic layout update. Explicit building placement can replan empty inferred
parking; occupied and authored parking is protected. New ground roads cannot be
drawn through parking lots. If neither a new lot nor nearby sharing works, the
import reports missing space/access rather than overlapping geometry.

Run the repeatable neighborhood parking check:

```bash
python tools/check_arcata_parking.py
```

It fills every physical car stall and delivery bay, rejects overflow, checks
vehicle/lot/building/road overlaps, and restores the occupied world from a save.
The inspector shows each building's category and parking lot ID.

Imported homes retain their mapped exterior polygons, including their angle and
non-rectangular outlines. Their axis-aligned bounds are kept for quick culling,
not used as the visible or selectable footprint. Interior courtyards stay empty;
the importer does not infer floor counts. Mapped footprints may themselves overlap,
and mapped positions do not guarantee a usable entrance or vehicle access.
This creates an authored city save; the separate synthetic workday stress
scenario is not changed by this import. Existing saves made with the old
rectangle-only importer need to be regenerated from their building extract.

## Citywide 10,000-resident stress test

The bundled `arcata-buildings-citywide-2026-11-04.json.gz` is a full municipal
bounding-box extract, snapshot `2026-11-04T18:00:23Z`, with original OSM tags and
geometry. It contains 5,590 tagged building ways/relations. Applying the bundled
Arcata boundary and deduplicating relation members imports **4,500 buildings**,
including **12 courtyard buildings**. It is distinct from the 169-building
neighborhood sample. The compressed file is 488,908 bytes; the adjacent
`.source.json` records the query, attribution, snapshot, and SHA-256 checksums.
No network connection is needed to repeat the test.

```bash
python -u tools/run_arcata_city_workday.py \
  --population 10000 --cars 1000 \
  --start-hour 7 --hours 3 --wall-seconds 900
```

This creates 10,000 residents, 2,500 households, 5,000 workers, and 1,000 household
cars in **one simulation**. The other 4,000 workers walk. Jobs are assigned with
seed 42 across 300 mapped nonresidential buildings. Population, job counts, and
initial food stocks are benchmark assumptions, not measured demographics or
real business operations. Existing four-person housing capacities and all
building footprints are preserved; unused houses remain vacant. The run fails
if the requested population exceeds housing capacity or cars cannot fit at home.

The test uses the updated shared parking model and the cached 1,181-road network.
The imported city has 2,964 inferred lots and 8,990 physical spaces. In this
dataset 100 buildings (four workplaces) lack vehicle access on that network;
these are retained and reported rather than silently dropped or teleported.
Road coverage has the limits described above, including excluded service roads.

Native movement and benchmark update calls use 0.05 simulated seconds. Reports
include p50/p95/p99/max update wall times, counts over 50/100 ms, worker arrivals,
driving/parked cars, cars waiting to depart, full destination lots, and missing
vehicle access. This is a headless **commute/parking and household-consumption**
test. It does not add artificial premises, buses, cafes, clinics, farms, or
production chains. The older `run_arcata_workday_stress.py` remains the separate
6,000-resident synthetic resource/service benchmark; their timings are not an
apples-to-apples comparison.

`--hours` controls simulated duration; `--wall-seconds` is a soft total wall-time
budget including setup, checked between import batches and update calls. A long
single update can overrun that budget. Reports and diagnostics are saved while
the run proceeds. For an independent hard process limit on Linux, use
`timeout --signal=INT --kill-after=15s 16m python -u ...` around the command.
The final `stop_reason` distinguishes a completed duration from a wall limit.
Each run creates a fresh results directory containing `configuration.json`,
`metrics.jsonl`, `summary.json`, and diagnostic `stacks.log` (every 30 wall
seconds; disable with `--stack-every 0`). No existing results are overwritten.

The checked-in `results/citywide-10000-smoke-2026-11-04/` is a **three simulated
minute** cloud smoke run, starting at 07:29:24. It completed 3,600 updates with
10,000 residents and 1,000 cars; 159 workers had arrived at its endpoint. It
recorded a 43.59-second maximum update during the initial commute burst. Later
30-second windows had median updates around 14–16 ms, but those large spikes
remain real. Stack sampling locates work in Python vehicle-route graph copying
and A* search. Those are baseline results from before background routing;
cloud timing does not predict desktop performance. Use the command above on the
target machine and compare its saved timing distribution and stop reason.

A follow-up instrumented single update at 07:30 reproduced the stall in 44.82 s
(`departure-profile.json` in that results directory). The update processed 500
worker departures: 215 car-dispatch attempts and 285 pedestrian trip requests.
Car dispatch made 766 lane-to-lane route searches, each copying the 8,700-node,
10,479-edge road graph. Graph copying alone took 34.92 s (77.9% of the update);
A* took 3.83 s. The scheduler packs all 5,000 workers into ten 500-person cohorts
at four-second intervals because this benchmark's workers have even resident IDs.
The original smoke run's overall mean update was 57.20 ms; its final 90 simulated
seconds averaged 16.85 ms. These measurements identified expensive synchronous
departure routing and repeated graph copies, addressed by the implementation below.

### Background routes, staggered shifts and learning

Authored-city fleet routing now uses a dedicated native graph and a low-priority
background worker. The worker builds reusable destination shortest-path trees
and returns plans without accessing live actors or parking. The owner thread
checks current access, reserves a real space and uses native admission checks.
An update never waits for a routing future. Explicit fleet calls outside an
update and the legacy standalone town API retain their immediate-result contract.
This does not move the simulation owner itself to a separate thread.

The default departure spread is two hours, with stable workplace/person offsets;
shift ends receive the same offsets. The default admission policy allows 20
commute starts per simulated second (burst four), one car per second at a shared
parking entrance, and at most 2,000 active road vehicles when admitting fleet
vehicles. Buses and native test-traffic spawners retain their own admission rules.
Only 32 queued commuters are checked and four route jobs submitted per 50-ms
movement quantum; internal event fragments share that allowance, while a bulk
advance processes multiple quanta. Newly completed driver plans receive a fair
admission opportunity alongside walking commuters;
at most 128 route requests are outstanding. Queued residents stay at home.

```bash
# Normal distributed morning departures, 07:30–09:30
python -u tools/run_arcata_city_workday.py --population 10000 --cars 1000 \
  --start-hour 7 --hours 3 --departure-window-minutes 120 \
  --departures-per-second 20 --max-active-cars 2000 --wall-seconds 900

# Synchronized worst-case demand; admission remains safely bounded
python -u tools/run_arcata_city_workday.py --population 10000 --cars 1000 \
  --start-hour 7.5 --hours 0.05 --departure-window-minutes 0 --wall-seconds 600
```

Completed route links provide observed travel times. Smoothed shared estimates
become routing costs on the following simulated day, and a driver keeps their
familiar route unless an alternative saves a stable individual threshold of
10–20%. Ordinary congestion never replaces an in-flight route. Road edits
invalidate old plans and preserve the existing mandatory journey-recovery path.
A remaining-route index also identifies active vehicles that still depend on a
particular link. This is shared traffic learning, not a personal-information or
live GPS model.

World saves retain departure policies/budgets, queued logical trips, observations
and familiar routes. Native trees and futures are rebuilt; routing-cache counters
may reset. Seeded schedules are repeatable, while asynchronous readiness can
change admission times slightly across runs or saves. Timing reports include
pending routes, completed queries, built trees, learned switches and waiting
commuters alongside the existing arrival, parking and conservation counters.

Post-fix cloud checks are saved in `results/background-10000-synchronized-2026-11-04/`
and `results/background-10000-spread-2026-11-04/`. Both restore the same full-city
authored geometry, seed 42, 10,000 residents and 1,000 persistent cars.

| Scenario | Simulated duration | Updates | Mean update | Maximum update | Final cars driving / parked at work |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous synchronous baseline | 180 s | 3,600 | 57.20 ms | 43,590.30 ms | 524 / 150 |
| Background routing, synchronized demand and bounded admission | 180 s | 3,600 | 17.33 ms | 689.23 ms | 412 / 124 |
| Background routing, first 15 minutes of the two-hour departure window | 900 s | 18,000 | 4.08 ms | 344.03 ms | 12 / 24 |

The synchronized run started 3,603 commuters and completed 654 route queries
using 235 built destination trees; 135 workers had arrived. The spread run
started 173 commuters and 27 had arrived. Both finished the requested duration
with all 10,000 residents accounted for and resource error below 1e-6. Four burst
updates and two spread updates exceeded 50 ms. The former 44-second stall was
not reproduced, but subsecond stalls remain and there is no hard frame-time
guarantee. These workloads have different departure/admission policies and route
costs, so their times are not an isolated algorithm-speedup measurement. The
spread run stops before peak morning demand; neither is a full workday run.

## Run

```bash
python3 tools/run_arcata_scale_test.py \
  --osm benchmarks/arcata/arcata-roads-2026-06-01.json \
  --boundary benchmarks/arcata/arcata-city-boundary.osm
```

The default run covers 900 simulated seconds at 0.05 seconds per update. It
starts with a 40-car cap and raises the cap by 40 every 15 simulated seconds.
At a rolling mean update cost of 200 ms over 20 frames (5 updates/second), it
holds the current cap for the remainder of the run. Directed portal routes are
precomputed before the timer starts; their setup time and reachable-pair count
are recorded separately. Results include a five-second time series, end-of-run
profiler samples, and a JSON summary.

## Matched performance comparison

The active-claims and persistent-occupancy measurements use this fixed schedule:

```bash
python3 tools/run_arcata_scale_test.py \
  --osm benchmarks/arcata/arcata-roads-2026-06-01.json \
  --boundary benchmarks/arcata/arcata-city-boundary.osm \
  --duration 300 --stage-caps 100,200 --spawn-interval 0.5 \
  --portal-count 16 --seed 20261017
```

See the [persistent occupancy comparison](results/persistent-occupancy-matched-300s-2026-10-17/comparison.md)
for validation, matched stage timings, and measurement limits. Input geometry,
reports, summaries, and profiler samples are retained for reproducibility.

## Attribution

© OpenStreetMap contributors. Data is available under the Open Database License
(ODbL) 1.0. See [OpenStreetMap's copyright and attribution page](https://www.openstreetmap.org/copyright).
