"""Persistent, position-ordered occupancy for routed traffic."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from math import floor
from operator import attrgetter
from time import perf_counter
from typing import Hashable, Protocol


OCCUPANCY_CELL_LENGTH = 32.0
SECTION_CLEARANCE = 22.0


class OccupancyCar(Protocol):
    id: str
    length: float

    def occupancy_position(self) -> tuple[Hashable, float] | None: ...


@dataclass(eq=False)
class OccupancyEntry:
    car: OccupancyCar
    position: float
    order: int = 0
    lane_index: int = 0


@dataclass
class _CarOccupancy:
    car: OccupancyCar
    segments: tuple
    starts: tuple = field(init=False)
    ends: tuple = field(init=False)
    first: int = 0
    stop: int = 0
    low: float = float("inf")
    high: float = float("inf")
    members: dict[int, tuple[Hashable, OccupancyEntry]] = field(default_factory=dict)
    bin_key: tuple | None = None
    bin_entry: OccupancyEntry | None = None
    movements: object = None
    movement_ranges: dict = field(default_factory=dict)
    claim: object = None
    target: object = None
    shadow_index: int | None = None
    entry_start: float = 0.0

    def __post_init__(self):
        self.starts = tuple(segment[0] for segment in self.segments)
        self.ends = tuple(segment[1] for segment in self.segments)

    def advance_window(self):
        low = self.car.distance - self.car.length / 2 - SECTION_CLEARANCE
        high = self.car.distance + self.car.length / 2
        if low < self.low or high < self.high:
            # Initialization, rewinding, or a changed vehicle footprint.
            self.first = bisect_left(self.ends, low)
            self.stop = bisect_right(self.starts, high)
        else:
            while self.first < len(self.ends) and self.ends[self.first] < low:
                self.first += 1
            while self.stop < len(self.starts) and self.starts[self.stop] <= high:
                self.stop += 1
        self.low, self.high = low, high

    def merge_shadow(self):
        claim = getattr(self.car, "claimed_movement", None)
        target = getattr(claim, "merge_target", None)
        movements = getattr(self.car, "controlled_movements", ())
        if claim is not self.claim or target != self.target or movements is not self.movements:
            if movements is not self.movements:
                self.movement_ranges = {}
                for start, end, connection in movements:
                    self.movement_ranges.setdefault(id(connection), (start, end))
                self.movements = movements
            self.claim, self.target = claim, target
            self.shadow_index = None
            entry = self.movement_ranges.get(id(claim)) if target is not None else None
            if entry is not None:
                self.entry_start = entry[0]
                candidate = bisect_left(self.starts, entry[1] - 1e-8)
                while candidate < len(self.starts) and abs(self.starts[candidate] - entry[1]) < 1e-8:
                    if self.segments[candidate][2] == target:
                        self.shadow_index = candidate
                        break
                    candidate += 1
        if self.shadow_index is not None:
            start = self.starts[self.shadow_index]
            if self.high >= self.entry_start and start - SECTION_CLEARANCE <= self.high < start:
                return self.shadow_index
        return None


@dataclass
class TrafficOccupancyIndex:
    """Retain lane entries and update membership only at section/cell boundaries."""

    cell_length: float = OCCUPANCY_CELL_LENGTH
    profile_internal_timings: bool = False
    last_rebuild_timings_ms: dict[str, float] = field(
        default_factory=dict, init=False, repr=False,
    )
    _bins: dict[tuple[Hashable, int], list[OccupancyEntry]] = field(
        default_factory=dict, init=False, repr=False,
    )
    _sections: dict[Hashable, list[OccupancyEntry]] = field(
        default_factory=dict, init=False, repr=False,
    )
    _cars: dict[int, _CarOccupancy] = field(default_factory=dict, init=False, repr=False)
    _max_car_length: float = field(default=0.0, init=False, repr=False)

    def rebuild(self, cars: list[OccupancyCar]) -> None:
        """Synchronize the retained index with one completed position snapshot.

        Keep the historical method name for callers that publish a new frame.
        Entries contain captured positions, never live reads of moving cars.
        """
        profile_internal = self.profile_internal_timings
        timings = {}
        dirty = set()
        phase_started = perf_counter() if profile_internal else 0.0
        present = {id(car) for car in cars}
        self._max_car_length = max((car.length for car in cars), default=0.0)
        for identity in self._cars.keys() - present:
            self._discard(self._cars.pop(identity), dirty)
        states = []
        for car in cars:
            identity = id(car)
            segments = getattr(car, "route_segments", ())
            state = self._cars.get(identity)
            if state is None or state.segments is not segments:
                if state is not None:
                    self._discard(state, dirty)
                state = _CarOccupancy(car, segments)
                self._cars[identity] = state
            states.append(state)
        if profile_internal:
            timings["occupancy_finalize"] = (perf_counter() - phase_started) * 1000
        phase_started = perf_counter() if profile_internal else 0.0
        occupancies = [car.occupancy_position() for car in cars]
        if profile_internal:
            timings["occupancy_position_lookup"] = (perf_counter() - phase_started) * 1000
        phase_started = perf_counter() if profile_internal else 0.0
        for state, occupancy in zip(states, occupancies):
            key = None if occupancy is None else (occupancy[0], floor(occupancy[1] / self.cell_length))
            if key != state.bin_key:
                self._remove_bin(state)
                if key is not None:
                    state.bin_key = key
                    state.bin_entry = OccupancyEntry(state.car, occupancy[1])
                    self._bins.setdefault(key, []).append(state.bin_entry)
            elif key is not None:
                state.bin_entry.position = occupancy[1]
        if profile_internal:
            timings["occupancy_bin_build"] = (perf_counter() - phase_started) * 1000
        phase_started = perf_counter() if profile_internal else 0.0
        for order, (state, occupancy) in enumerate(zip(states, occupancies)):
            if not state.segments:
                previous = state.members.get(-1)
                if previous is not None and (occupancy is None or previous[0] != occupancy[0]):
                    self._remove_member(state, -1, dirty)
                if occupancy is not None:
                    self._put_member(state, -1, occupancy[0], occupancy[1], order, dirty)
                continue
            state.advance_window()
            shadow = state.merge_shadow()
            for segment in tuple(state.members):
                if not state.first <= segment < state.stop and segment != shadow:
                    self._remove_member(state, segment, dirty)
            for segment in range(state.first, state.stop):
                start, _, key, offset = state.segments[segment]
                self._put_member(state, segment, key, offset + state.car.distance - start, order, dirty)
            if shadow is not None:
                start, _, key, offset = state.segments[shadow]
                self._put_member(state, shadow, key, offset + state.car.distance - start, order, dirty)
        for key in dirty:
            entries = self._sections.get(key)
            if entries:
                # TimSort is linear when cars retain their relative lane order.
                entries.sort(key=lambda entry: (entry.position, entry.order))
                for lane_index, entry in enumerate(entries):
                    entry.lane_index = lane_index
        if profile_internal:
            timings["occupancy_section_mapping"] = (perf_counter() - phase_started) * 1000
            self.last_rebuild_timings_ms = timings
        else:
            self.last_rebuild_timings_ms.clear()

    def _remove_bin(self, state):
        if state.bin_key is not None:
            entries = self._bins[state.bin_key]
            entries.remove(state.bin_entry)
            if not entries:
                del self._bins[state.bin_key]
            state.bin_key = state.bin_entry = None

    def _remove_member(self, state, segment, dirty):
        key, entry = state.members.pop(segment)
        entries = self._sections[key]
        entries.remove(entry)
        if not entries:
            del self._sections[key]
        dirty.add(key)

    def _discard(self, state, dirty):
        self._remove_bin(state)
        for segment in tuple(state.members):
            self._remove_member(state, segment, dirty)

    def _put_member(self, state, segment, key, position, order, dirty):
        member = state.members.get(segment)
        if member is None:
            entry = OccupancyEntry(state.car, position, order)
            state.members[segment] = (key, entry)
            self._sections.setdefault(key, []).append(entry)
            dirty.add(key)
        else:
            entry = member[1]
            if entry.position != position or entry.order != order:
                entry.position, entry.order = position, order
                dirty.add(key)

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
        result = self.lead_from(car, distance, lookahead)
        return result[1] if result is not None else None

    def lead_from(
        self, car: OccupancyCar, distance: float, lookahead: float,
    ) -> tuple[OccupancyCar, float] | None:
        """Return the nearest forward car and its bumper clearance."""
        nearest: tuple[OccupancyCar, float] | None = None
        segments = car.route_segments
        state = self._cars.get(id(car))
        if state is not None and state.segments is not segments:
            state = None
        first = 0
        if state is not None and state.segments is segments:
            low = distance - car.length / 2
            first = state.first
            if low < state.low:
                first = bisect_left(state.ends, low)
            else:
                while first < len(state.ends) and state.ends[first] < low:
                    first += 1
        for segment in range(first, len(segments)):
            start, end, key, offset = segments[segment]
            if start > distance + lookahead:
                break
            if end < distance - car.length / 2 or start > distance + lookahead:
                continue
            entries = self._sections.get(key, ())
            local_position = offset + distance - start
            # Coordinate conversion may round at a lane boundary. Include a
            # conservative candidate margin, then apply the original center
            # comparison below to decide whether a vehicle is actually ahead.
            candidate_position = local_position - 1e-8
            own = state.members.get(segment) if state is not None else None
            if own is not None and own[1].position == local_position:
                lane_index = own[1].lane_index
                while lane_index > 0 and entries[lane_index - 1].position >= candidate_position:
                    lane_index -= 1
            else:
                lane_index = bisect_left(entries, candidate_position, key=attrgetter("position"))
            local_nearest = None
            local_order = None
            for entry_index in range(lane_index, len(entries)):
                entry = entries[entry_index]
                center = start + entry.position - offset
                # Centers are ordered, but longer vehicles can have a closer
                # rear bumper than the next center. Stop only when even the
                # longest vehicle cannot improve the current gap.
                best_gap = lookahead if local_nearest is None else local_nearest[1]
                if center - distance - (self._max_car_length + car.length) / 2 > best_gap:
                    break
                if entry.car is car:
                    continue
                if center < distance:
                    continue
                gap = center - distance - (entry.car.length + car.length) / 2
                if gap <= lookahead and (local_nearest is None or gap < local_nearest[1]
                                        or (gap == local_nearest[1] and entry.order < local_order)):
                    local_nearest = (entry.car, gap)
                    local_order = entry.order
            if local_nearest is not None and (nearest is None or local_nearest[1] < nearest[1]):
                nearest = local_nearest
        return nearest

    def lead_gap(self, car: OccupancyCar, lookahead: float) -> float | None:
        """Look along connected route sections, not just the current section."""
        if getattr(car, "route_segments", ()):
            return self.gap_from(car, car.distance, lookahead)
        return self._same_link_gap(car, lookahead)

    def lead_car_gap(
        self, car: OccupancyCar, lookahead: float,
    ) -> tuple[OccupancyCar, float] | None:
        """Return the nearest lead vehicle when route-section data is available."""
        if getattr(car, "route_segments", ()):
            return self.lead_from(car, car.distance, lookahead)
        return None
