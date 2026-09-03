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
Unconnected two-way road endpoints derive cul-de-sac footprints and U-turn
connections between their road outputs and inputs. One-way roads retain
ordinary open endpoints with no bulb, setback, or turnaround. Each connection separates its
geometric `ManeuverDefinition` from its `ControlDefinition`, allowing driving
systems to interpret turns, merges, yields, stops, or signals without putting
that behavior inside A*.

`CityMap.rebuild_mobility_network()` replaces only the generated vehicle layer,
so future authored pedestrian, transit, and transfer layers can remain intact
when roads change. `CityMap.find_vehicle_route()` is a convenience for searching
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
