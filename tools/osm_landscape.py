"""Import OSM land cover and waterways without guessing unmapped geography."""
from collections import Counter, defaultdict
from math import dist, floor, isfinite
from random import Random
import re
from zlib import crc32

from building_footprints import contains_point, distance_to_ring, distance_to_segment, subtract_courtyards
from landscape import LandscapeArea, Waterway
from tools.osm_buildings import _coordinates, _outer_rings
from tools.osm_elements import read_osm


AREA_TAGS = {
    ('landuse', 'forest'): 'forest', ('natural', 'wood'): 'forest',
    ('natural', 'grassland'): 'meadow', ('landuse', 'meadow'): 'meadow',
    ('landuse', 'grass'): 'meadow', ('leisure', 'park'): 'meadow',
    ('landuse', 'farmland'): 'farmland', ('landuse', 'farmyard'): 'farmland',
    ('natural', 'water'): 'water', ('waterway', 'riverbank'): 'water',
    ('natural', 'wetland'): 'wetland',
}
DEFAULT_WIDTH_FEET = {'stream': 15., 'river': 90., 'canal': 30., 'ditch': 8.}


def area_kind(tags):
    for key, value in AREA_TAGS:
        if tags.get(key) == value:
            return AREA_TAGS[key, value]
    return None


def water_width(tags, kind):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(m|meter|metres|meters|ft|feet|\')?\s*', str(tags.get('width', '')), re.I)
    if match:
        value = float(match.group(1)) * (1 if (match.group(2) or '').lower() in ('ft', 'feet', "'") else 3.28084)
        if isfinite(value) and 0 < value <= 5000:
            return value
    return DEFAULT_WIDTH_FEET[kind]


def _rings(relation, ways, nodes, role):
    members = [dict(m, role='outer') for m in relation.get('members', [])
               if m.get('type') == 'way' and (m.get('role', '') in ('', 'outer') if role == 'outer' else m.get('role') == role)]
    if not members:
        return [], set()
    return _outer_rings({'members': members}, ways, nodes)


def _tree_exclusions(city):
    """Index existing built objects to keep imported trees off streets and roofs."""
    cells = defaultdict(list)
    size = 200.
    def add(bounds, item):
        x0,y0,x1,y1 = bounds
        for x in range(floor(x0/size), floor(x1/size)+1):
            for y in range(floor(y0/size), floor(y1/size)+1):
                cells[x,y].append(item)
    for road in city.roads:
        margin = road.width/2 + 14
        for a,b in zip(road.centerline, road.centerline[1:]):
            add((min(a[0],b[0])-margin,min(a[1],b[1])-margin,max(a[0],b[0])+margin,max(a[1],b[1])+margin), ('road',a,b,margin))
    from models import IntersectionKind
    from roundabouts import outer_band_width
    for junction in city.intersections:
        extra = outer_band_width(junction) if junction.kind is IntersectionKind.ROUNDABOUT else (2 if junction.kind is IntersectionKind.CUL_DE_SAC else 0)
        x,y=junction.position; radius=junction.radius+extra+11
        add((x-radius,y-radius,x+radius,y+radius), ('intersection',(x,y),radius))
    for water in city.terrain.waterways:
        margin = water.width/2 + 12
        for a,b in zip(water.points, water.points[1:]):
            add((min(a[0],b[0])-margin,min(a[1],b[1])-margin,max(a[0],b[0])+margin,max(a[1],b[1])+margin), ('waterway',a,b,margin))
    water_areas=[]
    for area in city.terrain.areas:
        if area.kind == 'water':
            xs,ys=zip(*area.points)
            water_areas.append((min(xs),min(ys),max(xs),max(ys),area.points))
    for lot in city.parking_lots:
        for polygon in ([lot.surface] if lot.surface else []) + lot.driveway_surfaces:
            if len(polygon)<3: continue
            xs,ys=zip(*polygon);margin=11.
            add((min(xs)-margin,min(ys)-margin,max(xs)+margin,max(ys)+margin), ('parking',polygon,margin))
    for building in city.buildings:
        p=building.parcel
        add((p.x-14,p.y-14,p.x+p.width+14,p.y+p.height+14), ('building',p.x-14,p.y-14,p.x+p.width+14,p.y+p.height+14))
    def allowed(p):
        for item in cells.get((floor(p[0]/size),floor(p[1]/size)), ()):
            if item[0] in ('road','waterway') and distance_to_segment(p,item[1],item[2]) < item[3]:
                return False
            if item[0]=='intersection' and dist(p,item[1]) < item[2]:
                return False
            if item[0]=='parking' and distance_to_ring(item[1],p) < item[2]:
                return False
            if item[0]=='building' and item[1] <= p[0] <= item[3] and item[2] <= p[1] <= item[4]:
                return False
        return not any(x0<=p[0]<=x1 and y0<=p[1]<=y1 and contains_point(ring,p)
                       for x0,y0,x1,y1,ring in water_areas)
    return allowed


