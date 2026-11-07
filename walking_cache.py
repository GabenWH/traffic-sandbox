"""Bounded query paths and compact exact keys for native pedestrian geometry."""
from array import array
from collections import OrderedDict
from collections.abc import MutableMapping
from itertools import chain
import sys


class WalkingRouteCache(MutableMapping):
    """LRU bounds both route count and retained point/link references.

    Eviction only drops a cache reference. An active passenger can continue to
    own its route, and the native engine already owns registered walking lanes.
    A route larger than the geometry budget is returned by its caller uncached.
    """
    def __init__(self, max_entries=512, max_units=65536):
        for value in (max_entries, max_units):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('Walking cache limits must be nonnegative integers')
        self.max_entries, self.max_units = max_entries, max_units
        self._rows = OrderedDict()
        self.units = self.evictions = 0

    def __len__(self):
        return len(self._rows)

    def __iter__(self):
        # Mapping views may read values through __getitem__, updating recency.
        # Iteration is an explicit snapshot operation, outside route-hit work.
        return iter(tuple(self._rows))

    def __contains__(self, key):
        return key in self._rows

    def __getitem__(self, key):
        value, _ = self._rows[key]
        self._rows.move_to_end(key)
        return value

    def __setitem__(self, key, route):
        if key in self._rows:
            del self[key]
        units = (len(route.points) + len(route.links)
                 + sum(len(link.points) for link in route.links)) if route is not None else 1
        if not self.max_entries or units > self.max_units:
            return
        while self._rows and (len(self._rows) >= self.max_entries
                              or self.units + units > self.max_units):
            _, (_, old_units) = self._rows.popitem(last=False)
            self.units -= old_units
            self.evictions += 1
        self._rows[key] = route, units
        self.units += units

    def __delitem__(self, key):
        _, units = self._rows.pop(key)
        self.units -= units

    def clear(self):
        self._rows.clear()
        self.units = 0


def walking_geometry_key(points, crossing):
    """Exact float geometry in an untracked byte buffer, with no hash collision."""
    values = array('d', chain.from_iterable(points))
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tobytes(), crossing


def walking_geometry_points(key):
    values = array('d')
    values.frombytes(key[0])
    if sys.byteorder != 'little':
        values.byteswap()
    return tuple(zip(values[::2], values[1::2]))
