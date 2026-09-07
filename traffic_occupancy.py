"""Linear-time spatial occupancy bins for routed traffic."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import floor
from typing import Hashable, Protocol


OCCUPANCY_CELL_LENGTH = 32.0
SECTION_CLEARANCE = 22.0


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
        # Also remember cars whose rear still occupies the previous section.
        # A car must not disappear from its follower's view at a lane boundary.
        # Keep a short clearance shadow on the section it just left. At a fork,
        # the two branches are still physically close for a few feet: a driver
        # taking the exit must not clip a queued car continuing past that exit.
        self._sections = defaultdict(list)
        for car in cars:
            segments = getattr(car, "route_segments", ())
            if segments:
                for start, end, key, offset in segments:
                    if start <= car.distance + car.length / 2 and end >= car.distance - car.length / 2 - SECTION_CLEARANCE:
                        self._sections[key].append(OccupancyEntry(car, offset + car.distance - start))
            else:
                occupancy = car.occupancy_position()
                if occupancy is not None:
                    self._sections[occupancy[0]].append(OccupancyEntry(car, occupancy[1]))

    def _same_link_gap(self, car: OccupancyCar, lookahead: float) -> float | None:
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


    def gap_from(self, car: OccupancyCar, distance: float, lookahead: float) -> float | None:
        """Measure bumper clearance forward from a point on this car's route.

        Each shared section has its own distance ruler. Convert other cars onto
        our route's ruler before comparing them. This works through corners,
        lane boundaries and a ring made from several ordinary lane sections.
        """
        nearest = None
        for start, end, key, offset in car.route_segments:
            if end < distance - car.length / 2 or start > distance + lookahead:
                continue
            for entry in getattr(self, "_sections", {}).get(key, ()):
                if entry.car is car:
                    continue
                center = start + entry.position - offset
                if center < distance:
                    continue
                gap = center - distance - (entry.car.length + car.length) / 2
                if gap <= lookahead and (nearest is None or gap < nearest):
                    nearest = gap
        return nearest

    def lead_gap(self, car: OccupancyCar, lookahead: float) -> float | None:
        """Look along connected route sections, not just the current section."""
        if getattr(car, "route_segments", ()):
            return self.gap_from(car, car.distance, lookahead)
        return self._same_link_gap(car, lookahead)
