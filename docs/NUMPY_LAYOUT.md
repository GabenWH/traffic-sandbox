# Numeric runtime storage

Regular simulation data uses numeric NumPy buffers. Names and object identities
stay in lookup tables at the boundary; numeric arrays never use `dtype=object`.
The existing resident, trip, editor and JSON save interfaces remain available.

| Component | Retained layout |
| --- | --- |
| Residents | Int64 IDs, int32 label codes and byte flags in parallel columns |
| Scheduled events | Numeric times, sequences, kind codes, payloads and heap indices |
| Compiled mobility graphs | CSR offsets, numeric destinations and costs, edge lookup table |
| Node positions | Float64 coordinate matrix indexed by node ID |
| Road/lane/connector/footprint geometry | Immutable float64 point buffers |
| Walking-route legs | One point buffer, offsets and kind codes per cached route |
| Vehicle geometry rulers | Float64 segment records and cumulative endpoints |
| Background routing snapshots | Numeric source/destination IDs and weight vectors |

## IDs and views

`ResidentTable.codes` maps labels to integer codes. `labels` maps codes back to
their original strings or `None`. Resident views read and write these columns,
so a caller holding `person` sees later updates to the same resident.

```python
person.state = 'work'                  # compatible view API
states = runtime.residents.columns['state']  # an int32 NumPy view
work_code = runtime.residents.codes['work']
at_work = states == work_code
```

Rows are stable and freed rows can be reused. Capacity grows geometrically.
Reacquire raw column views after inserting residents: growth can replace a
backing allocation. Updating a column's integer codes requires maintaining the
same gameplay/event invariants as the ordinary property API.

## Geometry and graphs

Point sequences provide ordinary tuple-valued reads, slicing, equality and
iteration. Slices share a read-only allocation. Compiled geometry is replaced
by normal road/editor rebuilds. Cached lengths use the original `math.dist`
operation order; the storage conversion does not change geometric precision.

Compiled graphs retain no per-edge `Transition` objects or per-node adjacency
lists. The graph API reconstructs temporary transitions when requested. Explicit
graph edits thaw a mutable graph; the next city rebuild packs its replacement.
Source snapshots and native traffic data stay independent of those edits.

Native bindings can pass contiguous NumPy coordinate and weight buffers through
the existing ctypes ABI. Buffers stay alive for each call; native constructors
copy the data they retain. No C++ source is added by this storage conversion.

## Events and irregular data

Event cancellation removes the heap entry immediately and releases its key and
payload references. Common payloads (resident IDs, pairs of integers, labels and
`None`) are encoded in numeric columns. Rare heterogeneous service payloads use
a side table whose entry is removed on cancellation/completion.

Inventories, named domain objects and sparse relationships still use ordinary
Python mappings. Wrapping such objects in NumPy object arrays would retain their
Python object graphs and would not provide the intended GC reduction.

## Verification

```bash
PYTHONPATH=.:tests python -m unittest \
  test_numpy_layout test_resident_arrays test_trip_retention \
  test_traffic_route_state test_mobility test_native_walking_routing \
  test_commute_routing test_native_routing test_city_gameplay test_city_recovery
```

Compare the same seeded Arcata scenario before/after, including population,
commute counts, food balance, normal tick timings, natural GC callbacks and live
data bytes. Include NumPy base allocations when counting memory: an array view's
own size excludes its shared backing allocation. Process peak RSS also includes
imports, temporary setup allocations and allocator high-water marks.
