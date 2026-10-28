# Routing architecture

Routing is split into three layers so the pathfinder has no dependency on a
transportation type.

## Generic search

`pathfinding.py` provides `astar()`, `Transition`, `Path`, and `DirectedGraph`.
A node can be any hashable value and an edge can carry any object. Search only
requires nonnegative costs, an expansion function, a goal predicate, and a
nonnegative heuristic. A zero heuristic gives Dijkstra behavior and is the safe
default when a graph combines costs with different meanings.

## Mobility layers

`MobilityNetwork` owns named `MobilityLayer` instances. Layers may represent
vehicles, walking, public transit, transfers, or another domain. Selecting
multiple layers combines their nodes and directed edges before search. Transfer
edges can join nodes contributed by otherwise independent layers.

The optional distance heuristic is appropriate only when every selected edge
cost is a distance. Time, fare, accessibility, and preference-based searches
should supply an objective-specific heuristic to `astar()`, or use the default
zero heuristic.

## Vehicle topology

Every lane contributes a directed edge from its start node to its end node.
Lanes have structural addresses derived from their road segment, direction, and
index; they do not own unrelated persistent UUIDs. Each road derives geometric
`route_inputs` and `route_outputs` at its endpoint cross-sections. A port carries
its lane group, centroid point, heading, and usable width.
Intersections have derived footprint radii, and lane travel is set back to the
footprint boundary so connection curves have real space instead of collapsing
at the crossing center. Intersections collect road outputs and road inputs and
generate explicit curved `LaneConnection` objects between those ports.
Same-segment and intersection U-turn movements are omitted by default.
Single-road two-way endpoints derive cul-de-sac footprints and U-turn
connections between their road outputs and inputs. If another road joins that
endpoint, it becomes a standard multi-road intersection. One-way roads retain
ordinary open endpoints with no bulb, setback, or turnaround. Each connection separates its
geometric `ManeuverDefinition` from its `ControlDefinition`, allowing driving
systems to interpret turns, merges, yields, stops, or signals without putting
that behavior inside A*.

`CityMap.rebuild_mobility_network()` replaces the generated vehicle and
pedestrian layers. Other named layers, such as transit and transfers, remain
intact when roads change. `CityMap.find_vehicle_route()` is a convenience for searching
from the beginning of one lane to the end of another.
`CityMap.find_vehicle_route_between()` accepts precise `LanePosition` values,
adds temporary partial-lane edges to the query graph, and can therefore start or
finish at any distance along a lane without changing the persistent network. It
also accepts a selected `Intersection` as an endpoint, including one whose kind
is `cul_de_sac`. A junction
start exposes all outgoing road inputs, while a junction destination accepts all
incoming road outputs, so callers do not have to guess a representative lane.

Lane connections have structural identities derived from their intersection and
road ports. Their saved maneuver/control configuration is reapplied after their
curves, intersection radii, cul-de-sacs, lane setbacks, and vehicle mobility
layer are derived from authored geometry. Rebuilding an unchanged geometric
port also retains its live control configuration when an upstream road is split.

The runtime-only test-traffic layer can mark any generic intersection,
including a cul-de-sac, as a combined source and sink. It routes between
selected junctions using this same vehicle graph and flattens lane, road-port,
and lane-connection edges into the polyline followed by each diagnostic car.
Each car owns a `CarBrain` that chooses desired speed and whether to request
entry into its next movement. For stop-controlled movements, the runtime
`AllWayStopCoordinator` records completed-stop arrival order and active claims;
it does not move cars or issue driving commands. Standard intersections can be
configured as all-way stops by applying `ControlType.STOP` to all generated lane
connections. Those definitions persist, while arrivals and claims remain
runtime-only. Signals and roundabout movement topology are not implemented.

Routed-car perception uses a runtime longitudinal occupancy grid keyed by the
current canonical lane, road-port traversal, or lane connection. One pass bins
cars into fixed-length cells, and each brain probes a bounded number of cells
ahead. This avoids both complete-route equality checks and per-lane comparison
sorting, gives expected O(n) tick cost, and maps naturally to flat GPU buffers
and atomic cell counts later. Desired-speed following remains a brain decision;
the motion layer independently clamps travel to make non-overlap an invariant.

