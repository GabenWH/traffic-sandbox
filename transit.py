"""Connected fixed-line bus service over road and pedestrian mobility layers.

Native traffic moves active buses and walkers. This event coordinator handles
service, capacity and passenger transitions. Bays are assumed off the road;
walking estimates use the current inferred pedestrian network. Shared-stop
transfers use an expected-time routing graph. No live delay prediction,
mid-trip fleet save/load or idling fuel are modeled yet.
"""
from collections import deque
from dataclasses import dataclass, field
from math import dist, isfinite

from mobility import LanePosition, vehicle_route_points
from models import polyline_length
from traffic_testbed import RoadVehicleSimulation


def _positive(value, name, zero=False):
    if isinstance(value, bool) or not isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f'{name} must be finite and {"nonnegative" if zero else "positive"}')


@dataclass(frozen=True)
class BusStop:
    id: str
    road_position: LanePosition
    walk_point: tuple[float, float]


@dataclass(frozen=True)
class BusLine:
    id: str
    stop_ids: tuple[str, ...]
    headway_seconds: float = 300.0
    dwell_seconds: float = 10.0
    boarding_seconds: float = 2.0
    alighting_seconds: float = 1.0
    speed_mph: float = 25.0


@dataclass
class Bus:
    id: str
    line_id: str
    capacity: int = 60
    fuel_liters: float = 100.0
    liters_per_mile: float = .45
    service_at: float = 0.0
    service_until: float = float("inf")
    length: float = 35.0
    width: float = 8.0
    phase: str = field(default='docked', init=False)
    stop_index: int = field(default=0, init=False)
    passengers: list[int] = field(default_factory=list, init=False)
    distance_feet: float = field(default=0.0, init=False)
    ready_at: float = field(default=0.0, init=False)
    position: tuple = field(default=(0, 0), init=False)
    _car: object = field(default=None, init=False, repr=False)
    _last_distance: float = field(default=0.0, init=False, repr=False)


@dataclass
class Passenger:
    id: int
    origin: tuple
    destination: tuple
    phase: str = 'planned'
    line_id: str | None = None
    board_stop: str | None = None
    alight_stop: str | None = None
    bus_id: str | None = None
    final_walk: object = None
    arrived_at: float | None = None
    itinerary: list = field(default_factory=list)
    leg_index: int = 0


