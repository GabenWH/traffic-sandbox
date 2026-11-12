#!/usr/bin/env python3
"""Create a loadable Arcata city with OSM buildings and inferred parking."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from persistence import world_to_dict
from tools.run_arcata_scale_test import build_city, parse_boundary


def download_extract(boundary_path, destination):
    """Download tagged building ways and relations with their full geometry."""
    outer, _, _ = parse_boundary(boundary_path)
    points = [point for ring in outer for point in ring]
    west, south = min(p[0] for p in points), min(p[1] for p in points)
    east, north = max(p[0] for p in points), max(p[1] for p in points)
    bbox = f'{south},{west},{north},{east}'
    query = f'[out:json][timeout:180];(way["building"]({bbox});relation["building"]({bbox}););out body geom;'
    request = Request('https://overpass-api.de/api/interpreter', data=urlencode({'data': query}).encode(),
                      headers={'User-Agent': 'traffic-sandbox-building-import/1.0'})
    with urlopen(request, timeout=210) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list):
        raise ValueError('Overpass did not return a building extract')
    if payload.get('remark'):
        raise ValueError(f"Overpass returned an incomplete result: {payload['remark']}")
    if not payload['elements']:
        raise ValueError('Overpass returned no building elements')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--osm', action='append', type=Path,
                        help='road Overpass JSON, repeatable; defaults to the bundled Arcata roads')
    parser.add_argument('--boundary', type=Path, default=ROOT / 'benchmarks/arcata/arcata-city-boundary.osm')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--buildings', action='append', type=Path,
                        help='building Overpass JSON or OSM XML extract, repeatable')
    source.add_argument('--download', type=Path, metavar='EXTRACT',
                        help='download building data from Overpass and save the extract at this path')
    terrain_source = parser.add_mutually_exclusive_group()
    terrain_source.add_argument('--landscape', action='append', type=Path,
                                help='OSM land cover/waterway extract, repeatable')
    terrain_source.add_argument('--download-landscape', type=Path, metavar='EXTRACT',
                                help='download land cover and waterways from Overpass')
    parser.add_argument('--residents-per-building', type=int, default=4,
                        help='assumed housing capacity per building (default: 4)')
    parser.add_argument('--output', type=Path, required=True, help='path for the new city save')
    args = parser.parse_args(argv)
    if args.residents_per_building < 1:
        parser.error('--residents-per-building must be positive')
    if args.output.exists():
        parser.error(f'output already exists: {args.output}')
    if args.download and args.download.exists():
        parser.error(f'extract already exists: {args.download}; use --buildings to reuse it')
    if args.download_landscape and args.download_landscape.exists():
        parser.error(f'extract already exists: {args.download_landscape}; use --landscape to reuse it')
    try:
        if args.download:
            print('Downloading Arcata building footprints from OpenStreetMap...', flush=True)
            building_paths = [download_extract(args.boundary, args.download)]
        else:
            building_paths = args.buildings
        if args.download_landscape:
            from tools.osm_landscape import download_landscape
            print('Downloading Arcata landscape from OpenStreetMap...', flush=True)
            landscape_paths = [download_landscape(args.boundary, args.download_landscape)]
        else:
            landscape_paths = args.landscape or []
        roads = args.osm or [ROOT / 'benchmarks/arcata/arcata-roads-2026-06-01.json']
        city, _, metadata = build_city(roads, args.boundary, building_paths=building_paths,
                                       residents_per_building=args.residents_per_building,
                                       landscape_paths=landscape_paths)
        if not metadata.get('imported_buildings'):
            raise ValueError('No usable building footprints were found inside the Arcata boundary')
        world = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(world, stream)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Import failed: {error}\n')
    print(json.dumps({'output': str(args.output), 'imported_homes': metadata['imported_homes'],
                      'imported_buildings': metadata['imported_buildings'],
                      'parking_lots': metadata['parking_lots'], 'parking_spaces': metadata['parking_spaces'],
                      'parking_lots_without_access': metadata['parking_lots_without_access'],
                      'parking_lots_without_space': metadata['parking_lots_without_space'],
                      'imported_courtyard_buildings': metadata.get('imported_courtyard_buildings',0),
                      'skipped_courtyard_relations': metadata.get('incomplete_courtyard_relations',0)+metadata.get('invalid_courtyard_relations',0),
                      'road_segments': len(city.roads), 'landscape': metadata.get('landscape', {}), 'capacity_per_home': args.residents_per_building,
                      'source': [str(path) for path in building_paths]}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
