"""Import OSM building footprints, mapped purposes, and inferred parking."""
from collections import Counter
import json
import gzip
from math import isfinite
import xml.etree.ElementTree as ET

from building_footprints import triangulate_ring, subtract_courtyards
from building_operations import validate_operation
from city import Building, Parcel, ZoneType
from models import BuildablePhase
from parking_layout import ensure_parking


def building_category(tags):
    purpose = str(tags.get('building:use', tags.get('building', 'yes'))).lower()
    if purpose in {'industrial', 'warehouse', 'factory', 'manufacture', 'farm', 'barn', 'farm_auxiliary', 'greenhouse', 'hangar'}:
        return ZoneType.INDUSTRIAL
    if (purpose in {'commercial', 'retail', 'office', 'supermarket', 'hotel', 'hospital',
                    'school', 'university', 'college', 'kindergarten', 'government', 'fire_station',
                    'church', 'civic', 'public', 'train_station', 'transportation', 'grandstand', 'kiosk', 'toilets'} or
            tags.get('shop') not in (None, '', 'no') or
            tags.get('office') not in (None, '', 'no') or
            tags.get('amenity') in {'cafe', 'restaurant', 'fast_food', 'clinic', 'hospital', 'school', 'bank'}):
        return ZoneType.COMMERCIAL
    return ZoneType.RESIDENTIAL


def _read_elements(path):
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        prefix = stream.read(256).lstrip()
        stream.seek(0)
        if not prefix.startswith('<'):
            payload = json.load(stream)
            if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list):
                raise ValueError(f'{path}: expected an Overpass JSON elements array')
            return payload['elements']
        try:
            root = ET.parse(stream).getroot()
        except ET.ParseError as error:
            raise ValueError(f'{path}: invalid OSM XML: {error}') from error
    if root.tag != 'osm':
        raise ValueError(f'{path}: expected an OSM XML document')
    elements = []
    for item in root:
        if item.tag not in ('node', 'way', 'relation') or not item.get('id'):
            continue
        record = {'type': item.tag, 'id': item.get('id'),
                  'tags': {tag.get('k'): tag.get('v') for tag in item.findall('tag')}}
        if item.tag == 'node':
            if item.get('lon') is None or item.get('lat') is None:
                continue
            record.update(lon=item.get('lon'), lat=item.get('lat'))
        elif item.tag == 'way':
            refs = item.findall('nd')
            record['nodes'] = [ref.get('ref') for ref in refs]
            if refs and all(ref.get('lon') is not None and ref.get('lat') is not None for ref in refs):
                record['geometry'] = [{'lon': ref.get('lon'), 'lat': ref.get('lat')} for ref in refs]
        else:
            record['members'] = [dict(member.attrib) for member in item.findall('member')]
        elements.append(record)
    return elements


def _coordinates(record, nodes):
    geometry = record.get('geometry')
    try:
        if geometry is not None:
            points = [(float(p['lon']), float(p['lat'])) for p in geometry]
        else:
            points = [nodes[str(node)] for node in record.get('nodes', [])]
    except (KeyError, TypeError, ValueError, OverflowError):
        return []
    return points if all(isfinite(x) and isfinite(y) for x, y in points) else []


def _outer_rings(relation, ways, nodes):
    """Join multipolygon outer-way fragments, which can be reversed or unordered."""
    pieces, member_ids = [], set()
    for member in relation.get('members', []):
        if member.get('type') != 'way' or member.get('role', '') not in ('', 'outer'):
            continue
        member_id = str(member.get('ref'))
        points = _coordinates(member, nodes) if member.get('geometry') is not None else _coordinates(ways.get(member_id, {}), nodes)
        if len(points) < 2:
            return [], set()
        pieces.append(points)
        member_ids.add(member_id)
    rings = []
    while pieces:
        ring = pieces.pop(0)
        while ring[0] != ring[-1]:
            for i, part in enumerate(pieces):
                if part[0] == ring[-1]:
                    ring.extend(part[1:])
                elif part[-1] == ring[-1]:
                    ring.extend(reversed(part[:-1]))
                elif part[-1] == ring[0]:
                    ring = part[:-1] + ring
                elif part[0] == ring[0]:
                    ring = list(reversed(part[1:])) + ring
                else:
                    continue
                pieces.pop(i)
                break
            else:
                return [], set()
        rings.append(ring)
    return rings, member_ids


def _rectangle(rings, project):
    """Return a world-space bounding rectangle for valid closed polygons."""
    projected = []
    for ring in rings:
        if len(ring) < 4 or ring[0] != ring[-1] or len(set(ring[:-1])) < 3:
            return None
        points = [project(p) for p in ring]
        try:
            triangulate_ring(points)
        except ValueError:
            return None
        origin = points[0]
        area = abs(sum((a[0]-origin[0])*(b[1]-origin[1]) -
                       (b[0]-origin[0])*(a[1]-origin[1])
                       for a, b in zip(points, points[1:]))) / 2
        if area <= 1e-6:
            return None
        projected.extend(points)
    if not projected:
        return None
    xs, ys = zip(*projected)
    return min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)


