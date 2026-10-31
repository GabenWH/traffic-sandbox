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

## Import OSM buildings as homes

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
skipped. The map service requires network access and may be temporarily busy;
the offline sample does not require it. The importer will not overwrite an
existing extract or city save.

Each mapped building is deliberately treated as a home, even if its tags say it
is a shop, garage, or another non-residential structure. `building=no` is
excluded. This is a simulation assumption, **not** evidence of actual land use
or population. Every home defaults to capacity for four people; set
`--residents-per-building` to change the assumption. The homes start
operational, vacant, and without food. Use the normal household and supply
commands to populate them and stock them.

The city model currently supports axis-aligned rectangular building parcels.
Each imported polygon is approximated by its bounding rectangle in feet; it does
not preserve the exact polygon, orientation, holes, or floor count. Rectangles
can overlap each other or a road, and mapped positions do not guarantee that a
usable entrance or vehicle access exists. This creates an authored city save;
the separate synthetic workday stress scenario is not changed by this import.

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
