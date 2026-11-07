"""Event-time indexes for finite public overflow parking.

Parking endpoints are physical fleet sites, not businesses or buildings. Rebuild
this index after a building/network edit, then reuse candidates for each trip.
The caller checks an actual pedestrian route before admitting an overflow trip.
"""
from collections import defaultdict
from math import atan2, dist, floor, isfinite, pi

from building_operations import operation_for
from parking import ParkingLot, ParkingSpace, oriented_rectangle, polygons_overlap
from parking_layout import _Obstacles, _ribbon, building_rings, parking_access, road_obstacles


WALK_REACH = 1320.0
_CELL = 512.0
_CURB_PREFIX = 'curb:'


def _public_building(site):
    building = site.get('building')
    if building is None or operation_for(building)['role'] in ('home', 'bus_stop'):
        return False
    tags = building.source_tags
    return not any(tags.get(key, '').lower() in ('private', 'no')
                   for key in ('access', 'parking:access'))


def _cells_near(point, radius, size=_CELL):
    for x in range(floor((point[0]-radius)/size), floor((point[0]+radius)/size)+1):
        for y in range(floor((point[1]-radius)/size), floor((point[1]+radius)/size)+1):
            yield x, y


def _lot_walk_point(lot):
    if lot.driveway:
        return tuple(lot.driveway[0])
    return tuple(sum(space.position[i] for space in lot.spaces)/lot.capacity for i in (0, 1))


