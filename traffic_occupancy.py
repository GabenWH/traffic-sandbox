"""Persistent, position-ordered occupancy for routed traffic."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, deque
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
    lane_index: int = -1
    length: float = 0.0


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
    order: int = 0
    distance: float | None = None
    length: float = 0.0
    published_movements: object = None
    published_claim: object = None
    published_target: object = None

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
    _length_counts: Counter = field(default_factory=Counter, init=False, repr=False)
    _next_order: int = field(default=0, init=False, repr=False)
    _publishing: bool = field(default=False, init=False, repr=False)
    _valid: bool = field(default=True, init=False, repr=False)

    def rebuild(self, cars: list[OccupancyCar]) -> None:
        """Fully synchronize membership; also recover a failed publication.

        Normal movement uses publish_changes(), which never scans this roster.
        """
        self._publish(cars, (), complete=True)

    def publish_changes(self, cars, *, removed=()) -> None:
        """Publish changed/admitted cars and explicit removals as one snapshot.

        Call after the entire movement batch. Unmentioned vehicles retain their
        captured coordinates. A failed publication requires a full rebuild.
        """
        self._publish(cars, removed, complete=False)

    def is_current(self, car) -> bool:
        state = self._cars.get(id(car))
        claim = getattr(car, "claimed_movement", None)
        return (self._valid and state is not None
                and state.segments is getattr(car, "route_segments", ())
                and state.distance == getattr(car, "distance", None)
                and state.length == car.length
                and state.published_movements is getattr(car, "controlled_movements", ())
                and state.published_claim is claim
                and state.published_target == getattr(claim, "merge_target", None))

    def _require_snapshot(self):
        if self._publishing or not self._valid:
            raise RuntimeError("Occupancy snapshot is unavailable; finish publication or rebuild")

    def _publish(self, cars, removed, *, complete):
        if self._publishing:
            raise RuntimeError("Occupancy snapshot publication is already in progress")
        if not complete:
            self._require_snapshot()
        elif not self._valid:
            self._cars.clear()
            self._sections.clear()
            self._bins.clear()
            self._length_counts.clear()
            self._max_car_length = 0.0
            self._next_order = 0
        self._publishing = True
        self._valid = False
        try:
            self._update(cars, removed, complete=complete)
            self._valid = True
        finally:
            self._publishing = False

    def _update(self, cars, removed, *, complete):
        profile_internal = self.profile_internal_timings
        timings = {}
        dirty = {}
        phase_started = perf_counter() if profile_internal else 0.0
        if complete:
            present = {id(car) for car in cars}
            removed = [self._cars[identity].car for identity in self._cars.keys() - present]
        lengths_changed = False
        for car in removed:
            state = self._cars.pop(id(car), None)
            if state is not None:
                self._discard(state, dirty)
                self._remove_length(state.length)
                lengths_changed = True
        states = []
        seen = set()
        for order, car in enumerate(cars):
            identity = id(car)
            if identity in seen:
                continue
            seen.add(identity)
            segments = getattr(car, "route_segments", ())
            state = self._cars.get(identity)
            if state is None or state.segments is not segments:
                admission_order = self._next_order if state is None else state.order
                if state is not None:
                    self._discard(state, dirty)
                    self._remove_length(state.length)
                else:
                    self._next_order += 1
                state = _CarOccupancy(car, segments, order=admission_order)
                self._cars[identity] = state
            if complete:
                state.order = order
                self._next_order = max(self._next_order, order + 1)
            if state.length != car.length:
                if state.length:
                    self._remove_length(state.length)
                state.length = car.length
                self._length_counts[car.length] += 1
                lengths_changed = True
            states.append(state)
        if lengths_changed:
            self._max_car_length = max(self._length_counts, default=0.0)
        if profile_internal:
            timings["occupancy_finalize"] = (perf_counter() - phase_started) * 1000
        phase_started = perf_counter() if profile_internal else 0.0
        occupancies = [state.car.occupancy_position() for state in states]
        if profile_internal:
            timings["occupancy_position_lookup"] = (perf_counter() - phase_started) * 1000
        phase_started = perf_counter() if profile_internal else 0.0
        for state, occupancy in zip(states, occupancies):
            key = None if occupancy is None else (occupancy[0], floor(occupancy[1] / self.cell_length))
            if key != state.bin_key:
                self._remove_bin(state)
                if key is not None:
                    state.bin_key = key
                    state.bin_entry = OccupancyEntry(state.car, occupancy[1], length=state.length)
                    self._bins.setdefault(key, []).append(state.bin_entry)
            elif key is not None:
                state.bin_entry.position = occupancy[1]
                state.bin_entry.length = state.length
        if profile_internal:
            timings["occupancy_bin_build"] = (perf_counter() - phase_started) * 1000
        phase_started = perf_counter() if profile_internal else 0.0
        for state, occupancy in zip(states, occupancies):
            state.distance = getattr(state.car, "distance", None)
            state.published_movements = getattr(state.car, "controlled_movements", ())
            state.published_claim = getattr(state.car, "claimed_movement", None)
            state.published_target = getattr(state.published_claim, "merge_target", None)
            order = state.order
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
        self._order_lanes(dirty, complete=complete)
        if profile_internal:
            timings["occupancy_section_mapping"] = (perf_counter() - phase_started) * 1000
            self.last_rebuild_timings_ms = timings
        else:
            self.last_rebuild_timings_ms.clear()

    def _remove_length(self, length):
        self._length_counts[length] -= 1
        if not self._length_counts[length]:
            del self._length_counts[length]

    def _order_lanes(self, dirty, *, complete):
        for key, changed in dirty.items():
            entries = self._sections.setdefault(key, [])
            additions = [entry for entry in changed if entry.lane_index == -1]
            if complete:
                entries.extend(additions)
                self._sort_lane(entries)
                if not entries:
                    del self._sections[key]
                continue
            # All coordinates have landed. Repair only adjacent edges touched
            # by changed entries; propagate inversions until order is restored.
            edges = set()
            for entry in changed:
                if entry.lane_index >= 0:
                    edges.update((entry.lane_index - 1, entry.lane_index))
            pending = deque(edges)
            swaps = 0
            while pending:
                edge = pending.popleft()
                edges.discard(edge)
                if not 0 <= edge < len(entries) - 1:
                    continue
                left, right = entries[edge:edge + 2]
                if (left.position, left.order) <= (right.position, right.order):
                    continue
                entries[edge], entries[edge + 1] = right, left
                right.lane_index, left.lane_index = edge, edge + 1
                swaps += 1
                if swaps > 2 * len(entries):
                    # Large teleports/reversals are exceptional; bound repairs.
                    self._sort_lane(entries)
                    break
                for neighbor in (edge - 1, edge + 1):
                    if neighbor not in edges:
                        edges.add(neighbor)
                        pending.append(neighbor)
            # Bisect only after retained entries have their final sorted order.
            for entry in additions:
                index = bisect_right(entries, (entry.position, entry.order),
                                     key=lambda item: (item.position, item.order))
                entries.insert(index, entry)
                for lane_index in range(index, len(entries)):
                    entries[lane_index].lane_index = lane_index
            if not entries:
                del self._sections[key]

    @staticmethod
    def _sort_lane(entries):
        entries.sort(key=lambda entry: (entry.position, entry.order))
        for lane_index, entry in enumerate(entries):
            entry.lane_index = lane_index

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
        entries.pop(entry.lane_index)
        for index in range(entry.lane_index, len(entries)):
            entries[index].lane_index = index
        entry.lane_index = -2
        if not entries:
            del self._sections[key]
        dirty.setdefault(key, set()).discard(entry)

    def _discard(self, state, dirty):
        self._remove_bin(state)
        for segment in tuple(state.members):
            self._remove_member(state, segment, dirty)

    def _put_member(self, state, segment, key, position, order, dirty):
        member = state.members.get(segment)
        if member is None:
            entry = OccupancyEntry(state.car, position, order, length=state.length)
            state.members[segment] = (key, entry)
            dirty.setdefault(key, set()).add(entry)
        else:
            entry = member[1]
            entry.length = state.length
            if entry.position != position or entry.order != order:
                entry.position, entry.order = position, order
                dirty.setdefault(key, set()).add(entry)

    def _same_link_gap(self, car: OccupancyCar, lookahead: float) -> float | None:
        """Return nearest forward bumper gap on the car's current link."""
        occupancy = car.occupancy_position()
        if occupancy is None:
            return None
        key, position = occupancy
        state = self._cars.get(id(car))
        car_length = state.length if state is not None else car.length
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
                    - entry.length / 2
                    - car_length / 2
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
        self._require_snapshot()
        nearest: tuple[OccupancyCar, float] | None = None
        segments = car.route_segments
        state = self._cars.get(id(car))
        if state is not None and state.segments is not segments:
            state = None
        car_length = state.length if state is not None else car.length
        first = 0
        if state is not None and state.segments is segments:
            low = distance - car_length / 2
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
            if end < distance - car_length / 2 or start > distance + lookahead:
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
                if center - distance - (self._max_car_length + car_length) / 2 > best_gap:
                    break
                if entry.car is car:
                    continue
                if center < distance:
                    continue
                gap = center - distance - (entry.length + car_length) / 2
                if gap <= lookahead and (local_nearest is None or gap < local_nearest[1]
                                        or (gap == local_nearest[1] and entry.order < local_order)):
                    local_nearest = (entry.car, gap)
                    local_order = entry.order
            if local_nearest is not None and (nearest is None or local_nearest[1] < nearest[1]):
                nearest = local_nearest
        return nearest

    def lead_gap(self, car: OccupancyCar, lookahead: float) -> float | None:
        """Look along connected route sections, not just the current section."""
        self._require_snapshot()
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