def import_osm_landscape(city, paths, in_boundary, project, *, touches_boundary=None, contains_world=None):
    """Add mapped polygons and waterways; repeated extracts do not duplicate them.

    Unsupported or incomplete geometry is skipped. Relation inner rings are
    removed before rendering, and no bodies of water are inferred from height.
    """
    nodes, ways, relations = {}, {}, {}
    for path in paths:
        for record in read_osm(path)['elements']:
            ident = str(record.get('id'))
            if record.get('type') == 'node' and 'lon' in record and 'lat' in record:
                try: nodes[ident] = (float(record['lon']), float(record['lat']))
                except (ValueError, TypeError): continue
            elif record.get('type') in ('way', 'relation'):
                collection = ways if record['type'] == 'way' else relations
                old = collection.get(ident, {})
                collection[ident] = {**old, **record}
                if old.get('geometry') and not record.get('geometry'):
                    collection[ident]['geometry'] = old['geometry']
    if touches_boundary is None:
        touches_boundary=lambda points, closed: any(in_boundary(p) for p in points)
    counts=Counter(); consumed=set()
    existing={a.source for a in city.terrain.areas if a.source} | {w.source for w in city.terrain.waterways if w.source}
    existing_areas={a.source.rsplit(':',1)[0] for a in city.terrain.areas if a.source}
    added_forests=[]

    def add_area(kind, source, rings, holes=()):
        if source in existing_areas:
            return
        if not rings or any(len(r)<4 or r[0]!=r[-1] for r in [*rings,*holes]):
            counts['invalid_geometry'] += 1; return
        # Keep only features touching the map's boundary. Do not infer location
        # from the centroid of unrelated polygons.
        if not any(touches_boundary(ring, True) for ring in rings):
            counts['outside_boundary'] += 1; return
        try:
            projected = [[project(p) for p in ring] for ring in rings]
            projected_holes = [[project(p) for p in ring] for ring in holes]
            parts = subtract_courtyards(projected, projected_holes) if projected_holes else projected
            new_areas=[LandscapeArea(kind,part,f'{source}:{i}') for i,part in enumerate(parts)]
            for area in new_areas: area.triangles
        except (ValueError, TypeError, OverflowError):
            counts['invalid_geometry'] += 1; return
        for area in new_areas:
            city.terrain.areas.append(area)
            if kind == 'forest': added_forests.append(area)
        existing_areas.add(source)
        counts[kind] += 1

    def add_waterway(ident, kind, points, tags):
        source=f'osm-waterway:way:{ident}'
        if source in existing or len(points)<2:return
        if not touches_boundary(points, False):
            counts['outside_boundary'] += 1; return
        try:
            city.terrain.waterways.append(Waterway(kind, [project(p) for p in points], water_width(tags,kind), source))
        except (TypeError,ValueError,OverflowError):
            counts['invalid_geometry'] += 1; return
        existing.add(source); counts[kind] += 1

    for relation in relations.values():
        tags=relation.get('tags', {})
        relation_kind=tags.get('waterway')
        if relation_kind not in DEFAULT_WIDTH_FEET:continue
        for member in relation.get('members', []):
            if member.get('type')!='way':continue
            ident=str(member.get('ref'));way=ways.get(ident,{})
            member_tags=way.get('tags',{})
            member_kind=member_tags.get('waterway')
            if member_kind not in DEFAULT_WIDTH_FEET:
                if member.get('role','') not in ('','main_stream'):continue
                member_kind=relation_kind
            points=_coordinates(member,nodes) if member.get('geometry') is not None else _coordinates(way,nodes)
            add_waterway(ident,member_kind,points,{**tags,**member_tags})

    for ident, relation in relations.items():
        kind = area_kind(relation.get('tags', {}))
        if kind is None: continue
        outer, ids = _rings(relation, ways, nodes, 'outer')
        inner, inner_ids = _rings(relation, ways, nodes, 'inner')
        # Suppress member ways even when a relation is malformed: filling an
        # orphan outer would silently erase its holes.
        consumed.update(str(m.get('ref')) for m in relation.get('members', []) if m.get('type')=='way')
        if any(m.get('role')=='inner' for m in relation.get('members', [])) and not inner:
            counts['invalid_geometry'] += 1; continue
        add_area(kind, f'osm-area:relation:{ident}', outer, inner)

    for ident, way in ways.items():
        tags = way.get('tags', {}); points = _coordinates(way, nodes)
        kind = area_kind(tags)
        if kind and ident not in consumed:
            add_area(kind, f'osm-area:way:{ident}', [points])
        waterway = tags.get('waterway')
        if waterway in DEFAULT_WIDTH_FEET:
            add_waterway(ident,waterway,points,tags)

    allowed=_tree_exclusions(city)
    left,bottom,right,top = city.terrain.bounds or (0,0,city.width,city.height)
    remaining=1000
    for area in added_forests:
        if remaining <= 0: break
        xs,ys=zip(*area.points)
        x0,y0=max(left,min(xs)),max(bottom,min(ys))
        x1,y1=min(right,max(xs)),min(top,max(ys))
        width,height=x1-x0,y1-y0
        if width <= 0 or height <= 0: continue
        attempts=min(250, max(1, int(width*height/2400)))
        random=Random(crc32(area.source.encode()))
        for _ in range(attempts):
            point=(random.uniform(x0,x1),random.uniform(y0,y1))
            if (contains_point(area.points,point) and (contains_world is None or contains_world(point))
                    and allowed(point)):
                city.terrain.trees.append(point); remaining-=1
                if remaining<=0: break
    counts['trees_added'] = 1000-remaining
    return dict(counts)


