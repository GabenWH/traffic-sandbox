# Arcata resource workday stress test

**Result: workday completion blocked by synchronous route planning.** This is a failed responsiveness test, not a completed-day validation of resource correctness.

## Scenario

- Full cached Arcata road map: 1,181 segments; synthetic premises on 100 connected streets.
- 500 four-person houses and 500 eight-person apartment buildings: 6,000 residents, 1,500 households, 3,000 workers.
- 20 endpoint businesses: 8 markets, 8 cafes, 4 clinics; three grain farms; one food factory.
- Additional construction company and one diagnostic construction site.
- Three shared-hub bus lines, 12 buses with 60 seats each, five-minute configured headways. Every bus leg passed vehicle-route validation. This is route feasibility, not proof of achieved headways.
- 24 persistent delivery trucks. Finite stocks; home food initially covers 12 hours.
- Planned simulation: 06:00–20:00. Buildings begin operational except the diagnostic worksite. Fictional premises and staffing, not real mapped businesses or calibrated land use.

## Observations

1. Ordinary automatic job assignment was interrupted after more than three CPU minutes after population initialization, before the workday could begin.
2. A separate diagnostic preassigned jobs as scenario data, then used the real scheduler, native traffic, shopping, transit and logistics. All 3,000 workers were assigned; this bypasses automatic job selection and is explicitly not a pass of that component.
3. The long diagnostic was interrupted after over six CPU minutes total without completing the first simulated hour.
4. A timed replay captured six stack samples over 91.10 wall seconds after simulation initialization. All remained at approximately 06:01. At the last sample, 48 residents were visiting and 5,952 were home. The replay intentionally exited with code 124 at its diagnostic limit.
5. Initial population accounting and resource balance were correct. No completed-hour production, delivery, bus throughput, commute-success, or shortage result is available. Zero initial unmet demand must not be interpreted as success.

## Located bottleneck

The sampled path is `CitySimulation._logistics` → `_choose_shoppers` → sorting candidate markets with `travel_seconds` → `TransitSimulation.journey_path` → `_walk` → `CityMap.find_pedestrian_route` → `PedestrianNetwork.route`.

The pedestrian query copies the full base graph using `graph.extend(self.layer.graph)`. Transit comparison also evaluates walking links to candidate stops. This multiplies graph work across homes, markets and stops, synchronously inside one economy event. Walking-route caching helps repeated identical queries but does not bound the first batch.

The needed next change is to reuse the pedestrian graph without copying it for each query, shortlist nearby destinations/stops, and budget or stagger household route planning. Then rerun this exact scenario through the full workday. Native movement has not been shown to be the cause by this test.

## Reproduction

From the repository root:

```bash
# Original automatic assignment path
python -u tools/run_arcata_workday_stress.py

# Authored employment diagnostic, intended full workday
STRESS_AUTHORED_JOBS=1 python -u tools/run_arcata_workday_stress.py

# Bounded stack-sampling diagnostic
STRESS_AUTHORED_JOBS=1 STRESS_WATCH_SECONDS=90 python -u tools/run_arcata_workday_stress.py
```

`watch.jsonl` contains exact stack traces and sampled simulation times. Other logs preserve the interrupted attempts. The harness changes scenario setup only; simulator implementation was not changed for this test.
