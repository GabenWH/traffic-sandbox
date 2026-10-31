# Native walking graph migration

Python remains authoritative for roads, sidewalk geometry, world edits, jobs and service selection. Compile the walking layer lazily into the same C++ library and graph/search implementation as vehicles. Keep walking and driving connectivity distinct. Native queries project endpoints and search immutable adjacency without copying the world graph. Query-local endpoint edges preserve bidirectional walking, access legs and junction crossing metadata. Python reconstructs the existing WalkingRoute API from returned edge slices.

Alternative: retain Python search with overlays. Rejected for this migration because the user explicitly requested unified native routing when car graph data already lives there. A separate Python worker would duplicate map ownership and serialization.

Rebuilding the Python world replaces the compiled walking snapshot; no native pointers enter saves. Existing transit revision checks remain. Transit service schedules, itinerary choices and simulation scheduling remain Python. This migration does not promise asynchronous economy scheduling or a completed Arcata workday; those are measured next in Codex. Native immutable queries release the GIL and can be used by workers without sharing mutable engine state.
