"""Personal car/walk legs and change-driven parking admission waits.

Parking endpoints belong to the fleet, not the economic building inventory.
Unchanged blocked trips are indexed by the resource that can wake them.
"""
from collections import ChainMap, Counter, OrderedDict, defaultdict
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from commute_preferences import CommutePreferences
from math import ceil, dist, isfinite

DAY = 86400
_OPTIONS_PENDING = object()


@dataclass
class _ParkingOptions:
    sites: list[str]
    remaining: Iterator[str | None]
    complete: bool = False


class ParkingTrips:
    def __init__(self, runtime):
        self.runtime = runtime
        self.preferences = CommutePreferences()
        self.plans = {}
        self.waits = {}
        self.counts = Counter()
        self.last_unmet = {}
        self.extra_sites = {}
        self.access = None
        self._options = {}
        self._walk_epoch = None
        self._walk_queries_left = 0
        self._lot_waiters = defaultdict(OrderedDict)
        self._dirty_lots = set()
        self._capacity_inflight = {}
        self._woken_lots = {}
        self._serial = 0

    def sync_access(self):
        from parking_access import ParkingAccessIndex
        r = self.runtime
        access = ParkingAccessIndex(r.city, r.sites)
        extra = dict(access.sites)
        # Retain physical addresses while a car still refers to them. A removed
        # road invalidates driving access; it does not teleport a parked car.
        lane_ids = {lane.id for road in r.city.roads for lane in road.lanes}
        for vehicle in r.fleet.vehicles.values():
            for sid in (vehicle.site, vehicle.destination):
                if sid in self.extra_sites and sid not in extra:
                    extra[sid] = dict(self.extra_sites[sid])
                    position = extra[sid].get('road_position')
                    if position is not None and position.lane.id not in lane_ids:
                        extra[sid]['road_position'] = None
        self.access, self.extra_sites = access, extra
        r.fleet.sites = ChainMap(self.extra_sites, r.sites)
        self._options.clear()
        for plan in self.plans.values():
            if plan['stage'] in ('ready', 'at_car'):
                plan['failed'] = {}
        if hasattr(r.fleet, 'rebuild_indexes'):
            r.fleet.rebuild_indexes()
        self.wake_network()

    def options(self, destination, *, bounded=False):
        """Replay eligible sites, checking further walks only when needed.

        Most departures use the primary lot. Keep the candidate iterator beside
        the validated prefix so a retry (or another commuter) resumes validation
        without rebuilding walks or eagerly retaining every hypothetical path.
        """
        if destination not in self._options:
            self._options[destination] = _ParkingOptions([destination], self._alternate_options(destination))
        state = self._options[destination]
        validated, pending = state.sites, state.remaining
        index = 0
        while True:
            if index == len(validated):
                if state.complete:
                    return
                if bounded and not self._take_walk_query():
                    yield _OPTIONS_PENDING
                    return
                try:
                    sid = next(pending)
                except StopIteration:
                    state.complete = True
                    return
                if sid is None:
                    continue
                validated.append(sid)
            yield validated[index]
            index += 1

    def _take_walk_query(self):
        # Match CitySimulation's movement-quantum budget: event fragments and
        # multiple commuters in the same quantum must not reset the allowance.
        epoch = max(0, ceil(self.runtime.time/.05-1e-6)-1)
        if epoch != self._walk_epoch:
            self._walk_epoch = epoch
            self._walk_queries_left = self.runtime.commute_policy.parking_walk_queries
        if self._walk_queries_left <= 0:
            return False
        self._walk_queries_left -= 1
        return True

    def _alternate_options(self, destination):
        r = self.runtime
        seen = {r.fleet._lot_key(destination)}
        limit = r.commute_policy.parking_walk_seconds
        point = r.sites[destination]['walk_point']
        for sid in self.access.candidates(destination, max_distance=limit*4.4):
            key = r.fleet._lot_key(sid)
            if key in seen:
                continue
            seen.add(key)
            endpoint = r.fleet.sites[sid]['walk_point']
            try:
                cost = r.transit.walking_cost(endpoint, point)
            except ValueError:
                yield None
                continue
            yield sid if cost <= limit+1e-8 else None

    def _walk_cost(self, origin, destination, *, allow_bus=False):
        try:
            transit = self.runtime.transit
            return (transit.journey_path(origin, destination).cost if allow_bus else
                    transit.walking_cost(origin, destination))
        except ValueError:
            return float('inf')

    def _car_point(self, vehicle):
        site = self.runtime.fleet.sites[vehicle.site]
        lot = site.get('parking_lot')
        space = lot.space(vehicle.parking_space_id) if lot is not None else None
        return space.position if space is not None else site['walk_point']

    def start(self, person, source, destination, *, purpose='visit', returning=False):
        r = self.runtime
        plan = self.plans.get(person.id)
        at_car = False
        context = source, destination, purpose, returning
        if plan is not None and (plan['source'], plan['destination'],
                                 plan.get('purpose', 'visit'), plan.get('returning', False)) != context:
            if plan['stage'] not in ('ready', 'at_car'):
                return False
            at_car = plan['stage'] == 'at_car'
            self.plans.pop(person.id)
            plan = None
        if plan is None:
            deadline = (int(r.time//DAY)*DAY+r._shift_end(person)
                        if purpose=='commute' and not returning else r.time+DAY)
            plan = dict(source=source, destination=destination,
                        stage='at_car' if at_car else 'ready', failed={},
                        purpose=purpose, returning=returning, deadline=deadline)
            self.plans[person.id] = plan
        admitted = self._attempt(person, plan)
        if admitted:
            self.resolved(person.id)
        return admitted

    def _fallback(self, person, plan, origin):
        r = self.runtime
        destination = r.sites[plan['destination']]['walk_point']
        seconds = self._walk_cost(origin, destination, allow_bus=True)
        if seconds > r.commute_policy.fallback_trip_seconds+1e-8:
            return False
        try:
            r.transit.request_trip(person.id, origin, destination)
        except (ValueError, RuntimeError):
            return False
        plan['stage'] = 'fallback'
        r.fleet.last_dispatch_status = 'walked'
        self.counts['mode_fallbacks'] += 1
        r._note('trip_mode_fallback', person=person.id, destination=plan['destination'], planned_seconds=seconds)
        return True

    def _note_parking_recalibration(self, person, plan, reason):
        if (plan.get('purpose') != 'commute' or plan.get('returning')
                or plan.get('parking_noted')):
            return
        self.preferences.record_parking(person.id, home=plan['source'],
            workplace=plan['destination'], day=int(self.runtime.time // DAY), reason=reason)
        plan['parking_noted'] = True

    def _attempt(self, person, plan):
        r = self.runtime
        fleet = r.fleet
        vehicle = fleet.vehicles[person.car_id]
        if vehicle.phase != 'parked':
            fleet.last_dispatch_status = 'unavailable'
            return False
        source = r.sites[plan['source']]['walk_point']
        car_point = self._car_point(vehicle)
        at_car = plan['stage'] == 'at_car' or vehicle.site == plan['source']
        origin = car_point if plan['stage'] == 'at_car' else source
        if not at_car and self._walk_cost(source, car_point) > r.commute_policy.parking_walk_seconds+1e-8:
            if self._fallback(person, plan, source):
                return True
            fleet.last_dispatch_status = 'inaccessible'
            return False
        reasons = []
        # Service visits/returns have different retry semantics. Apply the new
        # quantum budget only to commutes, which already retry planning at 0.25s.
        for sid in self.options(plan['destination'], bounded=r._inside_update and plan['purpose']=='commute'):
            if sid is _OPTIONS_PENDING:
                fleet.last_dispatch_status = 'planning'
                return False
            if sid in plan['failed']:
                reasons.append(plan['failed'][sid])
                continue
            if fleet.sites[sid]['road_position'] is None or fleet.sites[vehicle.site]['road_position'] is None:
                self._note_parking_recalibration(person, plan, 'inaccessible')
                reasons.append('inaccessible')
                plan['failed'][sid] = 'inaccessible'
                continue
            space_id = fleet._available_space(vehicle, sid)
            if space_id is False:
                self._note_parking_recalibration(person, plan, 'full')
                reasons.append('full')
                continue
            lot = fleet.sites[sid].get('parking_lot')
            space = lot.space(space_id) if lot is not None else None
            if sid != plan['destination'] and space is not None and self._walk_cost(
                    space.position,r.sites[plan['destination']]['walk_point']) > r.commute_policy.parking_walk_seconds+1e-8:
                reasons.append('inaccessible')
                continue
            if fleet._lot_key(vehicle.site) == fleet._lot_key(sid):
                # Sharing a lot does not move the driver to another building.
                # Leave the car's physical address and space claim untouched.
                r.transit.request_trip(person.id, origin, r.sites[plan['destination']]['walk_point'], allow_bus=False)
                plan['stage'] = 'walk_from_car'
                fleet.last_dispatch_status = 'walked'
                return True
            if not at_car:
                r.transit.request_trip(person.id, source, car_point, allow_bus=False)
                plan['stage'] = 'walk_to_car'
                fleet.last_dispatch_status = 'walking_to_car'
                return True
            if fleet.dispatch(person.car_id, sid):
                plan['stage'], plan['parking'] = 'driving', sid
                if sid != plan['destination']:
                    self._note_parking_recalibration(person, plan, 'overflow')
                    self.counts['overflow_parking_trips'] += 1
                    r._note('parking_fallback', person=person.id, destination=plan['destination'], parking=sid)
                return True
            status = fleet.last_dispatch_status
            if status in ('planning', 'limited', 'blocked', 'unavailable'):
                return False
            reasons.append(status)
            if status in ('inaccessible', 'no_fuel'):
                plan['failed'][sid] = status
        if self._fallback(person, plan, origin):
            return True
        fleet.last_dispatch_status = 'full' if 'full' in reasons else ('no_fuel' if 'no_fuel' in reasons else 'inaccessible')
        return False

    def car_arrived(self, vehicle):
        r = self.runtime
        plan = self.plans.get(vehicle.driver)
        if plan is None or plan['stage'] != 'driving':
            return False
        point = self._car_point(vehicle)
        r.transit.record_vehicle_arrival(vehicle.driver, point)
        plan['stage'] = 'finish_walk'
        self.finish_walk(vehicle.driver)
        return True

    def finish_walk(self, pid):
        r = self.runtime
        plan = self.plans.get(pid)
        if plan is None:
            return True
        vehicle = r.fleet.vehicles[r.residents[pid].car_id]
        origin = self._car_point(vehicle)
        destination = r.sites[plan['destination']]['walk_point']
        try:
            r.transit.request_trip(pid, origin, destination, allow_bus=False)
        except (ValueError, RuntimeError):
            r.fleet.last_dispatch_status = 'inaccessible'
            self._note_parking_recalibration(r.residents[pid], plan, 'walk_access')
            self.defer(pid, 'finish_walk')
            return False
        plan['stage'] = 'walk_from_car'
        self.resolved(pid)
        return True

    def person_arrived(self, person):
        plan = self.plans.get(person.id)
        if plan is None:
            return False
        if plan['stage'] == 'walk_to_car':
            plan['stage'] = 'at_car'
            self.runtime._once('parking_resume:'+str(person.id), self.runtime.time, 'parking_resume', person.id)
            return True
        if plan['stage'] in ('walk_from_car', 'fallback'):
            self.plans.pop(person.id)
        return False

    def resume(self, pid):
        r = self.runtime
        plan = self.plans.get(pid)
        if plan is None:
            return
        if self._attempt(r.residents[pid], plan):
            self.resolved(pid)
            return
        if r.fleet.last_dispatch_status in ('full', 'inaccessible', 'no_fuel'):
            self.defer(pid, 'resume')
        else:
            r._once('parking_resume:'+str(pid), r.time+.25, 'parking_resume', pid)

    def _remove_wait(self, pid):
        wait = self.waits.pop(pid, None)
        if wait is not None:
            self.runtime.cancel_event('trip_deadline:'+str(wait['serial']))
            for key in wait['lots']:
                queue = self._lot_waiters.get(tuple(key))
                if queue is not None:
                    queue.pop(pid, None)
                    if not queue:
                        self._lot_waiters.pop(tuple(key), None)
        return wait

    def resolved(self, pid):
        self._remove_wait(pid)
        key = self._woken_lots.pop(pid, None)
        if key is not None:
            self._capacity_inflight.pop(key, None)
            self._dirty_lots.add(key)

    def defer(self, pid, kind, returning=False, *, reason=None):
        r = self.runtime
        person = r.residents[pid]
        plan = self.plans.get(pid)
        destination = plan['destination'] if plan else (person.home if returning else person.workplace)
        previous = self.waits.get(pid)
        since = previous['since'] if previous else (plan.get('waiting_since',r.time) if plan else r.time)
        self.resolved(pid)
        self._serial += 1
        reason = reason or r.fleet.last_dispatch_status or 'inaccessible'
        lots = []
        pending = False
        if reason == 'full':
            for sid in self.options(destination, bounded=r._inside_update):
                if sid is _OPTIONS_PENDING:
                    pending = True
                    break
                if r.fleet.sites[sid]['road_position'] is not None:
                    lots.append(r.fleet._lot_key(sid))
            lots = list(dict.fromkeys(lots))
        deadline = (plan['deadline'] if plan and 'deadline' in plan else
                    int(r.time//DAY)*DAY+r._shift_end(person) if kind == 'commute' and not returning else r.time+DAY)
        expired = bool(plan and plan.get('unmet'))
        wait = dict(kind=kind, returning=returning, destination=destination, reason=reason,
                    since=since, deadline=deadline, lots=lots, serial=self._serial, expired=expired)
        if plan is not None:
            plan['waiting_since']=since
        self.waits[pid] = wait
        if pending:
            # An incomplete candidate list cannot become an idle capacity wait:
            # retry the trip under the same quantum budget until it is complete.
            self._wake(pid)
            if kind == 'commute':r._pending_departures[pid]=(returning,r.time+.25)
            return
        for key in lots:
            self._lot_waiters[key][pid] = None
        r._pending_departures.pop(pid, None)
        if not expired:
            r._once('trip_deadline:'+str(self._serial), deadline, 'trip_deadline', [pid, self._serial])

    def _wake(self, pid):
        r = self.runtime
        wait = self._remove_wait(pid)
        if wait is None or pid not in r.residents:
            return
        if wait['kind'] == 'commute':
            r._pending_departures[pid] = (wait['returning'], r.time)
        elif wait['kind'] == 'resume':
            r._once('parking_resume:'+str(pid), r.time, 'parking_resume', pid)
        elif wait['kind'] == 'finish_walk':
            r._once('parking_finish:'+str(pid), r.time, 'parking_finish', pid)
        else:
            r._once('service_return:'+str(pid), r.time, 'service_return', pid)

    def wake_capacity(self):
        fleet = self.runtime.fleet
        dirty = self._dirty_lots | fleet.drain_parking_changes()
        self._dirty_lots.clear()
        for key in dirty:
            if key in self._capacity_inflight:
                continue
            for pid in tuple(self._lot_waiters.get(key, ())):
                wait = self.waits.get(pid)
                person = self.runtime.residents.get(pid)
                if wait is None or person is None or person.car_id not in fleet.vehicles:
                    self._remove_wait(pid)
                    continue
                vehicle = fleet.vehicles[person.car_id]
                # Wait keys already identify the physical lots validated when
                # the wait was registered. A capacity notification only needs
                # an indexed fitting-space check, not another walking search.
                # Actual admission revalidates eligibility under its budget.
                sid = wait['destination']
                if fleet._lot_key(sid) != key:
                    if len(key) != 2 or key[0] not in ('lot', 'site'):
                        continue
                    sid = 'parking-endpoint:'+key[1] if key[0] == 'lot' else key[1]
                if (sid in fleet.sites and fleet._lot_key(sid) == key
                        and fleet._available_space(vehicle, sid) is not False):
                    self._capacity_inflight[key] = pid
                    self._woken_lots[pid] = key
                    self._wake(pid)
                    break

    def wake_network(self):
        # Called only on authored access/geometry changes, not from idle updates.
        for plan in self.plans.values():
            if plan['stage'] in ('ready','at_car'):
                plan['failed'] = {}
        for pid in tuple(self.waits):
            self._wake(pid)
        self._capacity_inflight.clear()
        self._woken_lots.clear()

    def unmet(self, pid, destination, reason, *, since=None, recoverable=False):
        r = self.runtime
        plan = self.plans.get(pid)
        if recoverable:
            self.waits[pid]['expired']=True
            if plan is not None:
                plan['unmet']=True
                if plan.get('purpose')=='commute' and not plan.get('returning'):
                    r.residents[pid].return_due=True
        else:
            self.resolved(pid)
            r._pending_departures.pop(pid, None)
            if plan and plan['stage'] in ('ready', 'at_car', 'finish_walk'):
                self.plans.pop(pid)
        self.counts['commute_unmet'] += 1
        self.last_unmet[pid]=dict(time=r.time,destination=destination,reason=reason,
                                 wait_seconds=max(0.,r.time-(r.time if since is None else since)),
                                 recoverable=recoverable)
        r._note('trip_unmet', person=pid, destination=destination, reason=reason,
                wait_seconds=max(0., r.time-(r.time if since is None else since)), recoverable=recoverable)

    def expire(self, pid, serial):
        wait = self.waits.get(pid)
        if wait is None or wait['serial'] != serial or wait.get('expired'):
            return
        person=self.runtime.residents[pid]
        recoverable=wait['returning'] or wait['kind']!='commute' or person.state!='home'
        self.unmet(pid, wait['destination'], wait['reason'], since=wait['since'], recoverable=recoverable)

    def report(self):
        r = self.runtime
        rows = [dict(person=pid, destination=wait['destination'], parking_lots=[key[1] for key in wait['lots']],
                     reason=wait['reason'], wait_seconds=max(0., r.time-wait['since']), deadline=wait['deadline'],
                     unmet=wait.get('expired',False))
                for pid, wait in self.waits.items()]
        by_destination, by_lot = {}, {}
        def add(groups,key,row):
            group=groups.setdefault(key,dict(count=0,total_wait_seconds=0.,max_wait_seconds=0.,reasons=Counter()))
            group['count']+=1
            group['total_wait_seconds']+=row['wait_seconds']
            group['max_wait_seconds']=max(group['max_wait_seconds'],row['wait_seconds'])
            group['reasons'][row['reason']]+=1
        for row in rows:
            add(by_destination,row['destination'],row)
            for key in row['parking_lots']:add(by_lot,key,row)
        return dict(commute_unmet=self.counts['commute_unmet'], mode_fallbacks=self.counts['mode_fallbacks'],
                    overflow_parking_trips=self.counts['overflow_parking_trips'], blocked_trips=rows,
                    stranded_trips=sum(row['unmet'] for row in rows),
                    blocked_by_destination=by_destination, blocked_by_parking_lot=by_lot,
                    last_unmet_trips=deepcopy(self.last_unmet))

    def snapshot(self):
        return dict(plans=deepcopy(self.plans), waits=deepcopy(self.waits), counts=dict(self.counts),
                    last_unmet=deepcopy(self.last_unmet), serial=self._serial,
                    preferences=self.preferences.to_dict())

    def restore(self, data):
        r = self.runtime
        preferences = CommutePreferences.from_dict(data.get('preferences', {}),
            resident_ids=r.residents, max_day=int(r.time // DAY))
        plans = {int(pid):deepcopy(plan) for pid, plan in data.get('plans', {}).items()}
        waits = {int(pid):deepcopy(wait) for pid, wait in data.get('waits', {}).items()}
        stages = {'ready', 'at_car', 'walk_to_car', 'driving', 'finish_walk', 'walk_from_car', 'fallback'}
        for pid, plan in plans.items():
            if (pid not in r.residents or plan['source'] not in r.sites or plan['destination'] not in r.sites
                    or plan['stage'] not in stages or not isinstance(plan.get('failed', {}), dict)):
                raise ValueError('Invalid saved parking journey')
            if 'deadline' in plan and (not isfinite(plan['deadline']) or plan['deadline']<0):
                raise ValueError('Invalid saved parking journey deadline')
        for pid, wait in waits.items():
            if (pid not in r.residents or wait['destination'] not in r.sites
                    or wait['kind'] not in ('commute', 'resume', 'finish_walk', 'service_return')
                    or not isinstance(wait['returning'], bool)
                    or any(not isfinite(wait[k]) or wait[k] < 0 for k in ('since', 'deadline'))):
                raise ValueError('Invalid saved blocked trip')
            wait['lots'] = [tuple(key) for key in wait['lots']]
        self.plans, self.waits = plans, waits
        # Old saves may contain deadlines for waits which have since resolved.
        for event in tuple(r._events):
            if event[2]!='trip_deadline':continue
            pid,serial=event[3][1]
            wait=waits.get(pid)
            if wait is None or wait['serial']!=serial or wait.get('expired'):
                r.cancel_event(event[3][0])
        self.preferences = preferences
        self.counts = Counter(data.get('counts', {}))
        self.last_unmet = {int(pid):deepcopy(outcome) for pid,outcome in data.get('last_unmet',{}).items()}
        self._serial = int(data.get('serial', 0))
        self._lot_waiters.clear()
        for pid, wait in waits.items():
            for key in wait['lots']:
                self._lot_waiters[key][pid] = None
                # A save may occur after the capacity release but before the
                # next update consumes its notification. Check these lots once.
                self._dirty_lots.add(key)
