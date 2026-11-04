"""Physical vehicle records outlive their transient native road actors."""
from dataclasses import dataclass, field
from math import isfinite,dist
from types import SimpleNamespace
from mobility import nearest_lane_position, vehicle_route_points,LaneTraversal
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
    _actor: object = field(default=None, repr=False)
    _last: float = field(default=0.0, repr=False)


class PersistentFleet:
    def __init__(self, transit, sites):
        self.transit, self.sites = transit, sites
        self.vehicles, self.routes = {}, {}
        self.arrivals = []
        self.routing=None
        self.background=False
        self.admission=None
        self.last_dispatch_status=None
        self._travel={}

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

    def _lot_key(self, site):
        lot = self.sites[site].get('parking_lot')
        return ('lot', lot.id) if lot is not None else ('site', site)

    def parked_at(self, site):
        key = self._lot_key(site)
        return sum(self._lot_key(v.site) == key and v.phase not in ('driving', 'waiting_for_parking')
                   for v in self.vehicles.values())

    def _available_space(self, vehicle, site):
        """Return a fitting free ID, None for legacy capacity, or False if full."""
        lot = self.sites[site].get('parking_lot')
        if lot is None:
            return None if self.parked_at(site) < self.sites[site]['parking_capacity'] else False
        key = self._lot_key(site)
        used = set()
        for other in self.vehicles.values():
            if other.id == vehicle.id:
                continue
            if self._lot_key(other.site) == key and other.parking_space_id:
                used.add(other.parking_space_id)
            reserved_site = other.destination or other.site
            if reserved_site in self.sites and self._lot_key(reserved_site) == key and other.reserved_space_id:
                used.add(other.reserved_space_id)
        # Cars use the smallest fitting space, keeping delivery bays available.
        space = min((s for s in lot.spaces if s.id not in used and s.fits(vehicle.length, vehicle.width)),
                    key=lambda s: (s.length*s.width, s.id), default=None)
        return space.id if space is not None else False

    def parked_vehicles(self):
        """Expose parked actors through the same dimensions/pose contract as traffic."""
        for vehicle in self.vehicles.values():
            if vehicle.phase in ('driving', 'waiting_for_parking'):
                continue
            lot = self.sites[vehicle.site].get('parking_lot')
            space = lot.space(vehicle.parking_space_id) if lot else None
            if space is None:
                continue
            yield SimpleNamespace(id=vehicle.id, position=space.position, heading=space.heading,
                                  length=vehicle.length, width=vehicle.width, color='#527fa5',
                                  elevation=0.0, parked=True, source_type=vehicle.kind,
                                  appearance=self._appearance(vehicle))

    @staticmethod
    def _appearance(vehicle):
        return VehicleAppearance(kind=vehicle.kind,
            shape='material_truck' if vehicle.kind == 'truck' else 'car',
            cargo_key=next(iter(vehicle.cargo),None),
            load_fraction=min(1,sum(vehicle.cargo.values())/vehicle.capacity) if vehicle.capacity else 0)

    def restore_parking(self, *, legacy_ids=(), suspended_ids=()):
        """Validate all saved claims together; migrate old count-only vehicles."""
        used = set()
        # Old count-only saves may already have traffic heading to a full lot.
        # Keep stationary vehicles in place before allocating inbound claims.
        for v in sorted(self.vehicles.values(), key=lambda vehicle:vehicle.phase == 'driving'):
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
                    and self.sites[v.site].get('parking_lot') is not None and v.parking_space_id is None):
                raise ValueError('Parked vehicle needs a parking space claim')
            # An old in-flight trip can arrive without a reservation and wait.
            # New departures always reserve through dispatch().

    def dispatch(self, vehicle_id, destination, *, origin_point=None):
        self.last_dispatch_status='unavailable'
        v = self.vehicles[vehicle_id]
        if v.phase != 'parked' or destination not in self.sites:
            return False
        if destination == v.site and origin_point is None:
            raise ValueError('Vehicle already at destination')
        if origin_point is None and self._lot_key(v.site) == self._lot_key(destination):
            v.site = destination
            self.arrivals.append(v.id)
            return True
        space = self._available_space(v, destination)
        if space is False:
            self.last_dispatch_status='full'
            return False
        if self.sites[destination]['road_position'] is None or self.sites[v.site]['road_position'] is None:
            return False
        key = (v.site, destination, None if origin_point is None else tuple(origin_point))
        if key not in self.routes or self.routing is not None:
            def accesses(site):
                authored = self.sites[site]['road_position']
                road = next(r for r in self.transit.city.roads if r.id == authored.lane.road_id)
                return [nearest_lane_position(lane, authored.point)[0] for lane in road.lanes]
            origins = accesses(v.site)
            if origin_point is not None:
                positions = [(nearest_lane_position(lane, origin_point), road) for road in self.transit.city.roads for lane in road.lanes]
                if not positions:return False
                nearest = min(positions, key=lambda x:x[0][1])[1]
                origins = [nearest_lane_position(lane,origin_point)[0] for lane in nearest.lanes]
            if self.routing is not None:
                from commute_routing import PENDING
                route=self.routing.get_route(v.id,v.site,destination,origins,accesses(destination),
                    day=int(self.transit.time//86400),blocking=not self.background)
                if route is PENDING:
                    self.last_dispatch_status='planning';return False
                self.routes[key]=route
            else:
                candidates = [self.transit.city.find_vehicle_route_between(a, b)
                              for a in origins for b in accesses(destination)]
                candidates = [r for r in candidates if r is not None]
                self.routes[key] = min(candidates, key=lambda r:r.cost, default=None)
        route = self.routes[key]
        if route is None:
            return False
        length = polyline_length(list(vehicle_route_points(route)))
        if v.fuel_liters + 1e-9 < length/5280*v.liters_per_mile:
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
            return False
        v.parking_space_id, v.reserved_space_id = None, space
        v._actor, v._last, v.destination, v.phase = actor, 0.0, destination, 'driving'
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
        completed = {c.id for c in self.transit.vehicle_arrivals}
        self.transit.vehicle_arrivals.clear()
        for v in self.vehicles.values():
            if v.phase != 'driving':
                continue
            if self.routing is not None:self._observe_trip(v)
            delta = max(0, v._actor.distance-v._last)
            v.distance_feet += delta
            v.fuel_liters = max(0, v.fuel_liters-delta/5280*v.liters_per_mile)
            v._last = v._actor.distance
            if v.id in completed:
                self._travel.pop(v.id,None)
                if self.routing is not None:self.routing.learning.finish(v.id)
                v.site, v.destination, v._actor = v.destination, None, None
                v.phase, v.trips = 'waiting_for_parking', v.trips+1
        for v in self.vehicles.values():
            if v.phase != 'waiting_for_parking':
                continue
            space = v.reserved_space_id or self._available_space(v, v.site)
            if space is not False:
                v.parking_space_id, v.reserved_space_id = space, None
                v.phase = 'parked'
                self.arrivals.append(v.id)