def import_osm_homes(city, paths, in_boundary, project, *, residents_per_building=4, progress=None):
    """Add operational buildings, preserving mapped nonresidential purposes.

    The historical function name remains for callers. Unknown building uses
    fall back to residential; housing capacities and parking are assumptions.
    """
    if isinstance(residents_per_building, bool) or not isinstance(residents_per_building, int) or residents_per_building < 1:
        raise ValueError('residents_per_building must be a positive integer')
    nodes, ways, relations = {}, {}, {}
    for path in paths:
        for element in _read_elements(path):
            kind, ident = element.get('type'), str(element.get('id'))
            if kind == 'node' and 'lon' in element and 'lat' in element:
                nodes[ident] = (float(element['lon']), float(element['lat']))
            elif kind in ('way', 'relation'):
                target = ways if kind == 'way' else relations
                # Preserve geometry when an adjacent extract repeats a sparse element.
                old = target.get(ident, {})
                target[ident] = {**old, **element}
                if old.get('geometry') and not element.get('geometry'):
                    target[ident]['geometry'] = old['geometry']

    def is_building(record):
        tag = str(record.get('tags', {}).get('building', '')).strip().lower()
        return tag not in ('', 'no', 'false', '0')

    counts = Counter()
    if progress:progress(dict(stage='building_geometry',source_records=len(ways)+len(relations)))
    existing = {b.id for b in city.buildings}
    relation_members = set()

    source_groups = {}
    for ident, relation in relations.items():
        if relation.get('tags', {}).get('type') == 'site':
            for member in relation.get('members', []):
                source_groups[(member.get('type'), str(member.get('ref')))] = f'osm-site:{ident}'

    def add(kind, ident, rings, record, holes=()):
        if not rings:
            counts['invalid_geometry'] += 1
            return False
        rectangle = _rectangle(rings, project)
        if rectangle is None:
            counts['invalid_geometry'] += 1
            return False
        points = [point for ring in rings for point in ring]
        center = ((min(p[0] for p in points)+max(p[0] for p in points))/2,
                  (min(p[1] for p in points)+max(p[1] for p in points))/2)
        if not in_boundary(center):
            counts['outside_boundary'] += 1
            return False
        bid = f'osm-building:{kind}:{ident}'
        if bid in existing:
            counts['already_imported'] += 1
            return True
        x, y, width, height = rectangle
        tags = dict(record.get('tags', {}))
        if (kind, ident) in source_groups:
            tags['parking:group'] = source_groups[(kind,ident)]
        category = building_category(tags)
        outbuilding = tags.get('building') in {'garage', 'garages', 'shed', 'carport', 'outbuilding', 'roof', 'deck', 'construction'}
        residents = residents_per_building if category == ZoneType.RESIDENTIAL and not outbuilding else 0
        footprints=[[project(point) for point in ring] for ring in rings]
        if holes:
            try:footprints=subtract_courtyards(footprints,[[project(point) for point in ring] for ring in holes])
            except ValueError:
                counts['invalid_geometry']+=1
                counts['invalid_courtyard_relations']+=1
                return False
            tags['traffic:courtyard']='yes'
        parcel = Parcel(x, y, width, height, category,
                        id=f'osm-parcel:{kind}:{ident}',
                        footprints=footprints)
        building = Building(tags.get('name') or f'OSM {category.value} {kind} {ident}', parcel,
                            residents=residents, jobs=0, source_tags=tags,
                            buildable_id='small_house' if residents else None,
                            color={ZoneType.RESIDENTIAL:'#d9b38c', ZoneType.COMMERCIAL:'#84aeca',
                                   ZoneType.INDUSTRIAL:'#baa56d'}[category], id=bid,
                            phase=BuildablePhase.OPERATIONAL,
                            operation=validate_operation({'role': 'home' if category == ZoneType.RESIDENTIAL else 'workplace'}))
        city.parcels.append(parcel)
        city.buildings.append(building)
        existing.add(bid)
        counts['imported_buildings'] += 1
        if holes:counts['imported_courtyard_buildings']+=1
        counts['imported_'+category.value] += 1
        if residents:
            counts['imported_homes'] += 1
        if progress and counts['imported_buildings']%250==0:
            progress(dict(stage='building_geometry',imported_buildings=counts['imported_buildings']))
        return True

    for ident, relation in sorted(relations.items()):
        if not is_building(relation):
            continue
        inner_members=[dict(member,role='outer') for member in relation.get('members',[])
                       if member.get('role')=='inner']
        holes=[]
        if inner_members:
            # A rejected relation must not reappear later as a filled outer
            # way (with different land use and invented housing capacity).
            relation_members.update(str(member.get('ref')) for member in relation.get('members',[])
                                    if member.get('type')=='way')
            holes,_=_outer_rings(dict(relation,members=inner_members),ways,nodes)
            if not holes:
                counts['incomplete_courtyard_relations']+=1
                relation_members.update(str(member.get('ref')) for member in relation.get('members',[])
                                        if member.get('type')=='way')
                continue
        rings, members = _outer_rings(relation, ways, nodes)
        if add('relation', ident, rings, relation, holes):
            relation_members.update(members)
            relation_members.update(str(m.get('ref')) for m in inner_members)
    for ident, way in sorted(ways.items()):
        if is_building(way) and ident not in relation_members:
            add('way', ident, [_coordinates(way, nodes)], way)
    ensure_parking(city,progress=progress)
    counts['parking_lots'] = len(city.parking_lots)
    counts['parking_spaces'] = sum(lot.capacity for lot in city.parking_lots)
    counts['parking_lots_without_access'] = sum(lot.road_id is None for lot in city.parking_lots)
    counts['parking_lots_without_space'] = sum(not lot.spaces for lot in city.parking_lots)
    return dict(counts)
