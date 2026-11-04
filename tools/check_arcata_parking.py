#!/usr/bin/env python3
"""Fill the imported neighborhood's parking and check geometry and persistence."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from city_simulation import CitySimulation
from parking import oriented_rectangle, polygons_overlap
from parking_layout import building_rings, road_obstacles
from persistent_fleet import FleetVehicle
from persistence import world_from_dict, world_to_dict
from tools.run_arcata_scale_test import build_city


def check_parking(city):
    runtime = CitySimulation(city)
    lots = {lot.id:lot for lot in city.parking_lots}
    members = {}
    for b in city.buildings:
        members.setdefault(b.parking_lot_id, []).append(b.id)
    assert all(lots[b.parking_lot_id].capacity >= 2 for b in city.buildings), 'Building has no usable parking'
    assert all(runtime.sites[b.id]['road_position'] is not None for b in city.buildings), 'Building has no parking access'
    for lot in city.parking_lots:
        site = members[lot.id][0]
        # Fill large bays first so the check also proves real truck dimensions.
        for space in sorted(lot.spaces, key=lambda s:-s.length*s.width):
            truck = space.fits(28,8)
            runtime.fleet.add(FleetVehicle('parking-check:'+space.id, 'truck' if truck else 'car',site,
                                          length=28 if truck else 15,width=8 if truck else 6))
        try:
            runtime.fleet.add(FleetVehicle('overflow:'+lot.id, 'car',site))
        except ValueError:
            pass
        else:
            raise AssertionError('Full lot admitted another car')

    parked = list(runtime.fleet.parked_vehicles())
    assert len(parked) == sum(l.capacity for l in lots.values()), 'Missing parked vehicle poses'
    vehicle_polygons = [oriented_rectangle(v.position,v.heading,v.length,v.width) for v in parked]
    conflicts = sum(polygons_overlap(a,b) for i,a in enumerate(vehicle_polygons) for b in vehicle_polygons[i+1:])
    building_polygons = [p for b in city.buildings for p in building_rings(b)]
    road_polygons = [p for _,p in road_obstacles(city)]
    conflicts += sum(polygons_overlap(lot.surface,p) for lot in lots.values() for p in building_polygons+road_polygons)
    conflicts += sum(polygons_overlap(a.surface,b.surface) for i,a in enumerate(city.parking_lots) for b in city.parking_lots[i+1:])
    conflicts += sum(polygons_overlap(s.corners,drive) for lot in lots.values()
                     for s in lot.spaces for drive in lot.driveway_surfaces)
    assert conflicts == 0, f'{conflicts} physical parking overlaps'
    saved = world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)
    restored_city = world_from_dict(json.loads(json.dumps(saved))).city_map
    restored = CitySimulation(restored_city)
    assert restored_city.parking_lots == city.parking_lots, 'Parking geometry changed on restore'
    assert [(v.id,v.site,v.parking_space_id) for v in runtime.fleet.vehicles.values()] == [
        (v.id,v.site,v.parking_space_id) for v in restored.fleet.vehicles.values()], 'Parking claims changed on restore'
    return dict(buildings=len(city.buildings), categories=dict(Counter(b.category.value for b in city.buildings)),
                parking_lots=len(lots),shared_lots=sum(len(bs)>1 for bs in members.values()),
                parking_spaces=len(parked),parked_cars=sum(v.kind=='car' for v in runtime.fleet.vehicles.values()),
                parked_trucks=sum(v.kind=='truck' for v in runtime.fleet.vehicles.values()),
                buildings_with_access=len(city.buildings),overlaps=conflicts,
                overflow_rejected=len(lots),save_restore='passed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--world',type=Path,help='check an existing vacant imported world instead')
    args = parser.parse_args(argv)
    start = perf_counter()
    if args.world:
        city = world_from_dict(json.loads(args.world.read_text())).city_map
        if city.gameplay_state:
            parser.error('Use a vacant world; this check fills every parking space')
    else:
        root = ROOT/'benchmarks/arcata'
        city,_,_ = build_city([root/'arcata-roads-2026-06-01.json'],root/'arcata-city-boundary.osm',
                              building_paths=[root/'arcata-buildings-neighborhood.osm'])
    report = check_parking(city)
    print(json.dumps(dict(report,wall_seconds=round(perf_counter()-start,2))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
