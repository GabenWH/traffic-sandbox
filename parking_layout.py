"""Event-time parking layout; generated lots are explicitly inferred geometry."""
from collections import defaultdict
from math import atan2, ceil, cos, dist, floor, hypot, pi, sin

from building_footprints import distance_to_ring, open_ring
from parking import ParkingLot, ParkingSpace, bounds, oriented_rectangle, polygons_overlap


def building_rings(building):
    p = building.parcel
    return p.footprints or [[(p.x, p.y), (p.x+p.width, p.y),
                             (p.x+p.width, p.y+p.height), (p.x, p.y+p.height)]]


def _ribbon(a, b, width, padding=0):
    length = dist(a, b)
    if length <= 1e-7:
        return oriented_rectangle(a, (1, 0), width, width)
    heading = ((b[0]-a[0])/length, (b[1]-a[1])/length)
    return oriented_rectangle(((a[0]+b[0])/2, (a[1]+b[1])/2), heading, length+2*padding, width)


def road_obstacles(city):
    # Protect the road deck plus three feet beside it; parking is off-street.
    for road in city.roads:
        for a, b in zip(road.centerline, road.centerline[1:]):
            yield road.id, _ribbon(a, b, road.width+6, road.width/2+3)
    for junction in city.intersections:
        radius = junction.radius+3
        yield 'junction:'+junction.id, [(junction.position[0]+radius*cos(i*pi/12),
                                        junction.position[1]+radius*sin(i*pi/12)) for i in range(24)]


def validate_road_parking(city, road):
    """Reject a new ground road through parking before editing the network."""
    for index,(a,b) in enumerate(zip(road.centerline,road.centerline[1:])):
        ha,hb = road.elevations[index:index+2]
        if ha >= 16 and hb >= 16:
            continue
        if ha >= 16 or hb >= 16:
            t = (16-ha)/(hb-ha)
            cutoff = (a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))
            if ha >= 16: a = cutoff
            else: b = cutoff
        surface = _ribbon(a,b,road.width+6,road.width/2+3)
        if any(polygons_overlap(surface, polygon) for lot in city.parking_lots
               for polygon in ([lot.surface] if lot.surface else [s.corners for s in lot.spaces])):
            raise ValueError('Road overlaps a parking lot; clear the parking area first')


class _Obstacles:
    def __init__(self):
        self.cells = defaultdict(list)
        self.items = []

    def _cells(self, polygon):
        x, y, r, b = bounds(polygon)
        for col in range(floor(x/128), floor(r/128)+1):
            for row in range(floor(y/128), floor(b/128)+1):
                yield col, row

    def add(self, kind, ident, polygon):
        index = len(self.items)
        self.items.append((kind, ident, polygon))
        for cell in self._cells(polygon):
            self.cells[cell].append(index)

    def clear(self, polygon, *, driveway_road=None):
        candidates = {i for cell in self._cells(polygon) for i in self.cells.get(cell, ())}
        for i in candidates:
            kind, ident, other = self.items[i]
            if driveway_road is not None and (kind == 'driveway' or (kind == 'road' and ident == driveway_road)):
                continue
            if polygons_overlap(polygon, other):
                return False
        return True


