"""Physical vehicle records outlive their transient native road actors."""
from collections import Counter
from retention import BoundedCache
from dataclasses import dataclass, field
from math import isfinite,dist,hypot
from types import SimpleNamespace
from mobility import nearest_lane_position, vehicle_route_points,LaneTraversal,lane_position_at_distance
from models import polyline_length
from vehicle import VehicleAppearance


@dataclass
class FleetVehicle:
    id: str
    kind: str
    site: str
    fuel_liters: float = 50.0
    capacity: float = 0.0
    liters_per_mile: float = .12
    length: float = 15.0
    width: float = 6.0
    phase: str = 'parked'
    cargo: dict = field(default_factory=dict)
    driver: int | None = None
    destination: str | None = None
    trips: int = 0
    distance_feet: float = 0.0
    truck_spec_id: str = 'material_truck'
    parking_space_id: str | None = None
    reserved_space_id: str | None = None
    road_stop_lane_id: str | None = None
    road_stop_distance: float | None = None
    reserved_road_stop_lane_id: str | None = None
    reserved_road_stop_distance: float | None = None
    road_stop_position: tuple | None = None
    road_stop_heading: tuple | None = None
    _actor: object = field(default=None, repr=False)
    _last: float = field(default=0.0, repr=False)

    _INDEX_FIELDS = frozenset(('site', 'destination', 'phase',
                              'parking_space_id', 'reserved_space_id',
                              'road_stop_lane_id', 'road_stop_distance',
                              'reserved_road_stop_lane_id', 'reserved_road_stop_distance'))

    def __setattr__(self, name, value):
        previous = self.__dict__.get(name)
        object.__setattr__(self, name, value)
        if name in self._INDEX_FIELDS and previous != value:
            changed = self.__dict__.get('_on_fleet_change')
            if changed is not None:
                changed(self.id)


@dataclass(frozen=True)
class _VehicleIndex:
    vehicle: FleetVehicle = field(compare=False)
    driving: bool
    parked_key: tuple | None
    waiting_key: tuple | None
    claims: frozenset
    legacy_reservation: tuple | None


