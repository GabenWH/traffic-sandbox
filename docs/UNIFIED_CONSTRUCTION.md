# Unified construction contract (2D and 3D)

## Mandatory invariant

Every buildable tool registered in the catalog must provide an interactive preview
in both top-down and perspective projections. A buildable cannot be enabled in
only one projection. This is a runtime and CI-enforced contract, not a UI convention.

## Architecture target

- A single construction session owns selected template, world-space pointer,
  snapped anchors, authored vertices, rotation, elevation, validity and phase.
- A shared geometry generator returns a projection-independent preview
  description for roads, buildings and future buildable kinds.
- Both render modes consume that same description in the native Panda scene;
  view-specific code may only transform/present it, not independently compute
  placement or commit geometry.
- Preview updates are transient and must not mutate world state or save files.
  Confirm commits the same validated geometry; Escape discards it.
- Existing 2D controls take precedence in both projections.
- No separate hidden-Tk preview is allowed in the default native viewer.

## Enforced registration contract

Registration validates that each buildable kind has a geometry factory,
preview capability, validation/commit handler, and supported interaction
protocol. A missing handler is a hard error, never a silently disabled mode.
All catalog templates must resolve to a registered kind. New kinds must add
a corresponding shared preview/commit contract and tests.

## Required regression gates

1. Enumerate every registered kind and every catalog template; assert that
   both projections can present the same world-space preview description.
2. Test initial cursor movement, multi-vertex road updates, snapping, invalid
   placement, confirmation and cancellation without early world mutation.
3. Verify building footprint/orientation and road lane widths, intersections,
   elevation and cul-de-sac geometry against committed geometry.
4. Switch 2D/3D repeatedly mid-placement without losing session state.
5. Exercise window resize, zoom, pan, camera orbit, DPI scaling and viewport
   restoration; preview follows the correct world-space pointer.
6. Assert renderer parity by comparing canonical geometry rather than
   screenshots alone; add image-based smoke tests for visibility and z-fighting.
7. CI must fail when a catalog entry or registered kind lacks either preview.

## Migration sequence

1. Characterize current editor behavior with failing parity tests.
2. Extract construction state and canonical geometry from existing view code.
3. Route native 2D and 3D overlays through the same preview description.
4. Replace legacy per-view preview paths after parity passes.
5. Make registration and catalog tests mandatory in CI.

This document specifies the contract; it does not claim the migration or
regression gates are implemented.