def _projection(point, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length2 = dx*dx+dy*dy
    if not length2:
        return a
    t = max(0, min(1, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/length2))
    return a[0]+t*dx, a[1]+t*dy


class _RoadIndex:
    """Only roads within driveway reach can serve a candidate lot."""
    def __init__(self,city):
        self.roads_by_id={road.id:road for road in city.roads}
        self.cells=defaultdict(set);self.segments=[]
        self.flat={r.id:all(abs(z)<=1 for z in r.elevations) for r in city.roads}
        for road in city.roads:
            if not road.lanes:continue
            for a,b in zip(road.centerline,road.centerline[1:]):
                if a==b:continue
                index=len(self.segments);self.segments.append((road,a,b))
                for x in range(floor(min(a[0],b[0])/600),floor(max(a[0],b[0])/600)+1):
                    for y in range(floor(min(a[1],b[1])/600),floor(max(a[1],b[1])/600)+1):
                        self.cells[x,y].add(index)

    def near(self,point,radius=600):
        left,right=floor((point[0]-radius)/600),floor((point[0]+radius)/600)
        top,bottom=floor((point[1]-radius)/600),floor((point[1]+radius)/600)
        if (right-left+1)*(bottom-top+1)>max(9,len(self.segments)*4):
            candidates=range(len(self.segments))
        else:
            candidates={i for x in range(left,right+1) for y in range(top,bottom+1)
                        for i in self.cells.get((x,y),())}
        best={}
        for index in candidates:
            road,a,b=self.segments[index];mouth=_projection(point,a,b);distance=dist(point,mouth)
            if distance>radius or (not self.flat[road.id] and abs(road.elevation_at(mouth))>1):continue
            entry=(distance,road.id,a,b)
            if road.id not in best or entry<best[road.id]:best[road.id]=entry
        return sorted(best.values())[:8]


def _near_roads(city, point, road_index=None, reach=600):
    if road_index is not None:return road_index.near(point,reach)
    choices = []
    for road in city.roads:
        if not road.lanes:
            continue
        segments = [(dist(point, _projection(point,a,b)), a, b)
                    for a,b in zip(road.centerline,road.centerline[1:]) if a != b
                    and abs(road.elevation_at(_projection(point,a,b))) <= 1]
        if segments:
            distance, a, b = min(segments)
            choices.append((distance, road.id, a, b))
    return sorted(choices)[:8]


def _group_key(building):
    tags = building.source_tags
    if tags.get('parking:group'):
        return 'source', tags['parking:group']
    if tags.get('addr:street') and tags.get('addr:housenumber'):
        return 'address', tags['addr:street'].strip().lower(), tags['addr:housenumber'].strip().lower()
    return None


def _groups(buildings):
    """Use source groups first; infer touching structures or nearby outbuildings."""
    groups = [];keyed={};nearby=defaultdict(set);centers={}
    for building in sorted(buildings, key=lambda b:b.id):
        key = _group_key(building)
        center = building.parcel.representative_point()
        centers[building.id]=center
        cell=(floor(center[0]/120),floor(center[1]/120))
        if key is not None:
            if key not in keyed:
                keyed[key]=len(groups);groups.append([])
            groups[keyed[key]].append(building)
            continue
        candidates=sorted({i for dx in (-1,0,1) for dy in (-1,0,1)
                           for i in nearby.get((cell[0]+dx,cell[1]+dy),())})
        for index in candidates:
            group=groups[index]
            if len(group)>=4:continue
            for other in group:
                if dist(center, centers[other.id]) > 120:
                    continue
                outbuilding = {'garage', 'garages', 'shed', 'carport', 'outbuilding'}
                threshold = 24 if (building.source_tags.get('building') in outbuilding or
                                  other.source_tags.get('building') in outbuilding) else 2
                gap = min(distance_to_ring(ring, p) for ring in building_rings(other)
                          for outline in building_rings(building) for p in open_ring(outline))
                if gap <= threshold:
                    group.append(building)
                    break
            else:
                continue
            break
        else:
            index=len(groups)
            groups.append([building])
        nearby[cell].add(index)
    return groups


def _layout(ident, center, angle, cars):
    ux, uy = cos(angle), sin(angle)
    vx, vy = -uy, ux
    width, depth = cars*12+14, 48
    def point(x, y):
        return center[0]+ux*x+vx*y, center[1]+uy*x+vy*y
    surface = oriented_rectangle(center, (ux,uy), width, depth)
    spaces = [ParkingSpace(f'{ident}:car:{i}', point(-width/2+6+12*i, -14),
                           angle=angle-pi/2) for i in range(cars)]
    spaces.append(ParkingSpace(f'{ident}:delivery', point(width/2-7, -9),
                               angle=angle-pi/2, length=30, width=12))
    exits = [point(x,15) for x in (0, -width/2+5, width/2-5)]
    return ParkingLot(ident, spaces, surface), exits


def _place(city, group, obstacles, map_bounds, road_index=None):
    ident = 'parking:'+min(b.id for b in group)
    centers = [b.parcel.representative_point() for b in group]
    center = tuple(sum(p[i] for p in centers)/len(centers) for i in (0,1))
    # Candidates are placed around each member as well as the midpoint.
    # A campus/address group may span far more than one search cell.
    reach=600+max(dist(center,p) for p in centers)
    roads = _near_roads(city, center,road_index,reach)
    angle = atan2(roads[0][3][1]-roads[0][2][1], roads[0][3][0]-roads[0][2][0]) if roads else 0
    desired = min(24, max(2, sum(max(2, ceil(b.residents/4), ceil(b.jobs/4)) for b in group)))
    candidates = []
    road_by_id = road_index.roads_by_id if road_index is not None else {road.id:road for road in city.roads}
    for _,road_id,a,b in roads:
        mouth = _projection(center,a,b)
        length = dist(a,b)
        u = ((b[0]-a[0])/length,(b[1]-a[1])/length)
        v = (-u[1],u[0])
        side = 1 if v[0]*(center[0]-mouth[0])+v[1]*(center[1]-mouth[1]) >= 0 else -1
        # Road edge clearance (3), half the 48-foot lot, and half a foot
        # of separation. Exact frontage candidates also fit narrow yards.
        setback = road_by_id[road_id].width/2+27.5
        for offset in (0,-24,24,-48,48,-72,72,-96,96):
            point = (mouth[0]+u[0]*offset+side*v[0]*setback,
                     mouth[1]+u[1]*offset+side*v[1]*setback)
            if dist(point,center) <= 224:
                candidates.append(point)
    for origin in [center]+centers if len(centers)>1 else centers:
        for radius in (36, 48, 64, 80, 104, 136, 176, 224):
            for i in range(16):
                direction = angle+i*pi/8
                candidates.append((origin[0]+radius*cos(direction), origin[1]+radius*sin(direction)))
    fallback = None
    for cars in dict.fromkeys((desired, min(desired, 4), 2)):
        for point in candidates:
            orientation = angle
            if roads:
                _,_,a,b = roads[0]
                mouth = _projection(point,a,b)
                if -sin(angle)*(mouth[0]-point[0])+cos(angle)*(mouth[1]-point[1]) < 0:
                    orientation += pi
            lot, exits = _layout(ident, point, orientation, cars)
            left, top, right, bottom = map_bounds
            if any(x < left or y < top or x > right or y > bottom for x,y in lot.surface):
                continue
            if not obstacles.clear(lot.surface):
                continue
            if fallback is None:
                fallback = lot
            for _, road_id, a, b in roads:
                for start in exits:
                    end = _projection(start, a, b)
                    if dist(start, end) > 300:
                        continue
                    road = road_by_id[road_id]
                    if abs(road.elevation_at(end)) > 1:
                        continue
                    path = _ribbon(start, end, 10)
                    if (not any(polygons_overlap(path, s.corners) for s in lot.spaces)
                            and obstacles.clear(path, driveway_road=road_id)):
                        lot.driveway, lot.road_id = [start,end], road_id
                        return lot
    return fallback or ParkingLot(ident)


def ensure_parking(city, *, progress=None):
    """Assign only unassigned buildings; never move existing lots or vehicles."""
    lot_ids = {lot.id for lot in city.parking_lots}
    pending = [b for b in city.buildings if b.parking_lot_id is None]
    if any(b.parking_lot_id is not None and b.parking_lot_id not in lot_ids for b in city.buildings):
        raise ValueError('Building refers to an unknown parking lot')
    if not pending:
        return
    obstacles = _Obstacles()
    road_index=_RoadIndex(city)
    road_points = [point for road in city.roads for point in road.centerline]
    # OSM projection is centered on the geographic origin, so valid geometry
    # can have negative coordinates even though width/height store its span.
    map_bounds = (min([0]+[p[0] for p in road_points]), min([0]+[p[1] for p in road_points]),
                  max([city.width]+[p[0] for p in road_points]), max([city.height]+[p[1] for p in road_points]))
    for building in city.buildings:
        for ring in building_rings(building):
            obstacles.add('building', building.id, ring)
    for ident, polygon in road_obstacles(city):
        obstacles.add('road', ident, polygon)
    def add_lot(lot):
        if lot.surface:
            obstacles.add('lot', lot.id, lot.surface)
        for a,b in zip(lot.driveway, lot.driveway[1:]):
            obstacles.add('driveway', lot.id, _ribbon(a,b,10))
    for lot in city.parking_lots:
        add_lot(lot)
    groups=_groups(pending)
    if progress:progress(dict(stage='parking_layout',groups=len(groups),completed=0))
    for number,group in enumerate(groups,1):
        # A newly placed building with an explicit source/address group may
        # reuse an existing lot. Its capacity remains the actual space count.
        key = _group_key(group[0])
        shared = next((b.parking_lot_id for b in city.buildings
                       if key is not None and b.parking_lot_id and _group_key(b) == key), None)
        if shared:
            for building in group:
                building.parking_lot_id = shared
        else:
            lot = _place(city, group, obstacles, map_bounds,road_index)
            city.parking_lots.append(lot)
            add_lot(lot)
            for building in group:
                building.parking_lot_id = lot.id
        if progress and (number%100==0 or number==len(groups)):
            progress(dict(stage='parking_layout',groups=len(groups),completed=number))
    _share_nearby_parking(city, {lot.id for lot in city.parking_lots}-lot_ids)
    if progress:progress(dict(stage='parking_ready',lots=len(city.parking_lots),
                              spaces=sum(l.capacity for l in city.parking_lots)))


def _share_nearby_parking(city, created):
    """Dense yards can share a nearby usable lot instead of gaining fake stalls.

    Only newly generated lots may be replaced; occupied existing lots remain
    stable. This is a parking assignment heuristic, not a cadastral assertion.
    """
    connected = [lot for lot in city.parking_lots if lot.spaces and lot.road_id]
    roads = _Obstacles()
    for ident, polygon in road_obstacles(city):
        roads.add('road', ident, polygon)
    removed = set()
    for lot in city.parking_lots:
        if lot.id not in created or (lot.spaces and lot.road_id):
            continue
        members = [b for b in city.buildings if b.parking_lot_id == lot.id]
        centers = [b.parcel.representative_point() for b in members]
        choices = []
        for other in connected:
            target = tuple(sum(s.position[i] for s in other.spaces)/len(other.spaces) for i in (0,1))
            distance = max(dist(p,target) for p in centers)
            if distance <= 300 and all(roads.clear(_ribbon(p,target,1)) for p in centers):
                choices.append((distance, other.id))
        if choices:
            shared = min(choices)[1]
            for building in members:
                building.parking_lot_id = shared
            removed.add(lot.id)
    city.parking_lots[:] = [lot for lot in city.parking_lots if lot.id not in removed]


def parking_access(city, lot, roads_by_id=None):
    """Resolve a driveway mouth after road edits, without moving the lot."""
    from mobility import nearest_lane_position
    if not lot.driveway:
        return None
    mouth = lot.driveway[-1]
    roads_by_id=roads_by_id if roads_by_id is not None else {r.id:r for r in city.roads}
    authored=roads_by_id.get(lot.road_id)
    def positions(roads):
        choices=[(nearest_lane_position(lane,mouth),road) for road in roads for lane in road.lanes]
        return [(position,road) for (position,distance),road in choices
                if distance<=road.width/2+2 and abs(road.elevation_at(position.point))<=1]
    candidates=positions([authored]) if authored else []
    if not candidates:candidates=positions(city.roads)
    if not candidates:
        return None
    position, road = min(candidates, key=lambda item:dist(item[0].point,mouth))
    return position
