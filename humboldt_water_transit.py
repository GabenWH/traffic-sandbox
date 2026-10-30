"""Event-based Humboldt Bay water + bus transit network experiment.

This is a standalone, geographic network-level scenario model. It deliberately
is not a native-vehicle extension of transit.TransitSimulation: vessel geometry,
bathymetry, real timetables, pedestrian access, and dock siting are not known.
No tick-wise passenger scanning: timetables, demand and capacity reservations
are handled on each passenger's departure event.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from heapq import heappop, heappush
from math import ceil, isfinite
from random import Random


@dataclass(frozen=True)
class Terminal:
    id: str
    name: str
    lat: float
    lon: float
    kind: str = 'interchange'


@dataclass(frozen=True)
class Line:
    id: str
    start: str
    end: str
    mode: str
    miles: float
    speed_mph: float
    headway_min: float
    seats: int
    kwh_per_mile: float
    dwell_min: float = 3.0
    sensitive: bool = False
    experimental: bool = False

    @property
    def travel_min(self):
        return 60.0 * self.miles / self.speed_mph

    @property
    def round_trip_min(self):
        return 2 * (self.travel_min + self.dwell_min)

    @property
    def required_vehicles(self):
        return ceil(self.round_trip_min / self.headway_min)


TERMINALS = (
    Terminal('arcata', 'Arcata', 40.8572, -124.1160, 'shallow'),
    Terminal('samoa', 'Samoa', 40.8160, -124.1895, 'water'),
    Terminal('eureka', 'Eureka', 40.8021, -124.1697, 'hub'),
    Terminal('king', 'King Salmon', 40.7521, -124.2070, 'water'),
    Terminal('fields', 'Fields Landing', 40.7250, -124.2175, 'water'),
    Terminal('fortuna', 'Fortuna', 40.5982, -124.1572, 'bus'),
    Terminal('ferndale', 'Ferndale', 40.5762, -124.2639, 'bus'),
)

# Illustrative route distances and technical assumptions. They are NOT
# navigation charts, permitted corridors, certified range, or energy measurements.
LINES = (
    Line('F1', 'samoa', 'eureka', 'ferry', 2.0, 19, 15, 40, 9),
    Line('F2', 'eureka', 'king', 'ferry', 5.2, 19, 30, 40, 9),
    Line('F3', 'king', 'fields', 'ferry', 2.5, 19, 30, 40, 9),
    Line('F4', 'eureka', 'fields', 'ferry', 7.0, 19, 30, 40, 9),
    Line('H1', 'arcata', 'eureka', 'hovercraft', 5.6, 30, 20, 18, 13, sensitive=True),
    Line('H2', 'arcata', 'samoa', 'hovercraft', 5.0, 30, 30, 18, 13, sensitive=True),
    Line('B1', 'fields', 'fortuna', 'bus', 13.5, 29, 30, 40, 2),
    Line('B2', 'fortuna', 'ferndale', 'bus', 7.5, 25, 30, 40, 2),
    Line('B3', 'arcata', 'eureka', 'bus', 9.5, 29, 20, 40, 2),
    Line('B4', 'samoa', 'arcata', 'bus', 8.4, 25, 30, 40, 2),
    Line('B5', 'eureka', 'fortuna', 'bus', 18.0, 29, 30, 40, 2),
    # A Ferndale hovercraft route is intentionally excluded: land, estuary,
    # wildlife and seasonal navigation feasibility have not been established.
)

WEIGHTS = {'arcata': 22, 'samoa': 8, 'eureka': 30, 'king': 7,
           'fields': 6, 'fortuna': 19, 'ferndale': 8}


@dataclass(frozen=True)
class Configuration:
    daily_trips: int = 2000
    fleet: str = 'mixed'  # mixed / ferry / hovercraft / bus
    sea_rise_ft: float = 0.0
    sensitive_exclusion: bool = False
    road_closure: bool = False
    hardened_terminals: bool = True
    headway_scale: float = 1.0
    seed: int = 7
    service_hours: float = 12.0

    def __post_init__(self):
        if self.fleet not in ('mixed', 'ferry', 'hovercraft', 'bus'):
            raise ValueError('Unknown fleet strategy')
        if not isinstance(self.daily_trips, int) or isinstance(self.daily_trips, bool) or self.daily_trips < 0:
            raise ValueError('daily_trips must be a nonnegative integer')
        if not isfinite(self.sea_rise_ft) or self.sea_rise_ft < 0:
            raise ValueError('sea_rise_ft must be nonnegative and finite')
        if not isfinite(self.headway_scale) or self.headway_scale <= 0:
            raise ValueError('headway_scale must be positive and finite')
        if not isfinite(self.service_hours) or self.service_hours <= 0:
            raise ValueError('service_hours must be positive and finite')


def enabled_lines(config: Configuration):
    lines = []
    for line in LINES:
        if config.fleet == 'bus' and line.mode != 'bus':
            continue
        if config.fleet == 'ferry' and line.mode == 'hovercraft':
            continue
        if config.fleet == 'hovercraft' and line.mode == 'ferry':
            continue
        if config.sensitive_exclusion and line.sensitive:
            continue
        # Illustrative road-failure experiment, not a prediction of closures.
        if config.road_closure and line.id in ('B1', 'B3', 'B5'):
            continue
        # Unprotected shoreline stops are assumed offline in the +6ft stress
        # test only. This is a policy switch, not a predicted flood threshold.
        if config.sea_rise_ft >= 6 and not config.hardened_terminals and \
                (line.start in ('king', 'fields') or line.end in ('king', 'fields')):
            continue
        lines.append(line)
    return tuple(lines)


class Network:
    def __init__(self, config: Configuration):
        self.config = config
        self.lines = enabled_lines(config)
        self.adj = {t.id: [] for t in TERMINALS}
        self.departures = {}  # (line id, start): scheduled minute stamps
        self.reserved = Counter()
        self.boarded = Counter()
        self.ridden_miles = Counter()
        self.fleet = Counter()
        self.energy_kwh = Counter()
        self.vehicle_miles = Counter()
        self._build()

    def _build(self):
        horizon = self.config.service_hours * 60
        for line in self.lines:
            if line.miles <= 0 or line.speed_mph <= 0 or line.headway_min <= 0 or line.seats < 1:
                raise ValueError('Invalid line parameters')
            headway = line.headway_min * self.config.headway_scale
            self.fleet[line.mode] += ceil(line.round_trip_min / headway)
            for origin, destination in ((line.start, line.end), (line.end, line.start)):
                self.adj[origin].append((destination, line))
                # Half-headway phase staggering for each direction.
                offset = 0 if origin == line.start else headway / 2
                times = tuple(offset + i * headway for i in range(ceil(horizon / headway) + 1)
                              if offset + i * headway < horizon)
                self.departures[(line.id, origin)] = times
                self.vehicle_miles[line.mode] += len(times) * line.miles
                self.energy_kwh[line.mode] += len(times) * line.miles * line.kwh_per_mile

    def plan(self, origin, destination, leave_min, reserve=False):
        """Earliest arrival with scheduled departures and reserved seat counts."""
        if origin not in self.adj or destination not in self.adj:
            raise KeyError('Unknown terminal')
        if origin == destination:
            return (leave_min, [])
        heap = [(leave_min, 0, origin)]
        best = {origin: leave_min}
        paths = {origin: []}
        serial = 0
        while heap:
            at, _, place = heappop(heap)
            if at > best[place] + 1e-8:
                continue
            if place == destination:
                if reserve:
                    for leg in paths[place]:
                        self.reserved[(leg['line'], leg['origin'], leg['departure'])] += 1
                        self.boarded[leg['mode']] += 1
                        self.ridden_miles[leg['mode']] += leg['miles']
                return at, paths[place]
            for next_place, line in self.adj[place]:
                times = self.departures[(line.id, place)]
                # Two-minute transfer time after arrival, except before first leg.
                earliest = at + (2 if paths[place] else 0)
                j = bisect_left(times, earliest - 1e-8)
                while j < len(times) and self.reserved[(line.id, place, times[j])] >= line.seats:
                    j += 1
                if j == len(times):
                    continue
                depart = times[j]
                arrive = depart + line.travel_min
                if arrive + 1e-8 < best.get(next_place, float('inf')):
                    leg = {'line': line.id, 'mode': line.mode, 'origin': place,
                           'destination': next_place, 'departure': depart,
                           'arrival': arrive, 'miles': line.miles}
                    best[next_place] = arrive
                    paths[next_place] = paths[place] + [leg]
                    serial += 1
                    heappush(heap, (arrive, serial, next_place))
        return (None, [])


def simulate(config: Configuration):
    network = Network(config)
    rng = Random(config.seed)
    places = list(WEIGHTS)
    weights = list(WEIGHTS.values())
    requests = []
    for person in range(config.daily_trips):
        a = rng.choices(places, weights)[0]
        b = rng.choices(places, weights)[0]
        if a == b:
            b = places[(places.index(a) + 1 + rng.randrange(len(places)-1)) % len(places)]
        requests.append((rng.random() * config.service_hours * 60, person, a, b))
    requests.sort()
    successful = []
    stranded = Counter()
    od = Counter()
    example = {}
    for time, pid, a, b in requests:
        arrive, path = network.plan(a, b, time, reserve=True)
        if arrive is None:
            stranded[(a, b)] += 1
            continue
        duration = arrive - time + 10 # 5 min terminal access at each end (assumption)
        successful.append(duration)
        od[(a, b)] += 1
        if (a,b) not in example:
            example[(a,b)] = {'minutes': round(duration, 1), 'legs': path}
    return {'scenario': 'Illustrative network experiment, not surveyed routes',
            'requested': config.daily_trips, 'served': len(successful),
            'unserved': sum(stranded.values()),
            'mean_door_to_door_min': round(sum(successful)/len(successful),1) if successful else None,
            'p90_door_to_door_min': round(sorted(successful)[min(len(successful)-1, int(.9*len(successful)))],1) if successful else None,
            'fleet': dict(network.fleet),
            'vehicle_miles': {k: round(v,1) for k,v in network.vehicle_miles.items()},
            'energy_kwh': {k: round(v,1) for k,v in network.energy_kwh.items()},
            'passenger_boardings': dict(network.boarded),
            'passenger_miles': {k: round(v,1) for k,v in network.ridden_miles.items()},
            'stranded_by_od': [{'origin':a,'destination':b,'count':n} for (a,b),n in stranded.most_common()],
            'lines': [l.id for l in network.lines],
            'examples': example,
            'limitations': [
                'Illustrative distances, frequency, speed, costs and passenger demand',
                'No measured bathymetry, docks, tides, wetlands constraints or navigable corridor validation',
                'No integration into C++ vehicle positions or existing CityMap',
                'Only fixed daily departure schedules and static mean per-mile energy',
                'Five-minute access at each endpoint is an assumed constant',
                'Flooded road and terminal exclusions are hypothetical stress scenarios',
            ]}