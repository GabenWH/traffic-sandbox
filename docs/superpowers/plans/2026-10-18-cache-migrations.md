# Incremental cache migrations

**Base:** `6fe1084`, `perf/persistent-lane-occupancy`.

**Spec:** `../specs/2026-10-18-incremental-simulation-cache-design.md`.

Continue the approved cache work inline. Preserve exact traffic behavior in
both modes, seeded choices, snapshot positions, mixed vehicle lengths, and
partial/chained claims. Use focused failing tests before implementing each
consumer, then full-suite and baseline comparisons.

1. Add `traffic_route_state.py` with immutable route facts and independent
   movement/control/roundabout cursors. Migrate route helpers, signal boundaries,
   incoming-lane lookup, short-chain starting positions, and active merge caps.
2. Retain source-selection and sorted-roster views with the revision-cache
   foundation. Invalidate at existing selection and add/remove/clear APIs. Keep
   public list-returning helpers compatible and maintain random draw order.
3. Extend `TrafficOccupancyIndex` with delta publication and add/remove APIs.
   Integrate movement, claim, admission, placement, and removal events in both
   modes. Retain `rebuild()` for initialization/reference recovery. Update lane
   coordinates in place, repair local ordering, and insert structural additions
   only after the existing lane order is valid. Preserve the full-rebuild query
   and timing contracts for tests and diagnostics.
4. Compare exact state and occupancy queries with the base, including a sustained
   five-minute load. Record full rebuild counts, route reads, lane sorts, and
   timings. Run the complete suite, request independent review, and commit.

## Execution record

- Starting tree is clean at `6fe1084`.
- New production writes will use explicit owner APIs. Existing manual fixture
  placements/removals will be migrated to those APIs while keeping their traffic
  assertions unchanged.
- Tasks 1–3: implemented. Source and roster owners expose read-only sequence
  views; placement, resize, route replacement, and explicit reorder APIs own
  invalidation. Normal ticks publish changed vehicles without full rebuilds.
- Review: one independent reviewer fuzzed 6,000 delta transitions against
  `6fe1084`. Its corner-heading and repeated-merge speed-cap findings were
  reproduced by failing tests and fixed. The comparison harness was expanded
  to all brain fields, headings, merge-entry speed, occupancy queries, and
  overlap pairs.
- Safety regressions: unowned collection mutations, unpublished dimensions,
  explicit placement/resize/reroute/reorder, and stale profiler subphase timings
  were verified failing before their fixes. Full suite: 362 run, 17 skipped,
  no failures.
- Ruling: explicit lab processing-order replacement uses the reference rebuild
  to replace tie order. Ordinary motion retains delta-only publication. This
  keeps setup deterministic at the cost of O(roster) work on explicit reorders.
- Ruling: compare legacy occupancy against a full reference built from the
  completed roster. The old legacy index can retain a just-completed car until
  the next tick; the new index removes it immediately. Update decisions and
  completion events must still match exactly.
- Performance follow-up: the initial small-map data-first comparison regressed
  about 4%. Profiling isolated repeated route-cache validation in observation
  and intent helpers. RouteState now retains its immutable facts after sync()
  validates their owned input identities; it drops them on replacement. The
  generic single-source cache-hit path also avoids allocating a stamp tuple.
  Cache and route guard/boundary tests remained green; affected sustained runs
  are repeated after these changes.

- Continuation verification: 368 tests run, 17 skipped, no failures. Independent
  supplemental review found a retained-route fast path bypassing dependency and
  source mutation guards; two tests reproduced it before restoring source stamp
  checks. Constructor/route replacement now publish their source at the owner
  boundary, and guarded replacement checks before changing live fields/claims.
  Three owner/composition tests reproduced and verified those boundaries.
- Final guarded original-base comparison: `e3e377d`, Arcata/data-first, 600s,
  12,000 identical logical-state ticks, 200 peak cars, 67 completions, zero
  overlaps/full rebuilds/full lane sorts. Median 28.16 → 11.30ms, P95 39.55 →
  18.24ms. Short slip-lane comparison also matched all 6,000 ticks.
- Follow-up requested by the user: final guarded original-base Arcata/legacy
  comparison, 600s, 12,000 identical logical-state ticks, 200 peak cars, 59
  completions, zero overlaps/full rebuilds/full lane sorts. At mean 192 cars in
  stage two, median total tick time was 127.74 → 9.61ms (P95 139.64 → 11.67ms);
  median update-only time was 120.84 → 7.86ms. Result saved as
  `benchmarks/cache-migrations/arcata-legacy-final.json`.
- Results and limitations: `docs/analysis/2026-10-18-cache-migration-verification.md`.