class PersistentFleet:
    def __init__(self, transit, sites):
        self.transit, self.sites = transit, sites
        self.vehicles, self.routes = {}, BoundedCache()
        self.arrivals = []
        self.routing=None
        self.background=False
        self.admission=None
        self.last_dispatch_status=None
        self._travel={}
        self._driving = {}
        self._waiting = {}
        self._claims = {}
        self._parked_counts = Counter()
        self._reserved_counts = Counter()
        self._indexed = {}
        self._dirty_vehicles = set()
        self._parking_ready = set()
        self._parking_changes = set()
        self._lane_revision = None
        self._lanes_by_id = {}

    def add(self, vehicle):
        if not vehicle.id or vehicle.id in self.vehicles or vehicle.site not in self.sites:
            raise ValueError('Vehicle needs a unique ID and known parking site')
        if any(not isfinite(x) or x < 0 for x in (vehicle.fuel_liters, vehicle.capacity, vehicle.liters_per_mile)):
            raise ValueError('Vehicle fuel and capacity must be finite and nonnegative')
        if any(not isfinite(x) or x <= 0 for x in (vehicle.length, vehicle.width)):
            raise ValueError('Vehicle dimensions must be finite and positive')
        space = self._available_space(vehicle, vehicle.site)
        if space is False:
            raise ValueError('No initial parking space')
        vehicle.parking_space_id = space
        self.vehicles[vehicle.id] = vehicle
        self.vehicle_changed(vehicle.id)

    def _lot_key(self, site):
        lot = self.sites[site].get('parking_lot')
        return ('lot', lot.id) if lot is not None else ('site', site)

    def parked_at(self, site):
        self._ensure_indexes()
        return self._parked_counts[self._lot_key(site)]

    def _index_entry(self, vehicle):
        key = self._lot_key(vehicle.site) if vehicle.site in self.sites else None
        destination = vehicle.destination or vehicle.site
        target = self._lot_key(destination) if destination in self.sites else None
        driving = vehicle.phase == 'driving'
        waiting = vehicle.phase == 'waiting_for_parking'
        # A suspended road actor has no origin stall. It retains only its
        # destination reservation until rebind_transport can resume its trip.
        parked = (not driving and not waiting and key is not None and
                  vehicle.road_stop_lane_id is None and
                  (vehicle.parking_space_id is not None or
                   (key[0] == 'site' and vehicle.destination is None)))
        claims = frozenset((lot, ident) for lot, ident in (
            (key, vehicle.parking_space_id), (target, vehicle.reserved_space_id))
            if lot is not None and ident is not None)
        legacy = (target if vehicle.destination is not None and target is not None
                  and target[0] == 'site' and vehicle.reserved_road_stop_lane_id is None else None)
        return _VehicleIndex(vehicle, driving, key if parked else None,
                             key if waiting else None, claims, legacy)

    def _insert_index(self, entry):
        ident = entry.vehicle.id
        self._indexed[ident] = entry
        object.__setattr__(entry.vehicle, '_on_fleet_change', self._dirty_vehicles.add)
        if entry.driving:
            self._driving[ident] = entry.vehicle
        if entry.parked_key is not None:
            self._parked_counts[entry.parked_key] += 1
        if entry.waiting_key is not None:
            self._waiting.setdefault(entry.waiting_key, {})[ident] = entry.vehicle
            self._parking_ready.add(entry.waiting_key)
        if entry.legacy_reservation is not None:
            self._reserved_counts[entry.legacy_reservation] += 1
        for key, space in entry.claims:
            self._claims.setdefault(key, {})[space] = ident

    def _remove_index(self, entry):
        ident = entry.vehicle.id
        self._driving.pop(ident, None)
        if entry.parked_key is not None:
            self._parked_counts[entry.parked_key] -= 1
        if entry.waiting_key is not None:
            waiting = self._waiting[entry.waiting_key]
            waiting.pop(ident, None)
            if not waiting:
                del self._waiting[entry.waiting_key]
        if entry.legacy_reservation is not None:
            self._reserved_counts[entry.legacy_reservation] -= 1
        for key, space in entry.claims:
            claims = self._claims[key]
            if claims.get(space) == ident:
                del claims[space]
            if not claims:
                del self._claims[key]

    def _released_capacity(self, previous, current):
        if previous is None:
            return
        claims = current.claims if current is not None else frozenset()
        released = {key for key, _ in previous.claims - claims}
        old_legacy = Counter(key for key in (previous.parked_key, previous.legacy_reservation)
                             if key is not None and key[0] == 'site')
        new_legacy = Counter(key for key in (current.parked_key, current.legacy_reservation)
                             if key is not None and key[0] == 'site') if current else Counter()
        released.update(old_legacy - new_legacy)
        self._parking_changes.update(released)
        self._parking_ready.update(released)

    def vehicle_changed(self, vehicle_id):
        """Refresh one changed record; bulk editors may call rebuild_indexes()."""
        self._dirty_vehicles.discard(vehicle_id)
        previous = self._indexed.get(vehicle_id)
        vehicle = self.vehicles.get(vehicle_id)
        current = self._index_entry(vehicle) if vehicle is not None else None
        if previous == current and (previous is None or previous.vehicle is vehicle):
            return
        if previous is not None:
            self._remove_index(previous)
            self._indexed.pop(vehicle_id, None)
        if current is not None:
            self._insert_index(current)
        self._released_capacity(previous, current)

    def _ensure_indexes(self):
        # Save loading and a few legacy callers insert records directly. This
        # length check is constant work; a bulk mutation pays for one rebuild.
        if len(self.vehicles) != len(self._indexed):
            self.rebuild_indexes()
        while self._dirty_vehicles:
            self.vehicle_changed(self._dirty_vehicles.pop())

    def rebuild_indexes(self):
        """Rebuild derived state after loading, editing sites, or road rebinding."""
        previous = self._indexed.copy()
        self._indexed.clear()
        self._driving.clear()
        self._waiting.clear()
        self._claims.clear()
        self._parked_counts.clear()
        self._reserved_counts.clear()
        self._parking_ready.clear()
        for vehicle in self.vehicles.values():
            self._insert_index(self._index_entry(vehicle))
        self._dirty_vehicles.clear()
        for ident, entry in previous.items():
            self._released_capacity(entry, self._indexed.get(ident))

    def notify_parking_changed(self, site):
        """Wake this lot after an externally edited capacity or parking layout."""
        key = self._lot_key(site)
        self._parking_changes.add(key)
        self._parking_ready.add(key)

    def drain_parking_changes(self):
        """Consume coalesced capacity releases for blocked trip queues."""
        self._ensure_indexes()
        changes = self._parking_changes
        self._parking_changes = set()
        return changes

    def _available_space(self, vehicle, site):
        """Return a fitting free ID, None for legacy capacity, or False if full."""
        self._ensure_indexes()
        lot = self.sites[site].get('parking_lot')
        key = self._lot_key(site)
        if lot is None:
            used = self._parked_counts[key] + self._reserved_counts[key]
            own = self._indexed.get(vehicle.id)
            if own is not None:
                used -= (own.parked_key == key) + (own.legacy_reservation == key)
            return None if used < self.sites[site]['parking_capacity'] else False
        claims = self._claims.get(key, {})
        # Cars use the smallest fitting space, keeping delivery bays available.
        space = min((s for s in lot.spaces if claims.get(s.id, vehicle.id) == vehicle.id
                     and s.fits(vehicle.length, vehicle.width)),
                    key=lambda s: (s.length*s.width, s.id), default=None)
        return space.id if space is not None else False

    def parked_vehicles(self):
        """Expose parked actors through the same dimensions/pose contract as traffic."""
        for vehicle in self.vehicles.values():
            if vehicle.phase in ('driving', 'waiting_for_parking'):
                continue
            if vehicle.road_stop_lane_id is not None:
                position, heading = vehicle.road_stop_position, vehicle.road_stop_heading
                if position is None or heading is None:
                    continue
            else:
                lot = self.sites[vehicle.site].get('parking_lot')
                space = lot.space(vehicle.parking_space_id) if lot else None
                if space is None:
                    continue
                position, heading = space.position, space.heading
            yield SimpleNamespace(id=vehicle.id, position=position, heading=heading,
                                  length=vehicle.length, width=vehicle.width, color='#527fa5',
                                  elevation=0.0, parked=True, source_type=vehicle.kind,
                                  appearance=self._appearance(vehicle))

    @staticmethod
    def _appearance(vehicle):
        return VehicleAppearance(kind=vehicle.kind,
            shape='material_truck' if vehicle.kind == 'truck' else 'car',
            cargo_key=next(iter(vehicle.cargo),None),
            load_fraction=min(1,sum(vehicle.cargo.values())/vehicle.capacity) if vehicle.capacity else 0)

    def _road_lanes(self):
        city = self.transit.city
        if self._lane_revision != city.mobility_revision:
            self._lanes_by_id = {lane.id: lane for road in city.roads for lane in road.lanes}
            self._lane_revision = city.mobility_revision
        return self._lanes_by_id

    def _road_stop_position(self, vehicle):
        """Return a still-valid exact stop, or None for a suspended road edit."""
        from truck_stops import LaneObstacle, loading_position
        lane = self._road_lanes().get(vehicle.road_stop_lane_id)
        distance = vehicle.road_stop_distance
        if lane is None or distance is None or not isfinite(distance):
            return None
        if distance < 0 or distance > polyline_length(lane.points):
            return None
        position = lane_position_at_distance(lane, distance)
        interior = loading_position(position, vehicle.length)
        if interior is None or abs(interior.distance-distance) > 1e-6:
            return None
        try:
            obstacle = LaneObstacle(vehicle.id, position, vehicle.length, vehicle.width,
                                    heading=vehicle.road_stop_heading)
        except ValueError:
            return None
        if (vehicle.road_stop_position is not None and
                dist(vehicle.road_stop_position, obstacle.position) > 1e-6):
            return None
        return position

    def _validate_road_stop(self, vehicle, suspended_ids):
        occupied = vehicle.road_stop_lane_id is not None
        reserved = vehicle.reserved_road_stop_lane_id is not None
        for lane, distance in ((vehicle.road_stop_lane_id, vehicle.road_stop_distance),
                               (vehicle.reserved_road_stop_lane_id, vehicle.reserved_road_stop_distance)):
            if (lane is None) != (distance is None):
                raise ValueError('Road stop needs both a lane and a distance')
            if lane is not None and (not isinstance(lane, str) or not lane or
                    not isinstance(distance, (int, float)) or not isfinite(distance) or distance < 0):
                raise ValueError('Invalid road stop position')
        if (occupied or reserved) and vehicle.kind != 'truck':
            raise ValueError('Only trucks may occupy a loading road stop')
        if occupied:
            if (vehicle.phase in ('driving', 'waiting_for_parking') or
                    vehicle.parking_space_id is not None or vehicle.reserved_space_id is not None or
                    vehicle.destination is not None):
                raise ValueError('Road stop conflicts with vehicle parking state')
            pose = vehicle.road_stop_position, vehicle.road_stop_heading
            if any(value is not None and (not isinstance(value, (list, tuple)) or len(value) != 2
                    or any(not isinstance(n, (int, float)) or not isfinite(n) for n in value)) for value in pose):
                raise ValueError('Invalid saved road stop pose')
            if vehicle.road_stop_heading is not None and abs(hypot(*vehicle.road_stop_heading)-1) > 1e-6:
                raise ValueError('Invalid saved road stop heading')
            if any(value is None for value in pose):
                from truck_stops import LaneObstacle
                position = self._road_stop_position(vehicle)
                if position is None:
                    raise ValueError('Suspended road stop needs its saved physical pose')
                obstacle = LaneObstacle(vehicle.id, position, vehicle.length, vehicle.width,
                                        heading=vehicle.road_stop_heading)
                vehicle.road_stop_position, vehicle.road_stop_heading = obstacle.position, obstacle.heading
            else:
                vehicle.road_stop_position = tuple(vehicle.road_stop_position)
                vehicle.road_stop_heading = tuple(vehicle.road_stop_heading)
        elif vehicle.road_stop_position is not None or vehicle.road_stop_heading is not None:
            raise ValueError('Saved road stop pose needs a stopped vehicle')
        if reserved and (vehicle.reserved_space_id is not None or occupied or
                (vehicle.phase != 'driving' and vehicle.id not in suspended_ids)):
            raise ValueError('Road stop reservation conflicts with vehicle state')

    def restore_road_stops(self):
        """Restore physical lane bodies and pending arrival holds after rebinding."""
        for vehicle in self.vehicles.values():
            if vehicle.road_stop_lane_id is not None:
                position = self._road_stop_position(vehicle)
                if position is not None:
                    self.transit.traffic.set_lane_obstacle(vehicle.id, position,
                        length=vehicle.length, width=vehicle.width, heading=vehicle.road_stop_heading)
            elif vehicle.phase == 'driving' and vehicle.reserved_road_stop_lane_id is not None:
                position = self.transit.traffic.stop_vehicle_at_route_end(vehicle.id)
                if (position.lane.id != vehicle.reserved_road_stop_lane_id or
                        abs(position.distance-vehicle.reserved_road_stop_distance) > 1e-6):
                    raise ValueError('Road stop reservation does not match its route endpoint')

    def restore_parking(self, *, legacy_ids=(), suspended_ids=()):
        """Validate all saved claims together; migrate old count-only vehicles."""
        self.rebuild_indexes()
        used = set()
        # Old count-only saves may already have traffic heading to a full lot.
        # Keep stationary vehicles in place before allocating inbound claims.
        for v in sorted(self.vehicles.values(), key=lambda vehicle:vehicle.phase == 'driving'):
            self._validate_road_stop(v, suspended_ids)
            if v.id in legacy_ids:
                target = v.destination if v.phase == 'driving' else v.site
                space = self._available_space(v, target)
                if space is False:
                    if v.phase != 'driving':
                        v.phase = 'waiting_for_parking'
                    continue
                if v.phase == 'driving': v.reserved_space_id = space
                else: v.parking_space_id = space
            for site, ident in ((v.site, v.parking_space_id), (v.destination, v.reserved_space_id)):
                if ident is None:
                    continue
                if site not in self.sites:
                    raise ValueError('Parking claim has an unknown building')
                lot = self.sites[site].get('parking_lot')
                space = lot.space(ident) if lot else None
                key = (self._lot_key(site), ident)
                if space is None or not space.fits(v.length, v.width) or key in used:
                    raise ValueError('Invalid or duplicate parking space claim')
                used.add(key)
            if v.phase == 'driving' and v.parking_space_id:
                raise ValueError('Driving vehicle cannot occupy a parking space')
            if (v.phase not in ('driving','waiting_for_parking') and v.id not in suspended_ids
                    and self.sites[v.site].get('parking_lot') is not None and v.parking_space_id is None
                    and v.road_stop_lane_id is None):
                raise ValueError('Parked vehicle needs a parking space claim')
            # An old in-flight trip can arrive without a reservation and wait.
            # New departures always reserve through dispatch().
        self.rebuild_indexes()

    def dispatch(self, vehicle_id, destination, *, origin_point=None):
        self.last_dispatch_status='unavailable'
        v = self.vehicles[vehicle_id]
        if v.phase != 'parked' or destination not in self.sites:
            return False
        stopped = self._road_stop_position(v) if v.road_stop_lane_id is not None else None
        if v.road_stop_lane_id is not None and stopped is None:
            self.last_dispatch_status = 'inaccessible'
            return False
        if destination == v.site and origin_point is None:
            raise ValueError('Vehicle already at destination')
        if origin_point is None and stopped is None and self._lot_key(v.site) == self._lot_key(destination):
            v.site = destination
            self.vehicle_changed(v.id)
            self.last_dispatch_status = 'departed'
            self.arrivals.append(v.id)
            return True
        space = self._available_space(v, destination)
        lot = self.sites[destination].get('parking_lot')
        has_bay = (any(s.fits(v.length, v.width) for s in lot.spaces) if lot is not None
                   else self.sites[destination]['parking_capacity'] > 0)
        roadside = space is False and v.kind == 'truck' and not has_bay
        if space is False and not roadside:
            self.last_dispatch_status='full'
            return False
        if (self.sites[destination]['road_position'] is None or
                (stopped is None and origin_point is None and self.sites[v.site]['road_position'] is None)):
            self.last_dispatch_status = 'inaccessible'
            return False
        key = (self.transit.city.mobility_revision, v.site, destination,
               None if origin_point is None else tuple(origin_point),
               (stopped.lane.id, stopped.distance) if stopped is not None else None,
               (v.length, v.width) if roadside else None)
        if key not in self.routes or self.routing is not None:
            def accesses(site):
                authored = self.sites[site]['road_position']
                if authored is None:
                    return []
                road = next((r for r in self.transit.city.roads if r.id == authored.lane.road_id), None)
                if road is None:
                    return []
                return [nearest_lane_position(lane, authored.point)[0] for lane in road.lanes]
            origins = [stopped] if stopped is not None else accesses(v.site)
            if origin_point is not None and stopped is None:
                positions = [(nearest_lane_position(lane, origin_point), road) for road in self.transit.city.roads for lane in road.lanes]
                if not positions:
                    self.last_dispatch_status = 'inaccessible';return False
                nearest = min(positions, key=lambda x:x[0][1])[1]
                origins = [nearest_lane_position(lane,origin_point)[0] for lane in nearest.lanes]
            targets = accesses(destination)
            if roadside:
                from truck_stops import loading_position
                targets = [p for position in targets if (p := loading_position(position, v.length)) is not None]
            if not origins or not targets:
                self.last_dispatch_status = 'inaccessible';return False
            if self.routing is not None:
                from commute_routing import PENDING
                route=self.routing.get_route(v.id,v.site,destination,origins,targets,
                    day=int(self.transit.time//86400),blocking=not self.background)
                if route is PENDING:
                    self.last_dispatch_status='planning';return False
                self.routes[key]=route
            else:
                candidates = [self.transit.city.find_vehicle_route_between(a, b)
                              for a in origins for b in targets]
                candidates = [r for r in candidates if r is not None]
                self.routes[key] = min(candidates, key=lambda r:r.cost, default=None)
        route = self.routes[key]
        if route is None:
            self.last_dispatch_status = 'inaccessible'
            return False
        road_stop = None
        if roadside:
            from truck_stops import route_end_position
            road_stop = route_end_position(route)
            if road_stop is None:
                self.last_dispatch_status = 'inaccessible'
                return False
        length = polyline_length(vehicle_route_points(route))
        if v.fuel_liters + 1e-9 < length/5280*v.liters_per_mile:
            self.last_dispatch_status = 'no_fuel'
            return False
        if sum(v.cargo.values()) > v.capacity + 1e-8:
            raise ValueError('Vehicle cargo exceeds capacity')
        if self.background and self.admission is not None and not self.admission.available(
                self.transit.time,self._lot_key(v.site),len(self.transit.traffic.cars)):
            self.last_dispatch_status='limited';return False
        actor = self.transit.traffic.admit_route(route, vehicle_id=v.id, source_id=v.site,
                   destination_id=destination, source_type=v.kind,
                   appearance=self._appearance(v),
                   length=v.length, width=v.width, speed_cap_mph=None)
        if actor is None:
            self.last_dispatch_status = 'blocked'
            return False
        if roadside:
            self.transit.traffic.stop_vehicle_at_route_end(v.id)
        v.parking_space_id, v.reserved_space_id = None, None if roadside else space
        v.road_stop_lane_id = v.road_stop_distance = None
        v.road_stop_position = v.road_stop_heading = None
        v.reserved_road_stop_lane_id = road_stop.lane.id if road_stop is not None else None
        v.reserved_road_stop_distance = road_stop.distance if road_stop is not None else None
        v._actor, v._last, v.destination, v.phase = actor, 0.0, destination, 'driving'
        self.vehicle_changed(v.id)
        self.last_dispatch_status='departed'
        if self.background and self.admission is not None:self.admission.consume(self.transit.time,self._lot_key(v.site))
        if self.routing is not None:self._track_trip(v,route)
        return True

    def _track_trip(self,vehicle,route,*,saved=None):
        from commute_routing import link_key,link_points
        boundaries=[];distance=0.;last=None
        for link in route.edges:
            points=link_points(link)
            if not points:continue
            length=polyline_length(points)+(dist(last,points[0]) if last is not None else 0.)
            distance+=length;last=points[-1]
            if length<=1e-8:continue
            full=polyline_length(link.value.lane.points) if isinstance(link.value,LaneTraversal) else length
            boundaries.append((distance,link_key(link),full/length))
        state=dict(segments=boundaries,cursor=0,entered=self.transit.time,
                   previous_time=self.transit.time,previous_distance=0.)
        if saved is not None:state.update(saved,segments=boundaries)
        elif vehicle._actor.distance>0:
            state['previous_distance']=vehicle._actor.distance
            while state['cursor']<len(boundaries) and boundaries[state['cursor']][0]<=vehicle._actor.distance:
                state['cursor']+=1
        self._travel[vehicle.id]=state
        self.routing.learning.track(vehicle.id,[row[1] for row in boundaries[state['cursor']:]])

    def _observe_trip(self,vehicle):
        state=self._travel.get(vehicle.id)
        if state is None:return
        now=self.transit.time;distance=vehicle._actor.distance
        change=distance-state['previous_distance'];elapsed=now-state['previous_time']
        while state['cursor']<len(state['segments']):
            boundary,key,factor=state['segments'][state['cursor']]
            if boundary>distance+1e-7:break
            crossed=now-(distance-boundary)/change*elapsed if change>1e-9 else now
            crossed=max(state['entered'],min(now,crossed))
            self.routing.learning.record(key,(crossed-state['entered'])*factor,day=int(crossed//86400))
            self.routing.learning.passed(vehicle.id,key)
            state['entered']=crossed;state['cursor']+=1
        state['previous_time']=now;state['previous_distance']=distance

    def observe(self):
        self._ensure_indexes()
        completed = {c.id for c in self.transit.vehicle_arrivals}
        self.transit.vehicle_arrivals.clear()
        for v in tuple(self._driving.values()):
            if self.routing is not None:self._observe_trip(v)
            delta = max(0, v._actor.distance-v._last)
            v.distance_feet += delta
            v.fuel_liters = max(0, v.fuel_liters-delta/5280*v.liters_per_mile)
            v._last = v._actor.distance
            if v.id in completed:
                self._travel.pop(v.id,None)
                if self.routing is not None:self.routing.learning.finish(v.id)
                roadside = v.reserved_road_stop_lane_id is not None
                entry = self._indexed[v.id]
                has_space = v.reserved_space_id is not None or (
                    entry.legacy_reservation is not None and
                    self._parked_counts[entry.legacy_reservation] < self.sites[v.destination]['parking_capacity'])
                if roadside:
                    v.road_stop_lane_id, v.road_stop_distance = v.reserved_road_stop_lane_id, v.reserved_road_stop_distance
                    v.road_stop_position, v.road_stop_heading = tuple(v._actor.position), tuple(v._actor.heading)
                    v.reserved_road_stop_lane_id = v.reserved_road_stop_distance = None
                elif has_space:
                    # Transfer the claim atomically so a full lot does not
                    # advertise capacity while a reservation becomes occupied.
                    v.parking_space_id, v.reserved_space_id = v.reserved_space_id, None
                v.site, v.destination, v._actor = v.destination, None, None
                v.phase, v.trips = ('parked' if roadside or has_space else 'waiting_for_parking'), v.trips+1
                self.vehicle_changed(v.id)
                if roadside or has_space:
                    self.arrivals.append(v.id)
                    continue
                # Convert an arriving reservation before older unreserved
                # waiters can claim a count-only site's newly arrived slot.
                self._park_waiting(v)
        ready, self._parking_ready = self._parking_ready, set()
        for key in ready:
            for v in tuple(self._waiting.get(key, {}).values()):
                self._park_waiting(v)

    def _park_waiting(self, vehicle):
        space = vehicle.reserved_space_id or self._available_space(vehicle, vehicle.site)
        if space is not False:
            vehicle.parking_space_id, vehicle.reserved_space_id = space, None
            vehicle.phase = 'parked'
            self.vehicle_changed(vehicle.id)
            self.arrivals.append(vehicle.id)
