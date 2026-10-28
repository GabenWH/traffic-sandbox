"""Integrated synthetic town: native transport, persistent people/fleet and food.

This is a one-day integration experiment, not a calibrated survival model.
Economy/dispatch is event-sampled every five seconds. Active movement is native.
"""
import copy
import heapq
from collections import Counter, deque
from dataclasses import asdict, dataclass
from math import isfinite

from city import Building, CityMap, Parcel, Terrain
from mobility import lane_position_at_distance
from persistence import world_to_dict, world_from_dict
from persistent_fleet import FleetVehicle, PersistentFleet
from transit import Bus, BusLine, BusStop, TransitSimulation


@dataclass
class Resident:
    id: int
    home: str
    worker: bool
    mode: str = 'walk'
    state: str = 'home'
    car_id: str | None = None
    return_due: bool = False
    workplace: str = "work"


class TownSimulation:
    def __init__(self, city, sites, residents, *, work_start=27000, work_end=57600):
        self.city, self.sites = city, sites
        self.residents = {p.id:p for p in residents}
        self.transit = TransitSimulation(city)
        self.fleet = PersistentFleet(self.transit, sites)
        self.work_start, self.work_end = work_start, work_end
        self.events = []
        self.jobs, self.handling = {}, {sid:deque() for sid in sites}
        self.bay_active = {}
        self.produced = self.consumed = self.unmet = self.fuel_used = 0.0
        self.deliveries = self.workers_arrived = 0
        self.initial_resources = sum(sum(s['building'].inventory.amounts.values()) for s in sites.values())
        self.initial_fuel = 0.0
        self.time = 0.0
        self._events = []
        self._sequence = 0
        for p in residents:
            if p.worker:
                self.schedule(work_start + (p.id % 20)*2, 'leave', p.id)
        self.schedule(work_end, 'return', None)
        self.schedule(max(0, work_end-600), 'bus_open', None)
        self.schedule(work_start+7200, 'bus_close', None)
        self.schedule(work_end+7200, 'bus_close', None)

    def schedule(self, when, kind, value):
        self._sequence += 1
        heapq.heappush(self._events, (when, self._sequence, kind, value))

    def _note(self, event, **values):
        self.events.append(dict(time=self.time, event=event, **values))

    def _depart(self, person, returning=False):
        source, target = (person.workplace, person.home) if returning else (person.home, person.workplace)
        if person.mode == 'car':
            if self.fleet.dispatch(person.car_id, target):
                person.state = 'returning' if returning else 'commuting'
                return True
            return False
        self.transit.request_trip(person.id, self.sites[source]['walk_point'],
                                  self.sites[target]['walk_point'], allow_bus=person.mode == 'bus')
        person.state = 'returning' if returning else 'commuting'
        return True

    def _process_events(self):
        while self._events and self._events[0][0] <= self.time+1e-7:
            _,_,kind,value = heapq.heappop(self._events)
            if kind in ('leave','retry_return'):
                p = self.residents[value]
                if not self._depart(p, returning=kind == 'retry_return'):
                    self.schedule(self.time+5, kind, value)
            elif kind == 'return':
                for p in self.residents.values():
                    if not p.worker:
                        continue
                    p.return_due = True
                    if p.state == 'work' and not self._depart(p, returning=True):
                        self.schedule(self.time+5, 'retry_return', p.id)
            elif kind == 'bus_close':
                for b in self.transit.buses.values():
                    b.service_until = self.time
            elif kind == 'bus_open':
                for b in self.transit.buses.values():
                    b.service_at = self.time
                    b.service_until = self.work_end+7200
                    b.ready_at = self.time+10

    def _arrive_person(self, p):
        if p.state == 'commuting':
            p.state = 'work'
            self.workers_arrived += 1
            self._note('worker_arrive', person=p.id)
            if p.return_due:
                if not self._depart(p, returning=True):
                    self.schedule(self.time+5, 'retry_return', p.id)
        elif p.state == 'returning':
            p.state = 'home'
            self._note('home_arrive', person=p.id)

    def _economy(self, dt):
        staff = sum(p.state == 'work' for p in self.residents.values())
        stock = self.sites['work']['building'].inventory.amounts
        made = min(stock.get('grain', 0), staff*6*dt/3600)
        stock['grain'] = stock.get('grain', 0)-made
        stock['food'] = stock.get('food', 0)+made
        self.produced += made
        for sid,s in self.sites.items():
            if not sid.startswith('home-'):
                continue
            inv = s['building'].inventory.amounts
            wanted = s['building'].residents*3*dt/86400
            used = min(inv.get('food', 0), wanted)
            inv['food'] = inv.get('food', 0)-used
            self.consumed += used
            self.unmet += wanted-used

    def _logistics(self):
        # Finish one resource-specific operation per bay before admitting FIFO.
        for site, (vid, finish, operation) in list(self.bay_active.items()):
            if finish > self.time+1e-8:
                continue
            v = self.fleet.vehicles[vid]
            v.phase = 'parked'
            job = self.jobs[vid]
            if operation == 'load':
                job['stage'] = 'outbound'
            else:
                inv = self.sites[site]['building'].inventory.amounts
                inv['food'] = inv.get('food', 0)+v.cargo.pop('food',0)
                self.deliveries += 1
                job['stage'] = 'return'
                self._note('unload', vehicle=vid, site=site)
            del self.bay_active[site]
        for site, queue in self.handling.items():
            if queue and site not in self.bay_active:
                vid,operation = queue.popleft()
                v = self.fleet.vehicles[vid]
                v.phase = 'handling'
                # Cargo-dependent rate belongs to the vehicle/material, not site.
                rate = 10.0
                self.bay_active[site] = (vid, self.time+5+sum(v.cargo.values())/rate, operation)
        for vid,job in list(self.jobs.items()):
            v = self.fleet.vehicles[vid]
            if v.phase != 'parked':
                continue
            if job['stage'] == 'outbound':
                self.fleet.dispatch(vid, job['destination'])
            elif job['stage'] == 'return':
                self.fleet.dispatch(vid, 'work')
        outstanding = {j['destination'] for j in self.jobs.values()}
        for v in self.fleet.vehicles.values():
            if v.kind != 'truck' or v.phase != 'parked' or v.id in self.jobs:
                continue
            stock = self.sites['work']['building'].inventory.amounts
            candidates = [sid for sid,s in self.sites.items() if sid.startswith('home-')
                          and sid not in outstanding
                          and s['building'].inventory.amounts.get('food',0) < s['building'].residents*1.5]
            if not candidates or stock.get('food',0) <= 0:
                continue
            destination = min(candidates, key=lambda sid:self.sites[sid]['building'].inventory.amounts.get('food',0)
                               /max(1,self.sites[sid]['building'].residents))
            target = self.sites[destination]['building']
            amount = min(v.capacity, stock['food'], target.residents*3-target.inventory.amounts.get('food',0))
            stock['food'] -= amount
            v.cargo['food'] = amount
            self.jobs[v.id] = dict(destination=destination, stage='loading')
            v.phase = 'queued_handling'
            self.handling['work'].append((v.id,'load'))
            outstanding.add(destination)

    def _arrivals(self):
        self.fleet.observe()
        for vid in self.fleet.arrivals:
            v = self.fleet.vehicles[vid]
            if v.kind == 'car':
                self._arrive_person(self.residents[v.driver])
            elif vid in self.jobs:
                job = self.jobs[vid]
                if job['stage'] == 'outbound':
                    job['stage'] = 'unloading'
                    v.phase = 'queued_handling'
                    self.handling[v.site].append((vid,'unload'))
                elif job['stage'] == 'return':
                    del self.jobs[vid]
        self.fleet.arrivals.clear()
        while self.transit.person_arrivals:
            self._arrive_person(self.residents[self.transit.person_arrivals.popleft()])

    def update(self, seconds):
        if not isfinite(seconds) or seconds < 0:
            raise ValueError('Time must be finite and nonnegative')
        end = self.time+seconds
        while self.time < end-1e-7:
            self._process_events()
            self._logistics()
            dt = min(5, end-self.time)
            if self._events:
                dt = min(dt, max(0, self._events[0][0]-self.time))
            if dt < 1e-8:
                continue
            self._economy(dt)
            self.transit.update(dt)
            self.time = self.transit.time
            self._arrivals()

    def report(self):
        states = Counter(p.state for p in self.residents.values())
        stock = sum(sum(s['building'].inventory.amounts.values()) for s in self.sites.values())
        cargo = sum(sum(v.cargo.values()) for v in self.fleet.vehicles.values())
        fuel = sum(v.fuel_liters for v in self.fleet.vehicles.values())+sum(b.fuel_liters for b in self.transit.buses.values())
        return dict(time=round(self.time,4), population=len(self.residents), at_home=states['home'],
                    at_work=states['work'], commuting=states['commuting']+states['returning'],
                    workers_arrived=self.workers_arrived, produced_food=self.produced,
                    consumed_food=self.consumed, unmet_food=self.unmet, deliveries=self.deliveries,
                    vehicles=len(self.fleet.vehicles)+len(self.transit.buses),
                    active_road_vehicles=len(self.transit.traffic.cars), fuel_liters=fuel,
                    resource_balance_error=stock+cargo+self.consumed-self.initial_resources,
                    fuel_used_liters=self.initial_fuel-fuel)

    def checkpoint(self):
        if (self.transit.traffic.cars or self.transit.engine.pedestrian_states() or self.jobs
                or self.bay_active or any(self.handling.values())
                or any(b.passengers for b in self.transit.buses.values())
                or any(p.state not in ('home','work') for p in self.residents.values())):
            raise ValueError('Checkpoint requires a quiescent town')
        # Serialize authored geometry plus logical actor records; native active
        # state is intentionally rejected rather than silently discarded.
        sites = {sid:dict(building_id=s['building'].id, lane_id=s['road_position'].lane.id,
                         distance=s['road_position'].distance, walk_point=s['walk_point'],
                         parking_capacity=s['parking_capacity']) for sid,s in self.sites.items()}
        buses = [dict((k,v) for k,v in asdict(b).items() if not k.startswith('_')) for b in self.transit.buses.values()]
        vehicles = [dict((k,v) for k,v in asdict(f).items() if not k.startswith('_')) for f in self.fleet.vehicles.values()]
        return dict(schema='town.quiescent.v1', world=world_to_dict(self.city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1),
                    sites=sites, residents=[asdict(p) for p in self.residents.values()], fleet=vehicles,
                    buses=buses, stops=[dict(id=s.id, lane_id=s.road_position.lane.id,
                        distance=s.road_position.distance, walk_point=s.walk_point) for s in self.transit.stops.values()],
                    lines=[asdict(l) for l in self.transit.lines.values()], time=self.time,
                    events=self._events, sequence=self._sequence, work_start=self.work_start,work_end=self.work_end,
                    metrics={k:getattr(self,k) for k in ('produced','consumed','unmet','deliveries','workers_arrived','initial_resources','initial_fuel')},
                    next_departure=self.transit._next_departure)

    @classmethod
    def from_checkpoint(cls, data):
        data = copy.deepcopy(data)
        if data.get('schema') != 'town.quiescent.v1':
            raise ValueError('Unsupported town checkpoint')
        city = world_from_dict(data['world']).city_map
        lanes = {l.id:l for r in city.roads for l in r.lanes}
        buildings = {b.id:b for b in city.buildings}
        sites = {sid:dict(building=buildings[s['building_id']],road_position=lane_position_at_distance(lanes[s['lane_id']],s['distance']),
                         walk_point=tuple(s['walk_point']),parking_capacity=s['parking_capacity']) for sid,s in data['sites'].items()}
        town = cls(city,sites,[Resident(**p) for p in data['residents']],work_start=data['work_start'],work_end=data['work_end'])
        town.time = town.transit.time = town.transit.traffic.elapsed_time = data['time']
        town.transit.engine._call('nt_clock',town.time,0.0,0.0)
        for s in data['stops']:
            town.transit.add_stop(BusStop(s['id'],lane_position_at_distance(lanes[s['lane_id']],s['distance']),tuple(s['walk_point'])))
        for line in data['lines']:
            line['stop_ids'] = tuple(line['stop_ids'])
            town.transit.add_line(BusLine(**line))
        for b in data['buses']:
            mutable = {k:b.pop(k) for k in ('phase','stop_index','passengers','distance_feet','ready_at','position')}
            bus = Bus(**b)
            town.transit.add_bus(bus)
            for k,v in mutable.items():
                setattr(bus,k,v)
        for v in data['fleet']:
            town.fleet.add(FleetVehicle(**v))
        town._events = [tuple(e) for e in data['events']]
        heapq.heapify(town._events)
        town._sequence = data['sequence']
        town.transit._next_departure = data['next_departure']
        for k,v in data['metrics'].items():
            setattr(town,k,v)
        return town


