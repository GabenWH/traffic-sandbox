# Parking cache repair and commute-preference scaffolding

Grace authorized the parking/GC fix and clarified that parking experience should matter on the next day. The latest scope is scaffolding only for mode preferences: collect/persist the inputs, expose prior-day observations, and leave current mode selection unchanged.

The existing lazy parking work is preserved as a baseline in this isolated checkout. It checks the primary lot first and limits cold alternative walking queries per movement quantum. Keep its parking order, reservation, walking eligibility, and waiter semantics.

The performance repair bounds full Python walking-route retention with an LRU (512 routes; 65,536 point/link units), returns oversized routes uncached, and retains active trips independently of cache eviction. Native pedestrian route lookup uses exact binary point geometry rather than a graph of Python point tuples. Saves keep their existing point-based JSON schema and reconstruct the compact lookup on restore. GC remains enabled.

The scaffold provides neutral car/walk/transit preference profiles and at most 14 daily parking-experience records per resident. A record names the actual home/work pair and day. Repeated retries do not duplicate the day's observation. Queries for day D expose only matching observations from days before D. Saves preserve profiles and experiences; older saves load an empty model. Only actual outbound commute parking trouble is recorded. The selector is intentionally not connected, so car ownership, trip modes, and today's fallback rules are unchanged.

Approaches considered: collector-threshold changes alone leave live retained paths in place; background walking routing would be a larger scheduling change. Bounded retention plus the existing lazy/query-budget search directly addresses measured growth with a smaller behavior-preserving change. For mode choice, a full active scoring/probability model was deferred by Grace; the approved scope supplies its data and persistence boundaries.

Validation covers capacity/LRU/oversized paths, active pedestrian progress and saves after eviction, neutral/scoped next-day observations, actual overflow recording, same-day retry deduplication, changed workplaces, malformed saves, and unchanged car-mode selection. Run the complete suite and a controlled Arcata cache/collector experiment. Do not claim removal of all GC pauses or a new full-morning speedup without measuring it. No GitHub publication is authorized.
