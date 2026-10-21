"""Derived topology data retained until its owning map is rebuilt."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from simulation_cache import CachedValue, RevisionSource

if TYPE_CHECKING:
    from city import CityMap
    from models import Intersection


class JunctionLookup:
    """Adapt the map's existing topology revision to a read-only ID lookup.

    Intersection objects are owned by the city; this protects the lookup's
    membership, not every field of its values. Topology edits must publish the
    normal ``mobility_revision`` before the next lookup. Holding the current
    map itself distinguishes map replacement without relying on a raw id().
    """

    def __init__(self) -> None:
        self._city: CityMap | None = None
        self._revision: int | None = None
        self._topology = RevisionSource("junction topology")
        self._lookup: CachedValue[Mapping[str, Intersection]] = CachedValue(
            "junction lookup", dependencies=(self._topology,), build=self._build,
        )

    def get(self, city_map: CityMap) -> Mapping[str, Intersection]:
        revision = city_map.mobility_revision
        if self._city is not city_map or self._revision != revision:
            with self._topology.mutate():
                self._city, self._revision = city_map, revision
        return self._lookup.get()

    def _build(self) -> Mapping[str, Intersection]:
        assert self._city is not None
        return MappingProxyType({item.id: item for item in self._city.intersections})
