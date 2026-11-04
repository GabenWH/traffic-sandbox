# Shared parking implementation plan

**Goal:** Give imported and newly placed buildings physical parking, allow several buildings to share one lot, and classify every building as residential, commercial, or industrial.

**Architecture:** Buildings refer to persistent city-owned parking lots. Each lot has individually sized, oriented spaces and a driveway; fleet vehicles occupy or reserve those spaces. Building addresses, inventories, and jobs remain separate when parking is shared. Python plans layouts and handles admission at events; native road movement keeps its existing tick.

**Constraints:** Use the existing Python/C++ application without new runtime dependencies. Preserve footprints and old saves. Source building outlines are not property boundaries: generated parking and proximity groups must be labelled inferred. Do not publish or push this branch as part of implementation.

**Decisions:** Use mapped building purpose when present, fall back to residential for unknown OSM buildings, and keep source tags. Explicit groups and matching addresses can share parking; touching buildings/outbuildings can receive an inferred shared lot. Generate collision-checked spaces plus maneuvering space outside buildings and roads. Report a zero-capacity or disconnected lot if geometry cannot support usable parking, rather than inventing capacity or access.

## Tasks

- [x] Model: add oriented spaces, lots, building categories, and parking references. Test dimensions, overlap detection, and classification.
- [x] Layout/import: generate deterministic lots, share groups, retain OSM classification and source tags, and give new placements parking. Test real source geometry, obstacle clearance, shared groups, and repeatability.
- [x] Fleet: allocate one fitting space per vehicle, share capacity between building sites, reserve arrivals, and preserve origin space on failed dispatch. Test multiple cars, trucks, full lots, same-lot moves, and real native trips.
- [x] Persistence and presentation: save lot geometry/references/claims, migrate old worlds, render spaces and parked vehicles in both views. Test round trips, invalid claims, and 3D geometry.
- [x] Verify the full suite and run a populated parking check on all 169 imported buildings. Record actual capacity, sharing, overlap, and access results.

## Review focus

Failed native admission must not lose an origin space or leak a reservation. A large truck must not occupy a car-sized stall. Shared lots must count vehicles and reservations across all associated buildings. Saving and road rebinding must preserve unique vehicle/space claims. Dense source geometry must not create overlapping stalls or silently move buildings.

## Implementation decisions and verification

- Generate a separate delivery-sized bay beside the car stalls. Vehicle admission checks actual dimensions and chooses the smallest fitting free space; nominal site capacity cannot create additional spaces.
- A new building can replan empty inferred parking. Occupied or authored parking rejects placement before mutation. New ground roads cannot cross parking surfaces; elevated decks with 16 feet of clearance are permitted.
- Ground parking does not connect to pedestrian-only paths or elevated road decks. Road edits resolve the existing driveway mouth again rather than moving parked vehicles.
- Legacy saves assign stationary vehicles before inbound vehicles. Existing inbound trips without reservations can wait for space and remain saveable.
- Independent review found and verified fixes for arrival reservation theft, driveways crossing their own stalls, invalid path/bridge access, stale truck cargo meshes, and road authoring through parking.
- `python tools/check_arcata_parking.py`: 169 buildings, 102 connected lots, 22 shared lots, 316 occupied spaces (214 cars and 102 trucks), zero overlaps, overflow rejected at all 102 lots, occupied save/restore passed.
- An independent Shapely check also found zero lot/road/building overlaps, zero stall overlaps, zero driveway/building or driveway/stall overlaps, and no inaccessible lots. Shapely is used for validation only and is not a project dependency.
- Final full suite with Panda3D installed: `python -m unittest discover -s tests` ran 658 tests in 357.465 seconds, no failures, two display-required tests skipped. The new parking tests include a real native road trip, occupied-save restoration, road rebinding, and old-save overflow migration.

Parking geometry and sharing remain inferred from source footprints/tags, not surveyed ownership. Native road actors still enter and leave at the driveway mouth; off-street steering and parking maneuver animation are outside this change.
