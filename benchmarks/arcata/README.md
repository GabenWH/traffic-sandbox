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
