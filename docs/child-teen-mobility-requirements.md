# Child and teen mobility requirements — traffic and transit simulation

Status: design requirements; not yet implemented. Applies to the traffic engine, public transit, and Fields Landing economic scenarios.

## Agent and household model
- Represent children and teenagers as travelers, with configurable age bands, school enrollment, household membership, activity schedules, and mobility permissions. Avoid a universal fixed age cutoff: independent travel depends on age, guardian policy, accessibility, safety, and local conditions.
- Give agents school, friends, parks, recreation, shopping, work (where applicable), and home destinations; model school days, after-school peaks, weekends, and holidays.
- Generate walking, cycling, bus, ferry, and accompanying-adult trips. A child's trip requiring supervision creates an adult escort obligation and may require a shared household vehicle.
- If a safe independent option exists, allow the child to travel without an escort, releasing the adult's time and vehicle capacity. Do not assume every trip becomes independent.

## Network and safety
- Evaluate actual routes, not straight-line distance: sidewalks, crossings, vehicle conflicts, speeds, lighting and service frequency, waiting times, transfers, and age-dependent restrictions.
- Track safe independent access to common destinations within 15 minutes, by age band; track unsafe/unserved trips separately.
- Ensure the 95% private-car-trip reduction target is an output to test, not an enforced assumption.

## Economic accounting
- Record adult chauffeuring/escort minutes avoided and vehicle-miles avoided separately. Value time in a separate welfare account; do not treat it automatically as public revenue or additional paid production.
- Initial sensitivity assumptions: 1,500 households with children; 15/30/45/60 minutes of chauffeuring avoided per day; $20/hour illustrative value. At 30 minutes per weekday and 260 weekdays: 195,000 hours/year, $3.9M/year. At 365 days: 273,750 hours/year, $5.475M/year. These are assumptions, not measured outcomes.
- Avoid double-counting mileage, household ownership savings, labor value, and transit fares.
- Report results by household type and age band, including equity and accessibility.

## Implementation and validation
- Keep routing and movement in the existing C++ engine; schedule generation and household/economic accounting should be event-driven or aggregated, not evaluated on every 50-ms tick.
- Test matched conventional car-dependent and integrated transit/logistics scenarios with identical population, demand, and economic shocks.
- Add tests for escorted school trips, safe independent trips, missed connections, weekend/holiday schedules, household vehicle contention, and aggregation of saved adult hours.
- Measure mean, median, high-stress and low-stress outcomes, 95th-percentile trip times, unmet trips, and total cost per resident.
