"""Convert OSM building footprints into the city's rectangular home model."""
from collections import Counter
import json
from math import isfinite
import xml.etree.ElementTree as ET

from building_operations import validate_operation
from city import Building, Parcel, ZoneType
from models import BuildablePhase


def _read_elements(path):
    with open(path, encoding='utf-8') as stream:
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


def import_osm_homes(city, paths, in_boundary, project, *, residents_per_building=4):
    """Add one operational home per OSM building way or multipolygon relation.

    This intentionally treats every building tag as a home, regardless of its
    mapped purpose. Capacities are assumptions, not population measurements.
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
    existing = {b.id for b in city.buildings}
    relation_members = set()

    def add(kind, ident, rings):
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
        parcel = Parcel(x, y, width, height, ZoneType.RESIDENTIAL, id=f'osm-parcel:{kind}:{ident}')
        building = Building(f'OSM home {kind} {ident}', parcel, residents=residents_per_building,
                            jobs=0, buildable_id='small_house', color='#d9b38c', id=bid,
                            phase=BuildablePhase.OPERATIONAL, operation=validate_operation({'role': 'home'}))
        city.parcels.append(parcel)
        city.buildings.append(building)
        existing.add(bid)
        counts['imported_homes'] += 1
        return True

    for ident, relation in sorted(relations.items()):
        if not is_building(relation):
            continue
        rings, members = _outer_rings(relation, ways, nodes)
        if add('relation', ident, rings):
            relation_members.update(members)
    for ident, way in sorted(ways.items()):
        if is_building(way) and ident not in relation_members:
            add('way', ident, [_coordinates(way, nodes)])
    return dict(counts)
