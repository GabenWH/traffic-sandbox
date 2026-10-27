# One C++ traffic engine

User requirement: consolidate legacy, data_first and native constructed-road traffic into the cpp branch. Preserve features; resolve behavioral conflicts by the date the behavior was written, newest first, then prefer data-first on ties.

Use the existing staged C++ engine as the sole application driver, called cpp. Python retains world construction, schedules, UI, external trip requests and output views. Shared/copy output representation is independent of driver selection. Freeze pre-consolidation Python engines under tests as independent differential references; they are not available from application APIs or launchers.

Approach: extend the existing native engine, remove production Python stepping/spawning fallbacks, migrate application/tool callers, retain and run behavior regressions. A full new C++ engine would discard existing tested behavior. Simply redirecting three mode names would hide unresolved differences and leave multiple advertised modes.

Provenance: origin/cpp f5d0c4e (October 24) supplies the native staged engine; main 3bee2f8 includes October 25 deconstruction and October 26 signal fixes; shared-state a8a1c13 supplies optional output views. Current source includes all cpp files. The cpp history merge retains the newer source tree, followed by explicit behavior review and tests.

Check signals, yellow commitment and rear clearance, deadlock bookkeeping, following/order independence, merge entry, seeded spawning and caps, external construction/deconstruction trips, route and map changes, manual edits, profiler/debugger and both output representations. Preserve Python unit-level decision helpers for reference tests without calling them in the application driving loop.

Do not add a Python fallback on compiler/runtime errors. Existing fixed-freeway demonstration and economy are outside the three constructed-road modes.
