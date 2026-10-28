"""Apply the town scenario to the cached Arcata OSM network, then run one day."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import time
from math import dist
from town_simulation import TownSimulation, build_town
from city import Parcel
from mobility import nearest_lane_position
from models import point_at_polyline_distance, polyline_length
from transit import BusStop, BusLine, Bus
from run_arcata_scale_test import build_city


def build_arcata(population=1000, work_start=27000, work_end=57600):
    root=Path(__file__).resolve().parents[1]
    city,_,metadata=build_city([root/'benchmarks/arcata/arcata-roads-2026-06-01.json'],
                               root/'benchmarks/arcata/arcata-city-boundary.osm')
    eligible=[r for r in city.roads if r.lanes and r.pedestrian_lanes]
    workroad=next(r for r in eligible if r.name.startswith('H Street'))
    def access(road):
        lane=road.pedestrian_lanes[0]
        point=point_at_polyline_distance(list(lane.points),polyline_length(list(lane.points))*.5)
        return point, nearest_lane_position(road.lanes[0],point)[0]
    workpoint,workpos=access(workroad)
    candidates=sorted((r for r in eligible if 700<dist(access(r)[0],workpoint)<5000),
                       key=lambda r:(-dist(access(r)[0],workpoint),r.id))
    template=build_town(population)
    homeids=[sid for sid in template.sites if sid.startswith('home-')]
    chosen=[]; rejected=0
    # Spread authored residential sites over the eligible connected streets.
    for road in candidates:
        point,pos=access(road)
        if any(dist(point,p)<180 for p,_ in chosen):
            continue
        try:
            city.find_pedestrian_route(point,workpoint)
            city.find_pedestrian_route(workpoint,point)
            if city.find_vehicle_route_between(pos,workpos) is None or city.find_vehicle_route_between(workpos,pos) is None:
                rejected+=1;continue
        except ValueError:
            rejected+=1;continue
        chosen.append((point,pos))
        if len(chosen)==len(homeids):break
    if len(chosen)!=len(homeids):raise RuntimeError('Insufficient connected residential sites')
    for sid,(point,pos) in zip(homeids+['work'],chosen+[(workpoint,workpos)]):
        site=template.sites[sid]
        site['walk_point'],site['road_position']=point,pos
        site['building'].parcel=Parcel(point[0],point[1]+20,30,30)
        city.buildings.append(site['building']);city.parcels.append(site['building'].parcel)
    town=TownSimulation(city,template.sites,list(template.residents.values()),work_start=work_start,work_end=work_end)
    a=town.sites[homeids[0]];b=town.sites['work']
    town.transit.add_stop(BusStop('A',a['road_position'],a['walk_point']))
    town.transit.add_stop(BusStop('B',b['road_position'],b['walk_point']))
    town.transit.add_line(BusLine('town-line',('A','B'),headway_seconds=120))
    for i in range(2):town.transit.add_bus(Bus(f'bus-{i}','town-line',capacity=40,
                         service_at=work_start,service_until=work_start+7200))
    for v in template.fleet.vehicles.values():town.fleet.add(v)
    town.initial_fuel=template.initial_fuel
    template.transit.engine.close()
    metadata.update(residential_sites=len(chosen),rejected_disconnected_sites=rejected,
                    household_locations='Synthetic sites along real roads, not mapped homes',
                    walking='Inferred road-owned sidewalks; campus footway data not imported')
    return town,metadata


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--population',type=int,default=1000)
    p.add_argument('--duration',type=int,default=86400);p.add_argument('--work-start',type=float,default=27000);p.add_argument('--work-end',type=float,default=57600)
    args=p.parse_args();start=time.perf_counter();town,metadata=build_arcata(args.population,args.work_start,args.work_end)
    print(json.dumps(metadata),flush=True)
    frames=[]
    for minute in range(args.duration//60+1):
        if minute:town.update(60)
        f=town.report();f.update(
            sites=[dict(id=sid,position=s['walk_point'],food=s['building'].inventory.amounts.get('food',0),residents=s['building'].residents) for sid,s in town.sites.items()],
            cars=[dict(id=c.id,position=c.position,kind=c.source_type) for c in town.transit.traffic.cars],
            people=[dict(id=p.id,position=(p.x,p.y)) for p in town.transit.engine.pedestrian_states()],
            parked_cars=sum(v.phase=='parked' and v.kind=='car' for v in town.fleet.vehicles.values()),
            bus_waiting=sum(len(q) for q in town.transit.queues.values()),bus_onboard=sum(len(b.passengers) for b in town.transit.buses.values()))
        frames.append(f)
        if minute%5==0:print(json.dumps(f if minute==1440 else {k:f[k] for k in ('time','at_home','at_work','commuting','deliveries')}),flush=True)
    data=dict(duration=args.duration,scenario='Real Arcata road network; fictional households, roles and resources',real_network=True,
              source=metadata,roads=[r.centerline for r in town.city.roads],frames=frames,summary=town.report(),
              wall_seconds=time.perf_counter()-start,
              fleet=[dict(id=v.id,kind=v.kind,site=v.site,phase=v.phase,trips=v.trips,fuel=v.fuel_liters) for v in town.fleet.vehicles.values()])
    target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(data,separators=(',',':')))
    try:
        saved=town.checkpoint()
        target.with_suffix('.checkpoint.json').write_text(json.dumps(saved,allow_nan=False))
        print('Quiescent checkpoint saved; restore not attempted in this harness',flush=True)
    except ValueError as e: print('End state not quiescent: '+str(e),flush=True)
    print(json.dumps(dict(summary=data['summary'],wall_seconds=data['wall_seconds'])),flush=True)


if __name__=='__main__':main()
