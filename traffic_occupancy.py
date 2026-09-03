"""Linear-time spatial occupancy bins for routed traffic."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import floor
from typing import Hashable, Protocol


OCCUPANCY_CELL_LENGTH = 32.0


class OccupancyCar(Protocol):
    id: str
    length: float

    def occupancy_position(self) -> tuple[Hashable, float] | None: ...


@dataclass(frozen=True)
class OccupancyEntry:
    car: OccupancyCar
    position: float


@dataclass
class TrafficOccupancyIndex:
    """Bin cars by mobility link and longitudinal cell without sorting."""

    cell_length: float = OCCUPANCY_CELL_LENGTH
    _bins: dict[tuple[Hashable, int], list[OccupancyEntry]] = field(
        default_factory=dict, init=False, repr=False,
    )

    def rebuild(self, cars: list[OccupancyCar]) -> None:
        bins: defaultdict[tuple[Hashable, int], list[OccupancyEntry]] = defaultdict(list)
        for car in cars:
            occupancy = car.occupancy_position()
            if occupancy is None:
                continue
            key, position = occupancy
            bins[(key, floor(position / self.cell_length))].append(
                OccupancyEntry(car, position),
            )
        self._bins = dict(bins)

    def lead_gap(self, car: OccupancyCar, lookahead: float) -> float | None:
        """Return nearest forward bumper gap on the car's current link."""
        occupancy = car.occupancy_position()
        if occupancy is None:
            return None
        key, position = occupancy
        first_cell = floor(position / self.cell_length)
        final_cell = floor((position + max(0.0, lookahead)) / self.cell_length)
        nearest: float | None = None
        for cell in range(first_cell, final_cell + 1):
            for entry in self._bins.get((key, cell), ()):
                if entry.car is car or entry.position < position:
                    continue
                gap = (
                    entry.position
                    - position
                    - entry.car.length / 2
                    - car.length / 2
                )
                if nearest is None or gap < nearest:
                    nearest = gap
        return nearest

