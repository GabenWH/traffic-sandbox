# Shared native viewer

The default viewer uses one C++ Panda3D scene for the top-down map and perspective
world. Python retains editor commands, gameplay orchestration, Tk panels and save
interfaces. Install the [matching native SDK](../native/viewer/README.md) first.

```bash
python freeway_simulator.py                 # shared native Panda viewer
python freeway_simulator.py --viewer tk     # explicit legacy Tk map
```

## Controls

Existing 2D behavior takes precedence in both modes.

| Input | Behavior |
| --- | --- |
| Left click | Existing active build, inspect, route or transit tool |
| Middle drag | Pan with the pointer |
| Wheel | Zoom toward the world point under the pointer |
| Right click | Existing context menu |
| Alt + middle drag | Orbit in perspective mode; pan in map mode |
| Page Up / Page Down | Active tool's existing height shortcuts |
| Enter / Escape | Active tool's existing completion/cancel shortcuts |
| 3D roads / 2D map | Switch projection without rebuilding the scene |

Build and Inspector panels dock beside the native window. Tool previews, route
highlights and annotations use a retained Panda overlay. The hidden Tk canvas
does not draw a second set of actors. Existing 2D viewport and 3D camera save
fields remain independent and retain their format.

## Architecture

| Component | Owner and update frequency |
| --- | --- |
| Static geometry | Python compiles numeric buffers on edits; C++ creates local mesh batches |
| Active poses and pedestrians | C++ consumes native traffic buffers each frame |
| Appearance and route-height rulers | Registered on roster, visual or map changes |
| Parked instances | Replaced on fleet/parking changes |
| Visible instance buffers | C++ updates shared meshes without Python per-actor scene calls |
| Camera, panels and input dispatch | Python bridge plus active editor interactions |

The route-height cache is bounded to 4,096 entries. Roster/visual changes currently
republish metadata for the active roster; this is measured separately and is a
potential next optimization for high admission rates. Ordinary frames skip it.
Borrowed native engine buffers are consumed before the next engine operation.

Real C++ tests cover batching, invalid upload preservation, ramps/stacked roads,
clearing actors, local parked bounds and rejection of Python pose reads during
steady-state presentation. Embedded-window tests exercise construction, endpoint
snapping, camera restoration and new-world replacement. Graphics tests and the
benchmark distinguish software rendering from target hardware measurements.

The historical Python `ui/scene3d.py` adapters remain for reference geometry tests
and matched benchmarks. The default viewer does not call them.

## Measured presentation cost

Linux, Python 3.12.14, Panda3D 1.10.16, 8 November 2026. Each fixed-fleet case
runs both adapter orders with 80 samples per order and warmups. Traffic does not
advance. All actors are visible, and each case uses one instanced actor mesh.

| Active cars | Previous adapter, supplied heights | Native presentation |
| ---: | ---: | ---: |
| 1 | 0.0133 ms | 0.0039 ms |
| 60 | 0.7922 ms | 0.0057 ms |
| 250 | 3.6701 ms | 0.0143 ms |
| 1,000 | 18.9780 ms | 0.0503 ms |

These are steady-state CPU presentation times. They exclude simulation steps,
initial metadata publication and graphics rendering. The previous adapter is
given the correct elevation in advance, so the comparison already excludes its
expensive global height search. The benchmark also asserts pose parity.

The 1,000-car native p95 was 0.0849 ms. First publication, including model setup,
was 0.70 / 0.80 / 3.99 / 5.88 ms for the four fleet sizes; a changed roster still
causes full metadata republication.

The imported Arcata scene contains 1,181 roads, 4,500 buildings and 2,964 parking
lots, compiled to 1,273 static meshes, 310,866 triangles and 40,053 line segments.
Static compilation/upload took 1.37 seconds after map import. On llvmpipe software
rendering at 960 × 640, static render/synchronization averaged 9.35 ms for the map
and 14.22 ms for perspective. Those graphics runs contain no active actors and
exclude editor, economy and simulation work; target-machine frame time remains
to be measured.

The [raw measurements](../benchmarks/native-viewer-2026-11-08.json) retain all
samples, metadata costs, source hash, scene counts and separate Arcata graphics
measurements. Reproduce with:

```bash
python tools/benchmark_native_viewer.py --arcata --samples 80 \
  --output build/native-viewer/results.json
```
