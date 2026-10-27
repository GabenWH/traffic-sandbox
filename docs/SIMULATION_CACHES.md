# Simulation caches

`simulation_cache.py` provides lazy derived values tied to explicit source
revisions. It uses the Python standard library and the existing simulation
thread. Create a cache once with its owner, then reuse it across ticks.

## Basic use

```python
from simulation_cache import CachedValue, RevisionSource

route_revision = RevisionSource("vehicle route")
route = ("a", "b")
edges = CachedValue(
    "route edges",
    dependencies=(route_revision,),
    build=lambda: tuple(zip(route, route[1:])),
)

assert edges.get() == (("a", "b"),)
same_edges = edges.get()  # Reuses the saved object; no route traversal.

with route_revision.mutate():
    route = ("a", "c", "b")

assert edges.get() == (("a", "c"), ("c", "b"))
```

The mutation increments one source revision. It does not find dependents or run
builders. The next `get()` checks its declared revisions and computes only if
one changed. Each source retains its immutable stamp until its next change;
the cache keeps one current value, not a history of generations.

Check whether a change is effective before entering `mutate()`. Repeated writes
of the same semantic state need not invalidate anything. Nested mutation scopes
for one source publish one revision when their outermost scope exits.

## Mutation and read phases

Place source writes inside the owner's mutation method:

```python
with route_revision.read_only():
    current_edges = edges.get()
    # Entering route_revision.mutate() here raises before its body runs.
```

Reads depending on a source that is currently being mutated also raise. A cache
builder cannot mutate any revision source or clear another cache. Recursive
cache evaluation raises `CacheCycleError`. Failed builders propagate their
exception and never return an earlier invalid value.

The mutation scope invalidates even when its body raises. It does not roll back
source data: the owner must validate or recover that data before resuming a
failed simulation operation. Guard scopes are not thread synchronization.

## Composing cached facts

An outer cache declares the root sources of everything it reads:

```python
edge_count = CachedValue(
    "route edge count",
    dependencies=edges.dependencies,
    build=lambda: len(edges.get()),
)
```

For several inputs, declare their combined root sources; duplicates are removed
by `CachedValue`. An undeclared nested source raises
`UndeclaredDependencyError`, even if the nested read hits its saved value.
Direct reads through `RevisionSource.stamp()` enforce the same rule.

These checks do not observe arbitrary Python assignments or in-place edits to
an ordinary list. Every relevant mutation still needs an owning revision scope.
Builders should return tuples, frozen records with immutable contents, or
read-only mappings. Reusing a mutable source object as a result can expose later
unpublished changes.

`clear()` releases one cached result and preserves its counters. `info()` returns
immutable hit, successful-build, and failed-build counts. Keep per-vehicle
caches with the vehicle's lifetime; release them when the vehicle is removed.

## Current integration

`traffic_network_cache.JunctionLookup` retains the city junction-ID mapping.
It rebuilds when the city object changes or the existing
`CityMap.mobility_revision` changes. Its mapping is read-only; the intersection
objects remain owned by the city. Topology edits must publish the normal city
revision through the existing network rebuild methods.

`RoadVehicleSimulation.active_junctions()` and source pruning use this mapping
in both update modes. The regression test measures 40 complete intersection
iterations before the change versus 1 after it over 20 unchanged ticks. Map
replacement, network rebuilds, and source-selection order have regression tests.

## Applying this to more systems

The [migration design](superpowers/specs/2026-10-18-incremental-simulation-cache-design.md)
describes the implemented route, roster, and occupancy boundaries and the
remaining coordinator work. The cache primitives retain metadata; domain owners
maintain collection indexes through explicit changes.

## Retained route and roster data

`traffic_route_state.RouteState` retains movement ranges, incoming lane and
signal boundaries, and separate route/control/roundabout cursors. Claims are
checked live, including every visit to a repeated merge connection. Replacing
the immutable movement or section tuple resets the facts and cursors.

Retained route-fact reads still check their source stamp, so composition cannot
bypass dependency declarations or read a source during mutation. Construction
and route replacement publish route revisions at the owner boundary; an outer
cache invalidates before any inner helper needs to run. Replacement checks the
route write guard before changing live fields or releasing claims. Facts build
lazily after that publication. Final movement choices also depend on progress
and claims, so a route-only dependency cannot validate those choices across ticks.

`RouteGeometry` retains polyline rulers and advances a local segment cursor.
At a rounded corner it uses the original subtraction rule over the retained
rulers to preserve the vehicle's heading. Rewinds use indexed lookup.

Source selections, spawn timers, the ID-sorted observation roster, vehicle-ID
lookup, and generated-vehicle count persist between structural changes. Random
destination shuffles still happen in their original order at scheduled attempts.

The public `cars`, `vehicles`, and `active_junction_ids` sequences are read-only
live views. Use `admit_route`, `remove_vehicle`, `clear_vehicles`,
`clear_test_traffic`, and `toggle_junction` to change their contents. For setup:

```python
traffic.place_vehicle(car.id, 120.0)
traffic.resize_vehicle(car.id, length=40.0, width=8.0)
traffic.replace_vehicle_route(car.id, route, distance=0.0)
traffic.reorder_vehicles(car.id for car in reversed(traffic.cars))
```

Placement, resizing, and route replacement publish affected occupancy directly.
`car.place(distance)` or the compatibility `car.advance(0)` queues a placement
for publication before the next update or admission. An explicit roster reorder
is a setup/recovery event and rebuilds occupancy to replace equal-position ties.
Direct field assignments are not a substitute for these owner methods.

## Incremental occupancy publication

`TrafficOccupancyIndex.publish_changes(changed_cars, removed=removed_cars)`
updates only the supplied vehicles. Ordinary movement retains entry objects and
updates captured coordinates and lengths. Section/cell boundaries update local
membership; adjacent inversions are repaired before new entries are inserted by
binary search. An exceptional large reorder can sort its affected lane.

Data-first mode publishes after the entire movement batch. Legacy mode publishes
after each accepted vehicle's movement, preserving its sequential decisions.
Admission inserts each accepted car before checking the next candidate. No
ordinary tick calls the full-roster `rebuild()` method.

Queries reject partially published or failed snapshots. A failed publication
requires `rebuild(current_cars)` before another query. Published vehicle lengths
remain fixed along with positions until publication. The longest-length bound is
maintained on admission, removal, and resize events rather than scanned each tick.

Dynamic gaps, speeds, and traffic decisions must read current published
kinematics. A cache for those values needs the appropriate pose/claim inputs or
a bounded snapshot epoch; a topology revision alone cannot validate them.

The remaining design work is finer intersection-local claim/arrival invalidation;
this migration retains the existing coordinator rules and epoch-scoped merge
observations. It does not cache final brain decisions across ticks.

Run the tests with:

```sh
python -m unittest discover -s tests -p test_simulation_cache.py -v
python -m unittest discover -s tests -p test_traffic_network_cache.py -v
python -m unittest discover -s tests -q
```