def build_town(population=1000, *, work_start=27000, work_end=57600):
    if isinstance(population,bool) or not isinstance(population,int) or population < 6:
        raise ValueError('Population must be an integer of at least six')
    city = CityMap(terrain=Terrain(trees=[]))
    road = city.add_road([(0,0),(6000,0)],name='Synthetic town main street',road_id='main')
    lane = next(l for l in road.lanes if l.direction == 'forward')
    sites, residents = {}, []
    homes = max(2, min(40,population//6))
    for h in range(homes):
        count = population//homes+(h<population%homes)
        x = 120+h*2200/max(1,homes-1)
        b = Building(f'Household {h}',Parcel(x,30,30,30),residents=count,id=f'home-{h}')
        b.inventory.amounts['food'] = count*.5
        city.parcels.append(b.parcel)
        city.buildings.append(b)
        sites[b.id] = dict(building=b, road_position=lane_position_at_distance(lane,x-lane.points[0][0]),
                           walk_point=(x,15),parking_capacity=3)
        for j in range(count):
            pid = len(residents)
            worker = j < max(1,int(count*.6))
            mode = 'car' if j == 0 else 'bus' if j%3 else 'walk'
            residents.append(Resident(pid,b.id,worker,mode,car_id=f'car-{h}' if j==0 else None))
    workplace = Building('Kitchen and grain store',Parcel(5720,30,60,60),jobs=population,id='work')
    workplace.inventory.amounts.update(food=population*2,grain=population*8)
    city.parcels.append(workplace.parcel)
    city.buildings.append(workplace)
    sites['work'] = dict(building=workplace,road_position=lane_position_at_distance(lane,5700),
                         walk_point=(5720,15),parking_capacity=homes+4)
    town = TownSimulation(city,sites,residents,work_start=work_start,work_end=work_end)
    town.transit.add_stop(BusStop('A',sites['home-0']['road_position'],sites['home-0']['walk_point']))
    town.transit.add_stop(BusStop('B',sites['work']['road_position'],sites['work']['walk_point']))
    town.transit.add_line(BusLine('town-line',('A','B'),headway_seconds=120))
    for i in range(2):
        town.transit.add_bus(Bus(f'bus-{i}', 'town-line', capacity=40, fuel_liters=100,
                                service_at=work_start,service_until=work_start+7200))
    for p in residents:
        if p.car_id:
            town.fleet.add(FleetVehicle(p.car_id,'car',p.home,driver=p.id))
    for i in range(2):
        town.fleet.add(FleetVehicle(f'truck-{i}','truck','work',capacity=120,
                                   fuel_liters=100,liters_per_mile=.3,length=28,width=8))
    town.initial_fuel = sum(v.fuel_liters for v in town.fleet.vehicles.values())+sum(b.fuel_liters for b in town.transit.buses.values())
    return town
