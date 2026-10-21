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
defines the remaining route, roster, claims, and occupancy changes. Route
metadata can reuse the same cache primitives. Occupancy needs direct add/remove
and movement-delta updates to its retained index; wrapping a whole-index rebuild
in a cache would still do that work whenever positions change.

Dynamic gaps, speeds, and traffic decisions must read current published
kinematics. A cache for those values needs the appropriate pose/claim inputs or
a bounded snapshot epoch; a topology revision alone cannot validate them.

Run the tests with:

```sh
python -m unittest discover -s tests -p test_simulation_cache.py -v
python -m unittest discover -s tests -p test_traffic_network_cache.py -v
python -m unittest discover -s tests -q
```
