"""Read tagged OSM elements from Overpass JSON or OSM XML, optionally gzip."""
import gzip
import json
import xml.etree.ElementTree as ET


def read_osm(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        prefix = stream.read(256).lstrip()
        stream.seek(0)
        if not prefix.startswith('<'):
            payload = json.load(stream)
            if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list):
                raise ValueError(f'{path}: expected an Overpass JSON elements array')
            if payload.get('remark'):
                raise ValueError(f"{path}: incomplete OSM response: {payload['remark']}")
            return payload
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
    return {'elements': elements}
