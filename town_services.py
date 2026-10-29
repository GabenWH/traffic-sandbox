"""Staffed food businesses, finite farm harvests, clinic visits and requesters.

Recipe/care rates are fictional scenario units. No diagnostic or medical model
is implied by a completed care visit. Road movement is owned by shared C++.
"""
from collections import Counter,deque
from dataclasses import dataclass,asdict
from town_simulation import TownSimulation


@dataclass
class Business:
    site: str
    kind: str
    inputs: dict
    output: str | None
    rate_per_worker_hour: float
    targets: dict


class ServiceTown(TownSimulation):
    def configure_services(self,businesses):
        self.businesses={b.site:b for b in businesses}
        self.care_queue=deque();self.care_tasks=[];self.visits={}
        self.meal_queues={b.site:deque() for b in businesses if b.kind=='cafe'}
        self.meal_credit=Counter()
        self.meal_capacity=Counter()
        self.harvested=self.medical_sinks=0.0
        self.treated=self.meals_served=0
        self.requests=[]
        self.staff=Counter()

    def _record_production(self, business, amount):
        pass

    def _resident_count(self, site):
        return self.sites[site]["building"].residents

    def request_visit(self,person_id,site,purpose):
        p=self.residents[person_id]
        if p.state not in ('home','work') or person_id in self.visits:
            return False
        if purpose not in ('care','meal') or site not in self.businesses:
            raise ValueError('Unknown service visit')
        if (purpose=='care' and self.businesses[site].kind!='clinic') or (purpose=='meal' and site not in self.meal_queues):
            raise ValueError('Site does not offer requested service')
        origin=p.home if p.state=='home' else p.workplace
        self.transit.request_trip(p.id,self.sites[origin]['walk_point'],self.sites[site]['walk_point'])
        self.visits[p.id]=dict(site=site,purpose=purpose,origin=origin,previous=p.state)
        p.state='visiting'
        return True

    def _process_events(self):
        # Dispatch service events separately, preserving the existing commute
        # schedule and its retry semantics.
        import heapq
        service=[];regular=[]
        while self._events and self._events[0][0]<=self.time+1e-7:
            event=heapq.heappop(self._events)
            (service if event[2] in ('service_visit','service_return') else regular).append(event)
        for event in regular:heapq.heappush(self._events,event)
        super()._process_events()
        for _,_,kind,value in service:
            if kind=='service_return':self._leave_service(value);continue
            pid,site,purpose=value
            if not self.request_visit(pid,site,purpose) and self.time<self.work_end:
                self.schedule(self.time+60,'service_visit',(pid,site,purpose))

    def _depart(self,person,returning=False):
        if person.id in self.visits:
            person.return_due=returning
            return False
        from math import dist
        source,target=(person.workplace,person.home) if returning else (person.home,person.workplace)
        if dist(self.sites[source]['walk_point'],self.sites[target]['walk_point'])<1e-7:
            person.state='returning' if returning else 'commuting'
            self._arrive_person(person)
            return True
        return super()._depart(person,returning)

    def _arrive_person(self,p):
        if p.state=='visiting':
            visit=self.visits[p.id]
            if visit['purpose']=='care':
                p.state='waiting_care';self.care_queue.append(p.id)
            else:
                p.state='waiting_meal';self.meal_queues[visit['site']].append(p.id)
            return
        if p.state=='visiting_return':
            visit=self.visits.pop(p.id)
            p.state=visit['previous']
            if p.state=='work':self._worker_resumed(p)
            if p.return_due and p.state=='work':
                self._return_after_visit(p)
            return
        super()._arrive_person(p)

    def _leave_service(self,pid):
        if pid not in self.visits:
            return
        p=self.residents[pid];visit=self.visits[pid]
        p.state='service_return_pending'
        try:
            self.transit.request_trip(pid,self.sites[visit['site']]['walk_point'],self.sites[visit['origin']]['walk_point'])
        except (ValueError,RuntimeError):
            self._defer_service_return(pid)
            return
        p.state='visiting_return'

    def _worker_resumed(self,person):
        pass

    def _defer_service_return(self,pid):
        self.schedule(self.time+60,'service_return',pid)

    def _return_after_visit(self,person):
        if not self._depart(person,True):self.schedule(self.time+5,'retry_return',person.id)

    def _economy(self,dt):
        self.staff=Counter(p.workplace for p in self.residents.values() if p.state=='work')
        for b in self.businesses.values():
            inv=self.sites[b.site]['building'].inventory.amounts
            if b.output:
                amount=self.staff[b.site]*b.rate_per_worker_hour*dt/3600
                for resource,quantity in b.inputs.items():
                    amount=min(amount,inv.get(resource,0)/quantity)
                for resource,quantity in b.inputs.items():
                    inv[resource]=inv.get(resource,0)-amount*quantity
                inv[b.output]=inv.get(b.output,0)+amount
                self._record_production(b,amount)
                if b.output=='food':self.produced+=amount
                elif b.output=='grain':self.harvested+=amount
        for sid,site in self.sites.items():
            n=self._resident_count(sid)
            if not n:continue
            inv=site['building'].inventory.amounts
            wanted=n*3*dt/86400
            credit=min(wanted,self.meal_credit[sid]);self.meal_credit[sid]-=credit
            wanted-=credit
            used=min(wanted,inv.get('food',0));inv['food']=inv.get('food',0)-used
            self.consumed+=used;self.unmet+=wanted-used
        for site,queue in self.meal_queues.items():
            inv=self.sites[site]['building'].inventory.amounts
            self.meal_capacity[site]=min(self.staff[site],self.meal_capacity[site]+self.staff[site]*dt/60)
            for _ in range(min(len(queue),int(self.meal_capacity[site]+1e-9))):
                if inv.get('food',0)<1:break
                pid=queue.popleft();inv['food']-=1
                self.meal_capacity[site]=max(0,self.meal_capacity[site]-1)
                self.meals_served+=1;self.consumed+=1
                self.meal_credit[self.residents[pid].home]+=1
                self._note('meal_served',person=pid,site=site)
                self._leave_service(pid)
        for clinic in (b.site for b in self.businesses.values() if b.kind=='clinic'):
            inv=self.sites[clinic]['building'].inventory.amounts
            slots=min(4,self.staff[clinic])
            active=[t for t in self.care_tasks if t.get('site',clinic)==clinic]
            for pid in list(self.care_queue):
                if len(active)>=slots or inv.get('medicine',0)<1:break
                if self.visits.get(pid,{}).get('site',clinic)!=clinic:continue
                self.care_queue.remove(pid);inv['medicine']-=1;self.medical_sinks+=1
                task=dict(person=pid,site=clinic,remaining=120.0)
                self.care_tasks.append(task);active.append(task)
            for task in active[:slots]:
                task['remaining']-=dt
                if task['remaining']<=0:
                    self.care_tasks.remove(task);self.treated+=1
                    self._note('care_completed',person=task['person'],site=clinic)
                    self._leave_service(task['person'])

    def _logistics(self):
        for site,(vid,finish,operation) in list(self.bay_active.items()):
            if finish>self.time+1e-8:continue
            v=self.fleet.vehicles[vid];job=self.jobs[vid];v.phase='parked'
            if operation=='load':
                v.cargo[job['resource']]=job['amount'];job['reserved']=0
                job['stage']='outbound'
            else:
                inv=self.sites[site]['building'].inventory.amounts
                resource=job['resource'];inv[resource]=inv.get(resource,0)+v.cargo.pop(resource,0)
                job['stage']='return';self.deliveries+=1
                self._note('unload',site=site,resource=resource,vehicle=vid)
            del self.bay_active[site]
        for site,queue in self.handling.items():
            if queue and site not in self.bay_active:
                vid,operation=queue.popleft();v=self.fleet.vehicles[vid];v.phase='handling'
                job=self.jobs[vid]
                # Rates are specific to the material handled, not the depot.
                rate={'food':10,'grain':15,'medicine':1}.get(job['resource'],5)
                self.bay_active[site]=(vid,self.time+5+job['amount']/rate,operation)
        for vid,job in list(self.jobs.items()):
            v=self.fleet.vehicles[vid]
            if v.phase!='parked':continue
            if job['stage']=='to_source':
                if v.site==job['source']:
                    v.phase='queued_handling';job['stage']='loading'
                    self.handling[v.site].append((vid,'load'))
                else:self.fleet.dispatch(vid,job['source'])
            elif job['stage']=='outbound':self.fleet.dispatch(vid,job['destination'])
            elif job['stage']=='return':
                if v.site==job['source']:del self.jobs[vid]
                else:self.fleet.dispatch(vid,job['source'])
        requests=[]
        outstanding={(j['destination'],j['resource']) for j in self.jobs.values()}
        for sid,site in self.sites.items():
            targets=({'food':self._resident_count(sid)*3} if self._resident_count(sid) else {})
            if sid in self.businesses:targets.update(self.businesses[sid].targets)
            for resource,target in targets.items():
                available=site['building'].inventory.amounts.get(resource,0)
                if available<target*.5 and (sid,resource) not in outstanding:
                    requests.append(dict(site=sid,resource=resource,amount=target-available))
        self.requests=requests
        for v in self.fleet.vehicles.values():
            if v.kind!='truck' or v.phase!='parked' or v.id in self.jobs:continue
            for req in requests:
                key=(req['site'],req['resource'])
                if key in outstanding:continue
                suppliers=[b.site for b in self.businesses.values() if b.site!=req['site'] and (
                    b.output==req['resource'] or (req['resource']=='food' and b.kind=='market'))
                    and self.sites[b.site]['building'].inventory.amounts.get(req['resource'],0)>0]
                if self._resident_count(req['site']):
                    suppliers=[s for s in suppliers if self.businesses[s].kind=='market']
                if not suppliers:continue
                source=max(suppliers,key=lambda s:self.sites[s]['building'].inventory.amounts.get(req['resource'],0))
                inv=self.sites[source]['building'].inventory.amounts
                amount=min(v.capacity,req['amount'],inv[req['resource']]);inv[req['resource']]-=amount
                self.jobs[v.id]=dict(source=source,destination=req['site'],resource=req['resource'],amount=amount,
                                      reserved=amount,stage='to_source')
                outstanding.add(key);break

    def _arrivals(self):
        self.fleet.observe()
        for vid in self.fleet.arrivals:
            v=self.fleet.vehicles[vid]
            if v.kind=='car':self._arrive_person(self.residents[v.driver])
            elif vid in self.jobs:
                job=self.jobs[vid]
                if job['stage']=='to_source':
                    v.phase='queued_handling';job['stage']='loading'
                    self.handling[v.site].append((vid,'load'))
                elif job['stage']=='outbound':
                    v.phase='queued_handling';job['stage']='unloading'
                    self.handling[v.site].append((vid,'unload'))
                elif job['stage']=='return':del self.jobs[vid]
        self.fleet.arrivals.clear()
        while self.transit.person_arrivals:
            self._arrive_person(self.residents[self.transit.person_arrivals.popleft()])

    def report(self):
        result=super().report()
        result['commuting']=sum(p.state in ('commuting','returning','visiting','visiting_return') for p in self.residents.values())
        result['at_services']=sum(p.state in ('waiting_care','waiting_meal') for p in self.residents.values())
        result.update(treated=self.treated,clinic_waiting=len(self.care_queue),meals_served=self.meals_served,
                      harvested=self.harvested,outstanding_requests=len(self.requests))
        result['resource_balance_error']+=self.medical_sinks+sum(j.get('reserved',0) for j in self.jobs.values())
        return result

    def checkpoint(self):
        if self.visits or self.care_queue or self.care_tasks or any(self.meal_queues.values()):
            raise ValueError('Service checkpoint requires completed visits')
        result=super().checkpoint()
        result['service_model']=dict(businesses=[asdict(b) for b in self.businesses.values()],
                                    meal_credit=dict(self.meal_credit),meal_capacity=dict(self.meal_capacity),requests=self.requests,medical_sinks=self.medical_sinks,
                                    harvested=self.harvested,treated=self.treated,meals_served=self.meals_served)
        return result

    @classmethod
    def from_checkpoint(cls,data):
        town=TownSimulation.from_checkpoint(data);town.__class__=cls
        model=data['service_model'];town.configure_services([Business(**b) for b in model['businesses']])
        town.meal_credit.update(model['meal_credit'])
        town.meal_capacity.update(model.get('meal_capacity',{}))
        town.requests=model.get('requests',[])
        for k in ('medical_sinks','harvested','treated','meals_served'):setattr(town,k,model[k])
        return town