The car brain also derives turn-signal intent from the next route-carried
`ManeuverDefinition`. Left and right turns signal within 100 feet of the
movement, U-turns use the left signal, and through movements do not signal.
Intent remains owned by the brain and is merely rendered by the UI; junctions
do not control vehicle indicators.


## Road-owned pedestrian network

`Road.pedestrian_sides` configures left, right, both, or no walkways.
`Road.pedestrian_offset` is the distance from the carriageway edge to the
walkway centerline, in world feet. `Road.rebuild_lanes()` regenerates both
vehicle lanes and separate `Road.pedestrian_lanes`; vehicle consumers continue
using `Road.lanes` exclusively. Each pedestrian lane has a structural identity
`<road id>:pedestrian:<side>` and supports walking in both directions even on
a one-way road. Road splits copy the configuration to both resulting roads.
Persistence saves the configuration and regenerates the geometry on load.

For compatibility, a road with unspecified sides defaults to both walkways,
except legacy Arcata road names ending in `[motorway]` or `[motorway_link]`,
which default to neither. This default is an assumption, not mapped sidewalk
data. Supplying `pedestrian_sides=()` explicitly disables walkways on any road.

`PedestrianNetwork` compiles the exact road-owned lane objects into the
`pedestrians` mobility layer. It does not generate a second set of lane
geometry. `CityMap.find_pedestrian_route(start, destination)` snaps a query to
those walkways and runs A* with distance costs and a Euclidean heuristic.
Temporary partial-lane query edges allow arbitrary positions without adding
per-building nodes to the persistent graph. The route's flattened points can
be passed to `NativeTrafficEngine.register_pedestrian_lane()` for C++ movement.
Road ownership and graph compilation remain in Python; active walkers advance
inside the native engine. Rebuilding roads does not migrate walkers already
registered with that engine; their paths must be replaced by the caller.

Junction connectors are still inferred straight links between walkway ends.
They are not authored crosswalks or accessibility rules. The current native
walker prototype checks only its first crossing and waits for vehicles; this
change does not add vehicle yielding, crowd collisions, transit, or active
pedestrian save/load. Walking cannot be routed on a city with no walkways.

Example:

```python
road = city.add_road(
    [(0, 0), (300, 0)],
    pedestrian_sides=("left", "right"),
    pedestrian_offset=3.0,
)
route = city.find_pedestrian_route((20, 15), (240, 15))
assert city.pedestrian_network.lanes[0] is road.pedestrian_lanes[0]
```


### Pedestrian-only paths

A standalone walkway is a segment of the same authored road network with zero
vehicle lanes and exactly one `center` pedestrian lane. Its geometry follows
the authored centerline directly, rather than generating sidewalks on either
side of an imaginary carriageway. `Road.width` returns its physical path width;
for a street it continues to return the carriageway width.

```python
campus_walk = city.add_pedestrian_path(
    [(300, 0), (300, 500)], name="Campus walk", width=6.0,
    endpoint_overrun_tolerance=0,
)
assert campus_walk.lanes == []
assert campus_walk.pedestrian_sides == ("center",)
```

The helper uses `CityMap.add_road()` with zero forward/reverse vehicle lanes,
so splitting, same-elevation junction attachment, editing, deletion and
persistence use the existing lifecycle. The pedestrian layer includes its
center lane, while the vehicle layer gets no lane or road-port nodes from it.
A path can connect two streets for pedestrians without giving cars a shortcut.
Crossings at distinct elevations remain disconnected. Elevation is authored
per segment: the point-based route query still snaps in 2D, so overlapping
levels cannot yet be selected explicitly by a query.

These are generic authored paths; no campus, trail or OpenStreetMap footway
dataset is imported by this change. Access permissions beyond pedestrian versus
vehicle, path surfaces, stairs, wheelchair access and bicycle rules are not yet
represented. Path junction links still use the inferred pedestrian connectors
described above.
