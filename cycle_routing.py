"""Explicit cycle access on an immutable snapshot of pedestrian geometry.

Endpoints are named lane ends, not arbitrary map points. Nothing snaps across
an inaccessible boundary. Neither approving an edge nor compiling a router
modifies the walking layer or the vehicle graph.
"""
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from numbers import Real

from native_routing import NativeCycleGraph
from pathfinding import Path
from pedestrian_mobility import pedestrian_lane_node as cycle_endpoint


def _positive_width(width):
    return isinstance(width, Real) and not isinstance(width, bool) and isfinite(width) and width > 0


@dataclass(frozen=True)
class CycleAccess:
    """Directed permission; cargo also needs a known usable (not nominal) width."""
    bicycle: bool = False
    cargo: bool = False
    clear_width_ft: float | None = None

    def __post_init__(self):
        if not isinstance(self.bicycle, bool) or not isinstance(self.cargo, bool):
            raise ValueError('Cycle permissions must be boolean')
        if self.clear_width_ft is not None and not _positive_width(self.clear_width_ft):
            raise ValueError('Known clear width must be finite and positive, in feet')


class CycleRouter:
    def __init__(self, layer, center_path_widths, permissions, *, cargo_clearance_ft):
        if not _positive_width(cargo_clearance_ft):
            raise ValueError('Cargo clearance must be finite and positive, in feet')
        # Resolve only explicitly requested edges. Reject ambiguous parallel
        # edges rather than authorizing multiple movements with one approval.
        requested = dict(permissions)
        found = {}
        for source in dict.fromkeys(a for a, _ in requested):
            for transition in layer.graph.transitions_from(source):
                key = source, transition.destination
                if key in requested:
                    if key in found:
                        raise ValueError(f'Ambiguous pedestrian edge: {key}')
                    found[key] = transition
        missing = requested.keys() - found.keys()
        if missing:
            raise ValueError(f'Unknown pedestrian edge: {next(iter(missing))}')

        self._nodes = tuple(dict.fromkeys(node for pair in found for node in pair))
        self._ids = {node: i for i, node in enumerate(self._nodes)}
        self._links = tuple(t.edge for t in found.values())
        self._targets = tuple(b for _, b in found)
        rows = []
        for (a, b), transition in found.items():
            access = requested[a, b]
            if not isinstance(access, CycleAccess):
                raise ValueError('Expected a CycleAccess permission for each edge')
            flags = int(access.bicycle) | (int(access.cargo) << 1)
            # For standalone paths the authored physical width caps both
            # travel and its junction approaches. A road's carriageway width
            # is NOT the usable width of its sidewalk.
            width = min(access.clear_width_ft or 0.0,
                        center_path_widths.get(a[1], float('inf')),
                        center_path_widths.get(b[1], float('inf')))
            rows.append(((self._ids[a], self._ids[b], transition.cost), flags, width))
        graphs = tuple(NativeCycleGraph(len(self._nodes), rows, cargo=mode, clearance_ft=cargo_clearance_ft)
                       for mode in (False, True)) if rows else ()
        # Bound snapshot-local trees by count and a ~16 MiB target (16 B/node).
        limit = min(64, (16 * 1024**2) // max(1, 16 * len(self._nodes)))
        @lru_cache(maxsize=limit)
        def tree(cargo, target):
            return graphs[cargo].tree(((target, 0.),))
        self._tree = tree

    def route(self, start, destination, *, cargo=False):
        """Return a directed Path of existing WalkLinks, or None for no ride."""
        if not isinstance(cargo, bool):
            raise ValueError('cargo must be boolean')
        if start == destination or start not in self._ids or destination not in self._ids:
            return None
        path = self._tree(cargo, self._ids[destination]).path(((self._ids[start], 0.),))
        if path is None:
            return None
        _, _, edges, cost = path
        return Path((start, *(self._targets[i] for i in edges)),
                    tuple(self._links[i] for i in edges), cost)
