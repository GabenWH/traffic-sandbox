"""Gameplay for authored cities, using the existing service/fleet/native engine.

Decisions live on a simulated-time event queue. update() never polls buildings,
residents or housing at the movement frequency. Geometry edits notify sync.
"""
from collections import Counter, deque
from dataclasses import asdict
from math import exp, isfinite, dist
import heapq

from building_operations import operation_for
from construction import building_access_points
from households import DAY, MONTH, Household, HousingMemory
from mobility import nearest_lane_position
from models import BuildablePhase
from persistent_fleet import FleetVehicle
from town_services import Business, ServiceTown
from town_simulation import Resident
from transit import Bus, BusLine, BusStop


class CitySimulation(ServiceTown):
    def __init__(self, city, traffic=None, construction=None):
        super().__init__(city, {}, [], traffic=traffic)
        self.configure_services([])
        self.time = self.transit.time
        self.construction = construction
        self.households = {}
        self._suspended_walkers = {}
        self._resuming_vehicles = {}
        self._resuming_buses = {}
        self._membership = {}
        self._next_person = self._next_household = 0
        self._events = []
        self._scheduled = set()
        self.scene_revision = 0
        self._building_signature = None
        self._access_times = {}
        self._homes = []
        self._occupancy = Counter()
        self._demand_counts = Counter()
        self._reservations = Counter()
        self._vacancy_candidates = {}
        self._candidate_cursor = 0
        self.counters = Counter(economy=0, housing=0, jobs=0, construction=0)
        self.imported_resources = 0.0
        self.resource_journal = Counter()
        self._last_economy = self._last_construction = self.time
        self._construction_arrivals = []
        self._bind_arrivals()
        self.sync_buildings()
        self.initial_resources = sum(amount for b in city.buildings for r,amount in b.inventory.amounts.items() if r in self._resource_types())
        state = city.gameplay_state
        if state:
            self._restore(state)
        city.gameplay = self
        self.transit.traffic._before_native_discard = self.capture_transport

    def capture_transport(self):
        if not self.transit.engine._ptr:
            return
        from gameplay_persistence import dump_transport
        self._transport_backup = dump_transport(self.transit, set(self.fleet.vehicles)|set(self.transit.buses))

    def _bind_arrivals(self):
        self.transit.arrivals_listener = self._transport_arrived
        if self.construction is not None:
            if self.construction.road_vehicles is not self.transit.traffic:
                raise ValueError('Construction and town require the same road vehicle engine')
            self.transit.arrival_observer = self._construction_arrivals.extend

    def _transport_arrived(self,time):
        self.time=time
        self._arrivals()

    def _once(self, key, when, kind, value=None):
        if key not in self._scheduled:
            self._scheduled.add(key)
            self.schedule(when, kind, [key, value])

    def _wake_economy(self):
        if self.residents or self.businesses or self.jobs:
            self._once('economy', self.time+60, 'economy')

    def sync_buildings(self):
        signature = tuple((b.id, b.phase, b.residents, b.jobs, repr(b.operation)) for b in self.city.buildings)
        if signature == self._building_signature:
            return
        self._settle_economy(self.time)
        self._building_signature = signature
        self.scene_revision += 1
        previous = set(self.businesses)
        lanes = [l for road in self.city.roads for l in road.lanes]
        self._homes = []
        for b in self.city.buildings:
            role = operation_for(b)
            center = (b.parcel.x+b.parcel.width/2, b.parcel.y+b.parcel.height/2)
            position = min(building_access_points(self.city,b),key=lambda p:dist(p.point,center),default=None)
            site = dict(building=b,road_position=position,walk_point=center,parking_capacity=max(4,b.jobs+b.residents+4))
            self.sites[b.id] = site
            self.handling.setdefault(b.id,deque())
            if b.phase != BuildablePhase.OPERATIONAL:
                continue
            if role['role'] == 'home' and b.residents:
                self._homes.append(b.id)
            elif role['role'] != 'bus_stop':
                self.businesses[b.id] = Business(b.id,role['role'],role['inputs'],role['output'],role['rate'],role['targets'])
                if role['role']=='cafe':self.meal_queues.setdefault(b.id,deque())
            if role['role']=='bus_stop' and position is not None and b.id not in self.transit.stops:
                self.transit.add_stop(BusStop(b.id,position,center))
        active = {b.id for b in self.city.buildings if b.phase == BuildablePhase.OPERATIONAL}
        for sid in list(self.businesses):
            if sid not in active:
                del self.businesses[sid]
        # Retain removed addresses while people/cargo still refer to them.
        self._active_sites = active
        closed=previous-set(self.businesses)
        for pid,visit in list(self.visits.items()):
            if visit['site'] not in closed:continue
            visit['cancelled']=True
            p=self.residents[pid]
            if p.state in ('waiting_meal','waiting_care','service_return_pending'):
                for queue in self.meal_queues.values():
                    if pid in queue:queue.remove(pid)
                if pid in self.care_queue:self.care_queue.remove(pid)
                self.care_tasks[:]=[t for t in self.care_tasks if t['person']!=pid]
                self._leave_service(pid)
        self._access_times.clear()
        self.assign_jobs()
        for hid in self.households:
            self._once('changed:'+hid, self.time+60+(int(hid.split('-')[-1])%60), 'assess_changed', hid)
        self._refresh_occupancy()
        self._wake_economy()
        if self.construction and (any(b.phase == BuildablePhase.UNDER_CONSTRUCTION for b in self.city.buildings)
                                  or self.construction.road_deconstruction_jobs):
            self._once('construction',self.time+1,'construction')

    def _resident_count(self, site):
        return self._demand_counts[site]

    def _refresh_occupancy(self):
        self._occupancy=Counter();self._demand_counts=Counter();self._reservations=Counter()
        for h in self.households.values():
            self._occupancy[h.home]+=len(h.members)
            if h.moving_to:self._reservations[h.moving_to]+=len(h.members)
            else:self._demand_counts[h.home]+=len(h.members)
        for b in self.city.buildings:b.occupants=self._occupancy[b.id]
        self._vacancy_candidates={size:[sid for sid in self._homes if self.vacancy(sid)>=size] for size in range(1,5)}

    def vacancy(self, home):
        if home not in self._homes:
            return 0
        capacity=self.sites[home]['building'].residents
        committed=self._occupancy[home]+self._reservations[home]
        return max(0,capacity-committed)

    def invite_household(self, home, size=4, *, car=False):
        self._settle_economy(self.time)
        if isinstance(size,bool) or not isinstance(size,int) or size<1 or size>4 or self.vacancy(home)<size:
            raise ValueError('Household needs 1..4 people and a suitable housing vacancy')
        hid=f'household-{self._next_household}';self._next_household+=1
        members=[]
        for i in range(size):
            pid=self._next_person;self._next_person+=1
            person=Resident(pid,home,i<max(1,int(size*.6)),mode='bus',workplace=None)
            self.residents[pid]=person;members.append(pid);self._membership[pid]=hid
        h=Household(hid,home,members,memory=HousingMemory(updated_at=self.time))
        self.households[hid]=h
        if car:
            p=self.residents[members[0]];p.mode='car';p.car_id='car-'+hid
            if self.sites[home]['road_position'] is None:
                p.mode='bus';p.car_id=None
            else:
                self.fleet.add(FleetVehicle(p.car_id,'car',home,driver=p.id))
                self.initial_fuel+=self.fleet.vehicles[p.car_id].fuel_liters
        self._refresh_occupancy();self.assign_jobs();self._wake_economy()
        h.last_score=self.desirability(h,home)
        self._once('care:'+hid,self.time+MONTH+(len(self.households)%3600),'choose_care',h.members[0])
        self._once('assess:'+hid,self.time+MONTH+(len(self.households)%3600),'assess',hid)
        self._note('household_invited',household=hid,home=home,size=size)
        return h

    def assign_jobs(self):
        self.counters['jobs']+=1
        assigned=Counter(p.workplace for p in self.residents.values() if p.workplace in self.businesses)
        for p in self.residents.values():
            if not p.worker:continue
            if p.workplace not in self.businesses:
                if p.state=='work' and p.workplace in self.sites:
                    p.return_due=True;self._safe_depart(p,True)
                    continue
                if p.state not in ('home','relocating_pending','relocating_arrived'):
                    p.return_due=True
                    continue
                p.workplace=None
            if p.workplace is None:
                options=[sid for sid in self.businesses if assigned[sid]<self.sites[sid]['building'].jobs]
                options.sort(key=lambda sid:self.travel_seconds(self.sites[p.home]['walk_point'],self.sites[sid]['walk_point']))
                if options and isfinite(self.travel_seconds(self.sites[p.home]['walk_point'],self.sites[options[0]]['walk_point'])):
                    p.workplace=options[0];assigned[p.workplace]+=1
            if p.workplace:
                self._schedule_shift(p)
        for p in self.residents.values():
            day=int(self.time//DAY);lunch=day*DAY+12*3600+(p.id%4)*900
            if lunch<=self.time:lunch+=DAY;day+=1
            self._once(f'meal:{p.id}:{day}',lunch,'choose_meal',p.id)
        if self.residents:self._once('jobs',self.time+DAY,'jobs')

    def _schedule_shift(self,p):
        day=int(self.time//DAY)
        start=day*DAY+self.work_start+(p.id%20)*2
        end=day*DAY+self.work_end
        if self.time>=end:day+=1;start+=DAY;end+=DAY
        self._once(f'leave:{p.id}:{day}',max(self.time,start),'leave',p.id)
        self._once(f'return:{p.id}:{day}',end,'return_person',p.id)

    def travel_seconds(self, origin, destination):
        key=(tuple(origin),tuple(destination))
        if key not in self._access_times:
            try:self._access_times[key]=self.transit.journey_path(origin,destination).cost
            except ValueError:self._access_times[key]=float('inf')
        return self._access_times[key]

    def desirability(self, household, home):
        site=self.sites[home];point=site['walk_point'];b=site['building']
        def access(targets):
            seconds=min((self.travel_seconds(point,self.sites[t]['walk_point']) for t in targets),default=float('inf'))
            return 100*exp(-seconds/1800)
        food=[sid for sid,biz in self.businesses.items() if biz.kind in ('market','cafe')
              and self.sites[sid]['building'].inventory.amounts.get('food',0)>0]
        clinics=[sid for sid,biz in self.businesses.items() if biz.kind=='clinic'
                 and self.staff[sid]>0 and self.sites[sid]['building'].inventory.amounts.get('medicine',0)>0]
        workplaces=[self.residents[pid].workplace for pid in household.members if self.residents[pid].workplace in self.businesses]
        commute=sum(access([sid]) for sid in workplaces)/len(workplaces) if workplaces else 40
        return .15*operation_for(b)['quality']+.4*access(food)+.3*commute+.15*access(clinics)

    def assess_household(self,hid):
        h=self.households[hid];self.counters['housing']+=1
        if h.moving_to:return
        score=self.desirability(h,h.home);h.last_score=score
        threshold=h.memory.value_at(self.time)
        h.memory.observe(score,self.time)
        candidates=self._vacancy_candidates.get(len(h.members),[])
        # Rotate a bounded batch, so large cities do not perform all pairs searches.
        if candidates:
            start=self._candidate_cursor%len(candidates);self._candidate_cursor+=32
            candidates=[candidates[(start+i)%len(candidates)] for i in range(min(32,len(candidates)))]
            candidates=[sid for sid in candidates if sid!=h.home]
            if not candidates:return
            best=max(candidates,key=lambda sid:self.desirability(h,sid))
            if self.desirability(h,best)>score+threshold:
                try:self.relocate(hid,best)
                except ValueError:pass

    def relocate(self,hid,target):
        self._settle_economy(self.time)
        h=self.households[hid]
        if h.moving_to or target==h.home or self.vacancy(target)<len(h.members):
            raise ValueError('Relocation needs an unreserved housing vacancy')
        if any(self.residents[pid].state!='home' for pid in h.members):
            raise ValueError('Household must be together at home to begin moving')
        source=self.sites[h.home];destination=self.sites[target]
        if not isfinite(self.travel_seconds(source['walk_point'],destination['walk_point'])):
            raise ValueError('No route to relocation home')
        old_count=self.sites[h.home]['building'].occupants
        stock=source['building'].inventory.amounts
        food=stock.get('food',0)*len(h.members)/max(1,old_count)
        stock['food']=stock.get('food',0)-food;h.cargo['food']=food
        h.meal_credit=self.meal_credit[h.home]*len(h.members)/max(1,self._resident_count(h.home))
        self.meal_credit[h.home]-=h.meal_credit
        h.moving_to=target;h.arrived=[]
        self._refresh_occupancy()
        for pid in h.members:
            self.residents[pid].state='relocating_pending'
            self._once('move:'+str(pid),self.time,'move_person',pid)
        self._note('relocation_started',household=hid,source=h.home,destination=target)

    def _move_person(self,pid):
        p=self.residents[pid];h=self.households[self._membership[pid]]
        if not h.moving_to:return
        try:
            if p.car_id:
                admitted=self.fleet.dispatch(p.car_id,h.moving_to)
            else:
                self.transit.request_trip(pid,self.sites[h.home]['walk_point'],self.sites[h.moving_to]['walk_point'])
                admitted=True
        except (ValueError,RuntimeError):admitted=False
        if admitted:p.state='relocating'
        else:self._once('move:'+str(pid),self.time+60,'move_person',pid)

    def _arrive_person(self,p):
        self._settle_economy(self.time)
        if p.state=='relocating':
            h=self.households[self._membership[p.id]]
            if p.id not in h.arrived:h.arrived.append(p.id)
            p.state='relocating_arrived'
            if len(h.arrived)==len(h.members):
                h.home,h.moving_to=h.moving_to,None
                for resource,amount in h.cargo.items():
                    if amount>0:self.sites[h.home]['building'].inventory.add(resource,amount)
                self.meal_credit[h.home]+=h.meal_credit;h.meal_credit=0
                h.cargo.clear();h.arrived.clear();h.memory.moved(self.time)
                for pid in h.members:self.residents[pid].home=h.home;self.residents[pid].state='home'
                self._refresh_occupancy();self._note('relocation_completed',household=h.id,home=h.home)
            return
        if p.state=='commuting':
            p.state='work';self.staff[p.workplace]+=1;self.workers_arrived+=1;self._note('worker_arrived',person=p.id,site=p.workplace)
            if p.return_due:self._safe_depart(p,True)
            return
        if p.state=='returning':
            p.state='home';p.return_due=False
            if p.workplace not in self.businesses:p.workplace=None
            return
        if p.state=='visiting' and self.visits.get(p.id,{}).get('cancelled'):
            self._leave_service(p.id)
            return
        super()._arrive_person(p)

    def _safe_depart(self,p,returning=False):
        self._settle_economy(self.time)
        if p.workplace is None:return False
        if not returning and p.state!='home':return False
        was_work=p.state=='work'
        try:success=self._depart(p,returning)
        except (ValueError,RuntimeError,KeyError):success=False
        if success and was_work:self.staff[p.workplace]=max(0,self.staff[p.workplace]-1)
        if not success:self._once(('retry_return:' if returning else 'retry_leave:')+str(p.id),self.time+60,'retry_return' if returning else 'retry_leave',p.id)
        return success

    def _worker_resumed(self,person):
        self.staff[person.workplace]+=1

    def _return_after_visit(self,person):
        self._safe_depart(person,True)

    def _defer_service_return(self,pid):
        self._once('service_return:'+str(pid),self.time+60,'service_return',pid)

    def _settle_economy(self,time):
        elapsed=time-self._last_economy
        if elapsed>1e-8:
            self._last_economy=time
            self._economy(elapsed)

    def request_visit(self,person_id,site,purpose):
        self._settle_economy(self.time)
        p=self.residents[person_id];work=p.workplace if p.state=='work' else None
        result=super().request_visit(person_id,site,purpose)
        if result and work is not None:self.staff[work]=max(0,self.staff[work]-1)
        return result

    def _economy(self,dt):
        super()._economy(dt)
        for h in self.households.values():
            if h.moving_to:
                need=len(h.members)*3*dt/DAY
                credit=min(need,h.meal_credit);h.meal_credit-=credit;need-=credit
                used=min(need,h.cargo.get('food',0));h.cargo['food']=h.cargo.get('food',0)-used
                self.consumed+=used;self.unmet+=need-used
        self.counters['economy']+=1

    def _run_event(self,kind,value):
        key,value=value;self._scheduled.discard(key)
        if kind=='economy':
            self._settle_economy(self.time)
            self._logistics();self._wake_economy()
        elif kind=='construction':
            self.counters['construction']+=1
            self.construction.observe_arrivals(self._construction_arrivals)
            self._construction_arrivals.clear()
            self.construction.update_external(self.city,self.time-self._last_construction)
            self.sync_network()
            self._last_construction=self.time
            self.sync_buildings()
            if (self.construction.trips or self.construction.pending_trips or self.construction.road_deconstruction_jobs
                    or any(b.phase==BuildablePhase.UNDER_CONSTRUCTION for b in self.city.buildings)):
                self._once('construction',self.time+1,'construction')
        elif kind=='jobs':self.assign_jobs()
        elif kind in ('assess','assess_changed'):
            self.assess_household(value)
            if kind=='assess':self._once('assess:'+value,self.time+MONTH,'assess',value)
        elif kind in ('leave','retry_leave'):
            p=self.residents[value]
            if p.state=='home' and self.time%DAY<self.work_end:p.return_due=False;self._safe_depart(p)
        elif kind in ('return_person','retry_return'):
            p=self.residents[value];p.return_due=True
            if p.state=='work':self._safe_depart(p,True)
        elif kind=='move_person':self._move_person(value)
        elif kind=='resume':self._resume_transport()
        elif kind=='service_return':self._leave_service(value)
        elif kind in ('choose_meal','choose_care'):
            self._choose_service(value,'meal' if kind=='choose_meal' else 'care')
            if kind=='choose_care':self._once(key,self.time+MONTH,'choose_care',value)
        elif kind=='service_visit':
            pid,site,purpose=value
            try:self.request_visit(pid,site,purpose)
            except (ValueError,RuntimeError):pass

    def update(self,seconds):
        if not isfinite(seconds) or seconds<0:raise ValueError('Time must be finite and nonnegative')
        self.sync_network()
        end=self.time+seconds
        if self.transit.person_arrivals or self.transit.vehicle_arrivals:
            self._transport_arrived(self.transit.time)
        if self.construction:self.construction.completed_road_vehicles=[]
        while self.time<end-1e-8 or (self._events and self._events[0][0]<=self.time+1e-8):
            while self._events and self._events[0][0]<=self.time+1e-8:
                _,_,kind,value=heapq.heappop(self._events);self._run_event(kind,value)
                if self.transit.person_arrivals or self.transit.vehicle_arrivals:
                    self._transport_arrived(self.transit.time)
            if self.time>=end-1e-8:break
            until=min(end,self._events[0][0] if self._events else end)
            self.transit.update(until-self.time)
            self.time=self.transit.time
            self._arrivals()
        self.time=end

    def sync_network(self):
        if self.transit.revision!=self.city.mobility_revision or self.transit.traffic._native_controller is None:
            from gameplay_persistence import rebind_transport
            rebind_transport(self)

    def _choose_service(self,pid,purpose):
        p=self.residents[pid]
        if p.state not in ('home','work'):return
        origin=p.home if p.state=='home' else p.workplace
        role,resource=('cafe','food') if purpose=='meal' else ('clinic','medicine')
        options=[sid for sid,b in self.businesses.items() if b.kind==role and self.staff[sid]>0
                 and self.sites[sid]['building'].inventory.amounts.get(resource,0)>=1]
        if not options:return
        if p.state=='work':options=[sid for sid in options if sid!=p.workplace or self.staff[sid]>1]
        if not options:return
        target=min(options,key=lambda sid:self.travel_seconds(self.sites[origin]['walk_point'],self.sites[sid]['walk_point']))
        try:self.request_visit(pid,target,purpose)
        except (ValueError,RuntimeError):pass

    def _resource_types(self):
        types={'food','grain','seed','medicine'}
        for b in self.businesses.values():
            types.update(b.inputs);types.update(b.targets)
            if b.output:types.add(b.output)
        return types

    def _record_production(self,business,amount):
        self.resource_journal[business.output]+=amount
        for resource,quantity in business.inputs.items():self.resource_journal[resource]-=quantity*amount

    def assign_workplace(self,person_id,site):
        p=self.residents[person_id]
        if p.state!='home' or site not in self.businesses:raise ValueError('Assign a resident who is at home to an operating workplace')
        assigned=sum(q.id!=p.id and q.workplace==site for q in self.residents.values())
        if assigned>=self.sites[site]['building'].jobs:raise ValueError('Workplace has no vacant jobs')
        p.worker=True;p.workplace=site;self._schedule_shift(p)

    def report(self):
        result=super().report()
        types=self._resource_types()
        stock=sum(amount for s in self.sites.values() for r,amount in s['building'].inventory.amounts.items() if r in types)
        cargo=sum(sum(v.cargo.values()) for v in self.fleet.vehicles.values())+sum(sum(h.cargo.values()) for h in self.households.values())
        reserved=sum(j.get('reserved',0) for j in self.jobs.values())
        result['resource_balance_error']=stock+cargo+reserved+self.consumed+self.medical_sinks-self.initial_resources-self.imported_resources-sum(self.resource_journal.values())
        result['households']=len(self.households)
        result['relocating_households']=sum(h.moving_to is not None for h in self.households.values())
        return result

    def _resume_transport(self):
        for pid,(origin,destination) in list(self._suspended_walkers.items()):
            try:self.transit.request_trip(pid,origin,destination)
            except (ValueError,RuntimeError):continue
            del self._suspended_walkers[pid]
        for vid,(point,destination) in list(self._resuming_vehicles.items()):
            if self.fleet.dispatch(vid,destination,origin_point=point):del self._resuming_vehicles[vid]
        for bid,(point,stop) in list(self._resuming_buses.items()):
            bus=self.transit.buses[bid]
            if bus.line_id not in self.transit.lines or stop not in self.transit.stops:continue
            lanes=[l for r in self.city.roads for l in r.lanes]
            if not lanes:continue
            target_index=self.transit.lines[bus.line_id].stop_ids.index(stop)
            if dist(point,self.transit.stops[stop].road_position.point)<1e-6:
                bus.stop_index=target_index;self.transit._dock(bus)
                del self._resuming_buses[bid];continue
            origin=min((nearest_lane_position(l,point) for l in lanes),key=lambda x:x[1])[0]
            route=self.city.find_vehicle_route_between(origin,self.transit.stops[stop].road_position)
            if route is None:continue
            actor=self.transit.traffic.admit_route(route,vehicle_id=bid,source_id='resume',destination_id=stop,
                source_type='bus',length=bus.length,width=bus.width,color='#e3a82f')
            if actor is not None:
                bus.stop_index=(target_index-1)%len(self.transit.lines[bus.line_id].stop_ids)
                bus._car=actor;bus._last_distance=0;bus.phase='driving'
                del self._resuming_buses[bid]
        if self._suspended_walkers or self._resuming_vehicles or self._resuming_buses:
            self._once('resume',self.time+60,'resume')

    def commission_truck(self,site):
        if site not in self.sites or self.sites[site]['road_position'] is None:
            raise ValueError('Truck requires a building with road access')
        vid='town-truck-'+str(len(self.fleet.vehicles))
        v=FleetVehicle(vid,'truck',site,capacity=120,fuel_liters=100,length=28,width=8)
        self.fleet.add(v);self.initial_fuel+=v.fuel_liters;return v

    def create_line(self,stop_ids):
        if len(set(stop_ids))<2:raise ValueError('Select at least two different completed bus stops')
        lid='city-line-'+str(len(self.transit.line_plans))
        self.transit.add_line(BusLine(lid,tuple(stop_ids),headway_seconds=600))
        for i in range(2):
            bus=Bus(lid+'-bus-'+str(i),lid,capacity=60)
            self.transit.add_bus(bus);self.initial_fuel+=bus.fuel_liters
        self._access_times.clear()
        return lid

    def import_resources(self,site,resource,amount):
        if site not in self.sites or not isfinite(amount) or amount<=0:raise ValueError('Delivery requires a site and positive finite amount')
        self._settle_economy(self.time)
        self.sites[site]['building'].inventory.add(resource,amount);self.imported_resources+=amount
        self._wake_economy()

    def refuel_at(self,site,amount):
        if site not in self.sites or not isfinite(amount) or amount<=0:raise ValueError('Refuel requires a site and positive finite litres')
        total=0
        for vehicle in self.fleet.vehicles.values():
            if vehicle.site==site and vehicle.phase=='parked':vehicle.fuel_liters+=amount;total+=amount
        for bus in self.transit.buses.values():
            line=self.transit.lines.get(bus.line_id)
            if line and line.stop_ids[bus.stop_index]==site and bus.phase in ('docked','out_of_fuel'):
                bus.fuel_liters+=amount;bus.phase='docked';total+=amount
        self.initial_fuel+=total
        return total

    def snapshot(self):
        from gameplay_persistence import dump_city
        return dump_city(self)

    def _restore(self,state):
        from gameplay_persistence import restore_city
        restore_city(self,state)