def ensure_curbside_parking(city, destinations):
    """Infer small roadside bays only on empty, walkable local-road frontage.

    Existing road widths contain moving lanes, with sidewalks just outside them.
    Bays therefore sit beyond that protected deck and sidewalk, connected by a
    short driveway at the row's end. We do not turn a moving lane or sidewalk into
    parking. Geometry is explicitly inferred and uses the ordinary persistent
    ParkingLot format. Existing bays are never moved or regenerated.
    """
    if not destinations:
        return
    # Match off-street inference: projected road geometry may extend beyond the
    # nominal span or use negative coordinates, but bays stay within that world.
    road_points = [point for road in city.roads for point in road.centerline]
    left = min([0]+[point[0] for point in road_points])
    top = min([0]+[point[1] for point in road_points])
    right = max([city.width]+[point[0] for point in road_points])
    bottom = max([city.height]+[point[1] for point in road_points])
    anchors = defaultdict(list)
    for point in destinations:
        anchors[floor(point[0]/_CELL), floor(point[1]/_CELL)].append(point)

    def near_destination(point):
        return any(dist(point, target) <= WALK_REACH
                   for cell in _cells_near(point, WALK_REACH)
                   for target in anchors.get(cell, ()))

    obstacles = _Obstacles()
    for building in city.buildings:
        for ring in building_rings(building):
            obstacles.add('building', building.id, ring)
    for ident, polygon in road_obstacles(city):
        obstacles.add('road', ident, polygon)

    def add_lot(lot):
        for polygon in [lot.surface] if lot.surface else [s.corners for s in lot.spaces]:
            obstacles.add('lot', lot.id, polygon)
        for polygon in lot.driveway_surfaces:
            obstacles.add('driveway', lot.id, polygon)

    existing_lots = {lot.id: lot for lot in city.parking_lots}
    for lot in city.parking_lots:
        add_lot(lot)
    for road in sorted(city.roads, key=lambda r: r.id):
        name = road.name.lower()
        if (not road.lanes or len(road.lanes) > 2
                or not road.pedestrian_lanes
                or any(f'[{kind}]' in name for kind in
                       ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link'))
                or (road.speed_limit_mph is not None and road.speed_limit_mph > 35)):
            continue
        sides = [side for side in ('left', 'right') if side in road.pedestrian_sides]
        setback = road.width/2 + max(road.pedestrian_offset+1, 4) + 6
        for segment, (a, b) in enumerate(zip(road.centerline, road.centerline[1:])):
            length = dist(a, b)
            if length < 104 or max(road.elevations[segment:segment+2]) > 1:
                continue
            ux, uy = (b[0]-a[0])/length, (b[1]-a[1])/length
            angle = atan2(uy, ux)
            for side in sides:
                sign = 1 if side == 'left' else -1
                vx, vy = -uy*sign, ux*sign
                def point(along, offset=setback):
                    return a[0]+ux*along+vx*offset, a[1]+uy*along+vy*offset
                slot = 0
                while (along := 52+24*slot) <= length-52:
                    ident = f'{_CURB_PREFIX}{road.id}:{segment}:{side}:{slot}'
                    existing = existing_lots.get(ident)
                    if existing is not None:
                        # Preserve the row and its access gap, but continue down
                        # the road so a new destination can use other frontage.
                        slot += existing.capacity+1
                        continue
                    if not near_destination(point(along)):
                        slot += 1
                        continue
                    count = min(6, int((length-52-along)//24)+1)
                    lot = None
                    for size in range(count, 0, -1):
                        span = (size-1)*24
                        surface = oriented_rectangle(point(along+span/2-6), (ux, uy), span+36, 12)
                        if any(x < left or y < top or x > right or y > bottom for x, y in surface):
                            continue
                        if not obstacles.clear(surface):
                            continue
                        start, end = point(along-18), point(along-18, 0)
                        driveway = _ribbon(start, end, 10)
                        if not obstacles.clear(driveway, driveway_road=road.id):
                            continue
                        spaces = [ParkingSpace(f'{ident}:{i}', point(along+24*i),
                            angle=angle if side == 'left' else angle+pi, length=22, width=10)
                            for i in range(size)]
                        if any(polygons_overlap(driveway, space.corners) for space in spaces):
                            continue
                        lot = ParkingLot(ident, spaces, surface, [start, end], road.id)
                        break
                    if lot is None:
                        slot += 1
                        continue
                    city.parking_lots.append(lot)
                    add_lot(lot)
                    slot += lot.capacity+1


class ParkingAccessIndex:
    """Public physical endpoints separate from the city's economic site map.

    ``sites`` is suitable as the first mapping in ``ChainMap(index.sites, sites)``.
    ``candidates(target)`` returns deterministic nearby *alternate* endpoint IDs,
    excluding the target's own lot. Each lot appears only once, regardless of the
    number of buildings that share it. Availability and actual walking routes are
    deliberately checked by trip admission, not by this static index.
    """
    def __init__(self, city, sites):
        self.city = city
        self.building_sites = sites
        self.sites = {}
        self._cells = defaultdict(list)
        self._candidates = {}
        public_sites = [site for site in sites.values() if _public_building(site)]
        ensure_curbside_parking(city, [site['walk_point'] for site in public_sites])
        public_lots = {site['parking_lot'].id for site in public_sites
                       if site.get('parking_lot') is not None}
        roads = {road.id: road for road in city.roads}
        for lot in city.parking_lots:
            if not lot.spaces:
                continue
            ident = 'parking-endpoint:'+lot.id
            position = parking_access(city, lot, roads)
            point = _lot_walk_point(lot)
            self.sites[ident] = dict(parking_lot=lot, parking_capacity=lot.capacity,
                                    road_position=position, walk_point=point, parking_endpoint=True)
            # Keep an address for parked vehicles even if a lot becomes private
            # or loses access; only eligible public lots enter candidate lookup.
            public = lot.id in public_lots or lot.id.startswith(_CURB_PREFIX)
            if position is not None and public:
                self._cells[floor(point[0]/_CELL), floor(point[1]/_CELL)].append(ident)
        self.revision = city.mobility_revision

    def walk_point(self, site_id):
        return (self.sites[site_id] if site_id in self.sites else
                self.building_sites[site_id])['walk_point']

    def candidates(self, target_site, max_distance=WALK_REACH):
        if not isfinite(max_distance) or max_distance < 0:
            raise ValueError('Parking walking distance must be finite and nonnegative')
        key = target_site, max_distance
        if key not in self._candidates:
            target = self.building_sites.get(target_site, self.sites.get(target_site))
            if target is None:
                return ()
            point = target['walk_point']
            own = target.get('parking_lot')
            choices = []
            for cell in _cells_near(point, max_distance):
                for ident in self._cells.get(cell, ()):
                    site = self.sites[ident]
                    if own is not None and site['parking_lot'].id == own.id:
                        continue
                    distance = dist(point, site['walk_point'])
                    if distance <= max_distance:
                        choices.append((distance, ident))
            self._candidates[key] = tuple(ident for _, ident in sorted(choices))
        return self._candidates[key]