class TransitSimulation:
    """Own one shared traffic clock; call update here rather than on traffic.

    A supplied traffic simulation must be synchronized to this city's current
    network before service starts. Road edits invalidate this service; rebuilding
    routes and migrating active passengers is deliberately not implicit.
    """
    def __init__(self, city, traffic=None):
        self.city = city
        self.traffic = traffic or RoadVehicleSimulation(update_mode='cpp', spawn_interval=10000)
        self.traffic.sync_network(city)
        self.engine = self.traffic._native_backend(city).engine
        self.revision = city.mobility_revision
        self.time = self.traffic.elapsed_time
        self.stops, self.lines, self.buses, self.people = {}, {}, {}, {}
        self.legs, self.leg_lengths, self.queues = {}, {}, {}
        self._next_departure = {}
        self.events = []
        self._walk_routes = {}
        self._walk_cache = {}
        self.vehicle_arrivals = deque()
        self.person_arrivals = deque()

    def _check_network(self):
        if self.city.mobility_revision != self.revision:
            raise RuntimeError('Road network changed; rebuild transit service before advancing')
        if self.traffic._native_backend(self.city).engine is not self.engine:
            raise RuntimeError('Native engine was replaced; transit must be rebuilt')

    def _event(self, event, **data):
        self.events.append(dict(time=round(self.time, 4), event=event, **data))

    def add_stop(self, stop):
        if not stop.id or stop.id in self.stops:
            raise ValueError('Stop IDs must be unique and nonempty')
        if not any(stop.road_position.lane is l for r in self.city.roads for l in r.lanes):
            raise ValueError('A bus stop needs a current vehicle lane in this city')
        if len(stop.walk_point) != 2 or not all(isfinite(x) for x in stop.walk_point):
            raise ValueError('Stop walking point must be finite')
        self.stops[stop.id] = stop

    def add_line(self, line):
        if not line.id or line.id in self.lines or len(line.stop_ids) < 2:
            raise ValueError('A line needs a unique ID and at least two stops')
        if len(set(line.stop_ids)) != len(line.stop_ids):
            raise ValueError('Stop IDs in a line must be distinct')
        for key in ('headway_seconds', 'speed_mph'):
            _positive(getattr(line, key), key)
        for key in ('dwell_seconds', 'boarding_seconds', 'alighting_seconds'):
            _positive(getattr(line, key), key, zero=True)
        routes, lengths = [], []
        for a, b in zip(line.stop_ids, (*line.stop_ids[1:], line.stop_ids[0])):
            if a not in self.stops or b not in self.stops:
                raise ValueError('Line refers to an unknown stop')
            route = self.city.find_vehicle_route_between(self.stops[a].road_position,
                                                         self.stops[b].road_position)
            if route is None:
                raise ValueError(f'No vehicle route between bus stops {a} and {b}')
            length = polyline_length(list(vehicle_route_points(route)))
            if length <= 0:
                raise ValueError('Bus legs must have positive length')
            routes.append(route)
            lengths.append(length)
        self.lines[line.id] = line
        self._next_departure[line.id] = self.time
        self.legs[line.id], self.leg_lengths[line.id] = routes, lengths
        for stop in line.stop_ids:
            self.queues[(line.id, stop)] = deque()

    def add_bus(self, bus):
        if not bus.id or bus.id in self.buses or bus.line_id not in self.lines:
            raise ValueError('Bus needs a unique ID and a known line')
        if isinstance(bus.capacity, bool) or not isinstance(bus.capacity, int) or bus.capacity < 1:
            raise ValueError('Bus capacity must be a positive integer')
        if any(car.id == bus.id for car in self.traffic.cars):
            raise ValueError('Bus ID already belongs to an active road vehicle')
        if bus.passengers or bus._car is not None or bus.stop_index != 0:
            raise ValueError('Add an unused bus at the first stop')
        for key in ('fuel_liters', 'service_at'):
            _positive(getattr(bus, key), key, zero=True)
        for key in ('liters_per_mile', 'length', 'width'):
            _positive(getattr(bus, key), key)
        line = self.lines[bus.line_id]
        bus.ready_at = max(self.time, bus.service_at) + line.dwell_seconds
        bus.position = self.stops[line.stop_ids[0]].road_position.point
        self.buses[bus.id] = bus

    def _walk(self, a, b):
        if dist(a, b) < 1e-7:
            return None
        key = (tuple(a), tuple(b))
        if key not in self._walk_cache:
            self._walk_cache[key] = self.city.find_pedestrian_route(a, b)
        return self._walk_cache[key]

    def request_trip(self, person_id, origin, destination, *, allow_bus=True):
        self._check_network()
        if isinstance(person_id, bool) or not isinstance(person_id, int) or person_id < 0 or person_id > 2147483647:
            raise ValueError('Passenger ID must be a nonnegative native integer')
        previous = self.people.get(person_id)
        if previous is not None and (previous.phase != 'arrived' or tuple(origin) != previous.destination):
            raise ValueError('An existing passenger must finish before departing from that destination')
        if any(len(p) != 2 or not all(isfinite(v) for v in p) for p in (origin, destination)):
            raise ValueError('Trip points must be finite 2D positions')
        from pathfinding import DirectedGraph
        graph=DirectedGraph()
        start,goal=('journey','origin'),('journey','destination')
        graph.add_node(start);graph.add_node(goal)
        try:
            direct=self._walk(origin,destination)
            graph.add_edge(start,goal,direct.length/4.4 if direct else 0,('direct',direct))
        except ValueError:
            pass
        if allow_bus:
            served=set()
            for line in self.lines.values():
                if not any(b.line_id==line.id and b.service_until>self.time and b.fuel_liters>0 for b in self.buses.values()):
                    continue
                for i,stop in enumerate(line.stop_ids):
                    off=('stop',stop);on=('ride',line.id,stop)
                    served.add(stop)
                    graph.add_edge(off,on,line.headway_seconds/2,('board',(line.id,stop)))
                    graph.add_edge(on,off,0,('alight',stop))
                    nxt=line.stop_ids[(i+1)%len(line.stop_ids)]
                    graph.add_edge(on,('ride',line.id,nxt),self.leg_lengths[line.id][i]/(line.speed_mph*22/15)+line.dwell_seconds,('ride',None))
            for stop in served:
                try:
                    first=self._walk(origin,self.stops[stop].walk_point)
                    graph.add_edge(start,('stop',stop),first.length/4.4 if first else 0,('first',first))
                except ValueError:
                    pass
                try:
                    last=self._walk(self.stops[stop].walk_point,destination)
                    graph.add_edge(('stop',stop),goal,last.length/4.4 if last else 0,('last',last))
                except ValueError:
                    pass
        path=graph.find_path(start,goal)
        if path is None:
            raise ValueError('No walking or transit journey')
        legs=[];first=last=None;boarding=None
        for kind,value in path.edges:
            if kind in ('first','direct'):first=value
            elif kind=='last':last=value
            elif kind=='board':boarding=value
            elif kind=='alight' and boarding is not None:
                legs.append(dict(line=boarding[0],board=boarding[1],alight=value))
                boarding=None
        person = previous or Passenger(person_id, tuple(origin), tuple(destination))
        person.origin, person.destination = tuple(origin), tuple(destination)
        person.phase, person.arrived_at = 'planned', None
        person.line_id = person.board_stop = person.alight_stop = person.bus_id = person.final_walk = None
        person.itinerary,person.leg_index=legs,0
        person.final_walk=last
        if legs:
            person.line_id,person.board_stop,person.alight_stop=legs[0]['line'],legs[0]['board'],legs[0]['alight']
        self.people[person.id] = person
        self._start_walk(person, first, 'walking_to_stop' if legs else 'walking_direct')
        return person

    def _start_walk(self, person, route, phase):
        person.phase = phase
        if route is None:
            self._finish_walk(person)
            return
        key = (route.points, route.first_crossing_fraction)
        if key not in self._walk_routes:
            self._walk_routes[key] = self.engine.register_pedestrian_lane(*key)
        self.engine.spawn_pedestrian(person.id, self._walk_routes[key], 4.4)

    def _finish_walk(self, person):
        if person.phase == 'walking_to_stop':
            person.phase = 'waiting'
            self.queues[(person.line_id, person.board_stop)].append(person.id)
            self._event('wait', person=person.id, stop=person.board_stop)
        else:
            person.phase, person.arrived_at = 'arrived', self.time
            self._event('arrive', person=person.id)
            self.person_arrivals.append(person.id)

    def _dock(self, bus):
        line = self.lines[bus.line_id]
        stop = line.stop_ids[bus.stop_index]
        alighting = [p for p in bus.passengers if self.people[p].alight_stop == stop]
        for person_id in alighting:
            bus.passengers.remove(person_id)
            person = self.people[person_id]
            person.bus_id = None
            self._event('alight', person=person_id, bus=bus.id, stop=stop)
            person.leg_index+=1
            if person.leg_index<len(person.itinerary):
                leg=person.itinerary[person.leg_index]
                person.line_id,person.board_stop,person.alight_stop=leg['line'],leg['board'],leg['alight']
                self._event('transfer',person=person.id,stop=stop,line=person.line_id)
                self._start_walk(person,None,'walking_to_stop')
            else:
                self._start_walk(person, person.final_walk, 'walking_from_stop')
        bus.phase = 'docked'
        bus.service_at = self.time
        bus.ready_at = self.time + line.dwell_seconds + len(alighting)*line.alighting_seconds
        bus.position = self.stops[stop].road_position.point
        self._event('dock', bus=bus.id, stop=stop)

    def _service(self, bus):
        if bus.phase != 'docked' or self.time < bus.service_at or self.time >= bus.service_until:
            return
        line = self.lines[bus.line_id]
        stop = line.stop_ids[bus.stop_index]
        queue = self.queues[(bus.line_id, stop)]
        while queue and len(bus.passengers) < bus.capacity:
            person = self.people[queue.popleft()]
            person.phase, person.bus_id = 'riding', bus.id
            bus.passengers.append(person.id)
            bus.ready_at = max(bus.ready_at, self.time) + line.boarding_seconds
            self._event('board', person=person.id, bus=bus.id, stop=stop)
        if self.time + 1e-8 < bus.ready_at:
            return
        if bus.stop_index == 0 and self.time + 1e-8 < self._next_departure[bus.line_id]:
            return
        needed = self.leg_lengths[bus.line_id][bus.stop_index] / 5280 * bus.liters_per_mile
        if bus.fuel_liters + 1e-9 < needed:
            bus.phase = 'out_of_fuel'
            self._event('out_of_fuel', bus=bus.id, stop=stop)
            return
        destination = line.stop_ids[(bus.stop_index+1) % len(line.stop_ids)]
        car = self.traffic.admit_route(self.legs[bus.line_id][bus.stop_index],
                                      vehicle_id=bus.id, source_id=stop, destination_id=destination,
                                      source_type='bus', length=bus.length, width=bus.width,
                                      speed_cap_mph=None, color='#e3a82f')
        if car is not None:
            if bus.stop_index == 0:
                self._next_departure[bus.line_id] = self.time + line.headway_seconds
            bus._car, bus._last_distance, bus.phase = car, 0.0, 'driving'
            self._event('depart', bus=bus.id, stop=stop, passengers=len(bus.passengers))

    def update(self, seconds):
        _positive(seconds, 'Time', zero=True)
        self._check_network()
        if abs(self.traffic.elapsed_time - self.time) > 1e-7:
            raise RuntimeError('Advance shared traffic only through TransitSimulation.update')
        remaining = seconds
        while remaining > 1e-9:
            for bus in self.buses.values():
                self._service(bus)
            # With no moving actors or generated traffic, advance to the next
            # bus service event without Python per-tick work during the night.
            if not self.traffic.cars and not self.traffic.active_junction_ids and not self.engine.pedestrian_states():
                deadlines = [max(b.service_at, b.ready_at,
                                 self._next_departure[b.line_id] if b.stop_index == 0 else self.time)
                             for b in self.buses.values() if b.phase == 'docked' and self.time < b.service_until]
                deadline = min(deadlines, default=float('inf'))
                skip = min(remaining, deadline-self.time)
                if skip > .05:
                    self.time += skip
                    self.traffic.elapsed_time = self.time
                    self.engine._call('nt_clock', self.time, 0.0, 0.0)
                    remaining -= skip
                    continue
            dt = min(.05, remaining)
            arrivals = self.traffic.update(self.city, dt)
            completed = {car.id for car in arrivals}
            self.vehicle_arrivals.extend(car for car in arrivals if car.id not in self.buses)
            self.time = self.traffic.elapsed_time
            for row in self.engine.completed_pedestrians():
                if row.id in self.people:
                    self._finish_walk(self.people[row.id])
            for bus in self.buses.values():
                if bus.phase != 'driving':
                    continue
                distance = bus._car.distance - bus._last_distance
                bus.distance_feet += max(0, distance)
                bus.fuel_liters = max(0, bus.fuel_liters - max(0, distance)/5280*bus.liters_per_mile)
                bus._last_distance = bus._car.distance
                bus.position = bus._car.position
                if bus.id in completed:
                    bus._car = None
                    bus.stop_index = (bus.stop_index+1) % len(self.lines[bus.line_id].stop_ids)
                    self._dock(bus)
            remaining -= dt
