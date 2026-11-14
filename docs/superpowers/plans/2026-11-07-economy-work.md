# Arcata economy work

Goal: measure the published parking branch before reducing repeated Python work.
The user supplied the scope and authorized local fixes, with no merge or push.
The local cf92caf tree is a1532fae, exactly the published c6daaffe tree.

- [x] Verify remote head/tree, trace settlement callers, run existing relevant tests.
- [x] Record coarse phase timings and call counts for seeded Arcata, 16k residents,
  1k cars, 08:00–08:10, 50 ms updates. Keep setup and reports out of timings.
- [x] If household scans dominate, separate household consumption from attendance
  settlements. Keep the existing economy timer; flush household balances before
  resource/credit/membership changes and saves. Restore old saves safely.
- [x] Probe incoming-query scaling separately. Prefer ephemeral grouped totals
  over a persistent cache; preserve delivery exclusions, reservations, and order.
- [x] Test minute consumption, meal credit, midminute deliveries, relocation,
  save/load, duplicate shopping, job stages and exact incoming totals.
- [x] Repeat the same Arcata window without profiling for speed comparisons;
  report synthetic scaling separately. Run the project suite and review the diff.

Decisions: leave other checkouts and previous benchmarks intact. Use ordinary
Python and the existing native engine; no C++ changes or new dependencies.
Report short-window limits explicitly; do not extrapolate to a day or claim 3×.

Validation: 822 tests completed, 802 passed and 20 skipped. Independent code
review found no remaining actionable issues. Raw diagnostic results are separate
from two sequential pairs of plain runs; see docs/arcata-economy-profile.md.
