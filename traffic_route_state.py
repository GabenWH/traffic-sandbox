"""Retained route facts and local progress cursors for city road vehicles."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import dist
from types import MappingProxyType

from models import ManeuverType
from simulation_cache import CachedValue, RevisionSource


def _range_key(movement):
    return movement[0], movement[1], id(movement[2])


@dataclass(frozen=True)
class _RouteFacts:
    movements: tuple
    starts: tuple
    ends: tuple
    controls: tuple
    control_ends: tuple
    roundabouts: tuple
    roundabout_ends: tuple
    incoming: object
    signal_starts: object
    by_connection: object


class RouteState:
    def __init__(self):
        self._movements = self._segments = None
        self._revision = RevisionSource("vehicle route facts")
        self._facts = CachedValue("route facts", dependencies=(self._revision,),
                                  build=self._build)
        self._current_facts = None
        self._cursors = {}

    def sync(self, movements, segments):
        if movements is not self._movements or segments is not self._segments:
            with self._revision.mutate():
                self._movements, self._segments = movements, segments
                self._cursors.clear()
                self._current_facts = None

    def _read_facts(self):
        # sync() owns the only inputs. Check their identities once there, then
        # reuse the immutable published facts throughout the unchanged route.
        # A retained read must still enforce mutation and composed-cache guards.
        self._revision.stamp()
        if self._current_facts is None:
            self._current_facts = self._facts.get()
        return self._current_facts

    def _build(self):
        movements = self._movements
        controls = tuple(m for m in movements if m[2].roundabout_role != "exit"
                         and m[2].maneuver.kind is not ManeuverType.U_TURN)
        roundabouts = tuple(m for m in movements if m[2].roundabout_role)
        incoming_sections = tuple(s for s in self._segments
                                  if s[2][0] in ("lane", "road_port"))
        lane_sections = tuple(s for s in self._segments if s[2][0] == "lane")
        incoming_ends = tuple(s[1] for s in incoming_sections)
        lane_ends = tuple(s[1] for s in lane_sections)
        incoming, signals, by_connection = {}, {}, {}
        for movement in movements:
            start, _end, connection = movement
            by_connection.setdefault(id(connection), []).append(movement)
            index = bisect_right(incoming_ends, start - connection.control_offset + 1e-8) - 1
            incoming[_range_key(movement)] = (
                incoming_sections[index][2] if index >= 0
                else ("road_output", connection.source_output.id)
            )
            index = bisect_right(lane_ends, start + 1e-8) - 1
            signals[_range_key(movement)] = lane_sections[index][0] if index >= 0 else None
        return _RouteFacts(
            movements, tuple(m[0] for m in movements), tuple(m[1] for m in movements),
            controls, tuple(m[1] for m in controls),
            roundabouts, tuple(m[1] for m in roundabouts),
            MappingProxyType(incoming), MappingProxyType(signals),
            MappingProxyType({key: tuple(value) for key, value in by_connection.items()}),
        )

    def _cursor(self, name, ends, distance):
        previous = self._cursors.get(name)
        if previous is None or distance < previous[1]:
            index = bisect_right(ends, distance)
        else:
            index = previous[0]
            while index < len(ends) and ends[index] <= distance:
                index += 1
        self._cursors[name] = index, distance
        return index

    def next_route(self, distance):
        facts = self._read_facts()
        index = self._cursor("route", facts.ends, distance)
        return facts.movements[index] if index < len(facts.movements) else None

    def next_controlled(self, distance, length, has_claim):
        facts = self._read_facts()
        index = self._cursor("control", facts.control_ends, distance - length / 2)
        for i in range(index, len(facts.controls)):
            movement = facts.controls[i]
            if not (has_claim(movement[2]) and distance + length / 2 >= movement[0]):
                return movement
        return None

    def next_roundabout(self, rear):
        facts = self._read_facts()
        index = self._cursor("roundabout", facts.roundabout_ends, rear)
        return facts.roundabouts[index] if index < len(facts.roundabouts) else None

    def incoming(self, movement):
        return self._read_facts().incoming[_range_key(movement)]

    def signal_start(self, movement):
        return self._read_facts().signal_starts.get(_range_key(movement))

    def following(self, movement):
        facts = self._read_facts()
        first = bisect_left(facts.starts, movement[1])
        for index in range(first, len(facts.movements)):
            yield facts.movements[index]

    def claimed_ranges(self, connections):
        """Retain every visit to a claimed connection, including loop routes."""
        facts = self._read_facts()
        for connection in connections:
            yield from facts.by_connection.get(id(connection), ())


class RouteGeometry:
    """Keep segment rulers so motion does not walk the completed polyline."""

    def __init__(self):
        self._points = None
        self._segments = self._ends = ()
        self._index = 0
        self._last_distance = None

    def position_and_heading(self, points, distance_along):
        if points is not self._points:
            segments, ends, total = [], [], 0.0
            for start, end in zip(points, points[1:]):
                length = dist(start, end)
                if not length:
                    continue
                heading = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
                segments.append((start, heading, length, total, end))
                total += length
                ends.append(total)
            self._points, self._segments, self._ends = points, tuple(segments), tuple(ends)
            self._last_distance = None
        distance = max(0.0, float(distance_along))
        if not self._segments:
            return points[-1], (1.0, 0.0)
        if self._last_distance is None or distance < self._last_distance:
            self._index = bisect_left(self._ends, distance)
        else:
            while self._index < len(self._ends) and self._ends[self._index] < distance:
                self._index += 1
        self._last_distance = distance
        # Prefix addition and the reference's repeated subtraction can disagree
        # about the segment at a rounded corner. Preserve that boundary choice;
        # ordinary motion still reads only the retained local segment.
        for boundary in (self._index - 1, self._index):
            if 0 <= boundary < len(self._ends) and abs(distance - self._ends[boundary]) <= 1e-8:
                return self._boundary_position(distance, points)
        if self._index == len(self._segments):
            return points[-1], self._segments[-1][1]
        start, heading, _length, offset, _end = self._segments[self._index]
        remaining = distance - offset
        return ((start[0] + heading[0] * remaining, start[1] + heading[1] * remaining),
                heading)

    def _boundary_position(self, remaining, points):
        for start, heading, length, _offset, end in self._segments:
            if remaining <= length:
                fraction = remaining / length
                return ((start[0] + (end[0] - start[0]) * fraction,
                         start[1] + (end[1] - start[1]) * fraction), heading)
            remaining -= length
        return points[-1], self._segments[-1][1]
