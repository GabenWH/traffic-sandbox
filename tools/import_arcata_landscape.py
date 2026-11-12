#!/usr/bin/env python3
"""Add OSM scenery to an existing Arcata world without changing its gameplay."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from persistence import world_from_dict, world_to_dict
from tools.osm_landscape import download_landscape, import_osm_landscape, boundary_selector
from tools.run_arcata_scale_test import parse_boundary, point_in_city


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--world',type=Path,required=True,help='existing Arcata world save')
    parser.add_argument('--boundary',type=Path,default=ROOT/'benchmarks/arcata/arcata-city-boundary.osm')
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--landscape',type=Path,action='append',help='OSM JSON, XML or gzip extract; repeatable')
    source.add_argument('--download',type=Path,metavar='EXTRACT',help='download and retain an OSM extract')
    parser.add_argument('--output',type=Path,required=True,help='new world save; never overwrites')
    args=parser.parse_args(argv)
    if args.output.exists():parser.error(f'output already exists: {args.output}')
    if args.download and args.download.exists():parser.error(f'extract already exists: {args.download}')
    try:
        with args.world.open(encoding='utf-8') as stream: raw=json.load(stream)
        loaded=world_from_dict(raw)
        outer,inner,_=parse_boundary(args.boundary)
        points=[p for ring in outer for p in ring[:-1]]
        lat0=sum(p[1] for p in points)/len(points);lon0=sum(p[0] for p in points)/len(points)
        def project(point):
            return ((point[0]-lon0)*111320*math.cos(math.radians(lat0))*3.28084,
                    (point[1]-lat0)*111132*3.28084)
        projected=[project(p) for p in points];xs,ys=zip(*projected)
        loaded.city_map.terrain.bounds=(min(xs),min(ys),max(xs),max(ys))
        paths=[download_landscape(args.boundary,args.download)] if args.download else args.landscape
        counts=import_osm_landscape(loaded.city_map,paths,lambda p:point_in_city(p,outer,inner),project,
                                    touches_boundary=boundary_selector(outer,inner),
                                    contains_world=lambda p:point_in_city((
                                        lon0+p[0]/(111320*math.cos(math.radians(lat0))*3.28084),
                                        lat0+p[1]/(111132*3.28084)),outer,inner))
        updated=world_to_dict(loaded.city_map,unit_system=loaded.unit_system,
                              camera_x=loaded.camera_x,camera_y=loaded.camera_y,camera_zoom=loaded.camera_zoom,
                              camera_3d=loaded.camera_3d)
        # Change only known landscape fields, preserving current gameplay,
        # camera, and even save extensions this importer does not understand.
        terrain=raw['world']['terrain']
        for key in ('trees','areas','waterways','hills','bounds'):
            terrain[key]=updated['world']['terrain'][key]
        world_from_dict(raw)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:json.dump(raw,stream)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1,f'Landscape import failed: {error}\n')
    print(json.dumps({'output':str(args.output),'landscape':counts}))
    return 0


if __name__=='__main__':raise SystemExit(main())
