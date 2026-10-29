"""Physical vehicle records outlive their transient native road actors."""
from dataclasses import dataclass, field
from math import isfinite
from mobility import nearest_lane_position, vehicle_route_points
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
    _actor: object = field(default=None, repr=False)
    _last: float = field(default=0.0, repr=False)


class PersistentFleet:
    def __init__(self, transit, sites):
        self.transit, self.sites = transit, sites
        self.vehicles, self.routes = {}, {}
        self.arrivals = []

    def add(self, vehicle):
        if not vehicle.id or vehicle.id in self.vehicles or vehicle.site not in self.sites:
            raise ValueError('Vehicle needs a unique ID and known parking site')
        if any(not isfinite(x) or x < 0 for x in (vehicle.fuel_liters, vehicle.capacity, vehicle.liters_per_mile)):
            raise ValueError('Vehicle fuel and capacity must be finite and nonnegative')
        if self.parked_at(vehicle.site) >= self.sites[vehicle.site]['parking_capacity']:
            raise ValueError('No initial parking space')
        self.vehicles[vehicle.id] = vehicle

    def parked_at(self, site):
        return sum(v.site == site and v.phase != 'driving' and v.phase != 'waiting_for_parking'
                   for v in self.vehicles.values())

    def dispatch(self, vehicle_id, destination, *, origin_point=None):
        v = self.vehicles[vehicle_id]
        if v.phase != 'parked' or destination not in self.sites:
            return False
        if self.sites[destination]['road_position'] is None or self.sites[v.site]['road_position'] is None:
            return False
        if destination == v.site and origin_point is None:
            raise ValueError('Vehicle already at destination')
        key = (v.site, destination, None if origin_point is None else tuple(origin_point))
        if key not in self.routes:
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
        actor = self.transit.traffic.admit_route(route, vehicle_id=v.id, source_id=v.site,
                   destination_id=destination, source_type=v.kind,
                   appearance=VehicleAppearance(kind=v.kind,shape='material_truck' if v.kind=='truck' else 'car',
                        cargo_key=next(iter(v.cargo),None),load_fraction=min(1,sum(v.cargo.values())/v.capacity) if v.capacity else 0),
                   length=v.length, width=v.width, speed_cap_mph=None)
        if actor is None:
            return False
        v._actor, v._last, v.destination, v.phase = actor, 0.0, destination, 'driving'
        return True

    def observe(self):
        completed = {c.id for c in self.transit.vehicle_arrivals}
        self.transit.vehicle_arrivals.clear()
        for v in self.vehicles.values():
            if v.phase != 'driving':
                continue
            delta = max(0, v._actor.distance-v._last)
            v.distance_feet += delta
            v.fuel_liters = max(0, v.fuel_liters-delta/5280*v.liters_per_mile)
            v._last = v._actor.distance
            if v.id in completed:
                v.site, v.destination, v._actor = v.destination, None, None
                v.phase, v.trips = 'waiting_for_parking', v.trips+1
        for v in self.vehicles.values():
            if v.phase == 'waiting_for_parking' and self.parked_at(v.site) < self.sites[v.site]['parking_capacity']:
                v.phase = 'parked'
                self.arrivals.append(v.id)