def boundary_selector(outer, inner):
    """Include enclosing polygons and crossings whose vertices are outside."""
    from tools.run_arcata_scale_test import clip_segment_to_city, point_in_city
    all_points=[p for ring in outer for p in ring]
    city_box=(min(p[0] for p in all_points),min(p[1] for p in all_points),
              max(p[0] for p in all_points),max(p[1] for p in all_points))
    def touches(points, closed):
        if not points:return False
        xs,ys=zip(*points)
        if max(xs)<city_box[0] or min(xs)>city_box[2] or max(ys)<city_box[1] or min(ys)>city_box[3]:
            return False
        if any(point_in_city(p,outer,inner) for p in points):return True
        if closed and any(contains_point(points,ring[0]) for ring in outer if ring):return True
        return any(clip_segment_to_city(a,b,outer,inner) for a,b in zip(points,points[1:]))
    return touches


def download_landscape(boundary_path, destination):
    """Download an Overpass extract for later reuse; never overwrite a file."""
    import json
    from pathlib import Path
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    from tools.run_arcata_scale_test import parse_boundary
    outer, _, _ = parse_boundary(Path(boundary_path))
    points = [point for ring in outer for point in ring]
    west, south = min(p[0] for p in points), min(p[1] for p in points)
    east, north = max(p[0] for p in points), max(p[1] for p in points)
    bbox = f'{south},{west},{north},{east}'
    selectors = ('["landuse"~"^(forest|meadow|grass|farmland|farmyard)$"]',
                 '["natural"~"^(wood|grassland|water|wetland)$"]',
                 '["leisure"="park"]', '["waterway"~"^(river|stream|canal|ditch|riverbank)$"]')
    query = '[out:json][timeout:180];(' + ''.join(
        f'{kind}{selector}({bbox});' for kind in ('way','relation') for selector in selectors
    ) + ');out body geom;'
    request = Request('https://overpass-api.de/api/interpreter', data=urlencode({'data': query}).encode(),
                      headers={'User-Agent':'traffic-sandbox-landscape-import/1.0'})
    with urlopen(request,timeout=210) as response:
        payload=json.load(response)
    if not isinstance(payload,dict) or not isinstance(payload.get('elements'),list) or payload.get('remark'):
        raise ValueError(f"Overpass did not return a complete landscape extract: {payload.get('remark', 'invalid response') if isinstance(payload,dict) else 'invalid response'}")
    destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x',encoding='utf-8') as stream:
        json.dump(payload,stream)
    return destination
