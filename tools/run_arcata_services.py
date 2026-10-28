"""Staffed, multi-business Arcata scenario with a shared-stop transit network."""
import sys,json,time,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from city import Building,Parcel
from persistent_fleet import FleetVehicle
from transit import TransitSimulation,Bus,BusLine,BusStop
from mobility import vehicle_route_points
from town_services import ServiceTown,Business
from run_arcata_town import build_arcata


def build_services(population=1000):
    town,source=build_arcata(population,work_start=60,work_end=14400)
    # Reuse the preflighted access sites for fictional business premises.
    homeids=[s for s in town.sites if s.startswith('home-')]
    definitions=[('farm-north','farm',0,{'crop':1},'grain',12,{}),
                 ('farm-south','farm',-1,{'crop':1},'grain',12,{}),
                 ('bakery-north','bakery',len(homeids)//4,{'grain':1},'food',6,{'grain':400}),
                 ('bakery-south','bakery',len(homeids)*3//4,{'grain':1},'food',6,{'grain':400}),
                 ('cafe-north','cafe',len(homeids)//3,{'grain':1},'food',4,{'grain':200}),
                 ('cafe-south','cafe',len(homeids)*2//3,{'grain':1},'food',4,{'grain':200}),
                 ('clinic','clinic',len(homeids)//2,{},None,0,{'medicine':50})]
    specs=[]
    for sid,kind,index,inputs,output,rate,targets in definitions:
        reference=town.sites[homeids[index]];point=reference['walk_point']
        b=Building(f'{sid} (scenario)',Parcel(point[0]+20,point[1]+20,25,25),jobs=100,id=sid)
        if kind=='farm':b.inventory.amounts.update(crop=5000,grain=200)
        elif kind=='clinic':b.inventory.amounts.update(medicine=50)
        else:b.inventory.amounts.update(grain=100,food=40)
        town.city.buildings.append(b);town.city.parcels.append(b.parcel)
        town.sites[sid]=dict(building=b,walk_point=point,road_position=reference['road_position'],parking_capacity=100)
        specs.append(Business(sid,kind,inputs,output,rate,targets))
    town.sites['work']['building'].name='Central food market (scenario)'
    town.sites['work']['building'].inventory.amounts={'food':500}
    specs.append(Business('work','market',{},None,0,{'food':1000}))
    workers=[p for p in town.residents.values() if p.worker]
    workplaces=[b.site for b in specs]
    for i,p in enumerate(workers):p.workplace=workplaces[i%len(workplaces)]
    town.transit.engine.close()
    town.transit=TransitSimulation(town.city)
    town.fleet.transit=town.transit
    town.__class__=ServiceTown;town.configure_services(specs)
    from collections import deque
    town.handling={sid:deque() for sid in town.sites}
    # Shared stop IDs are actual transfer nodes. Both lines serve the central
    # market. Feeder service joins the market to both farm scenarios.
    selected=sorted(set(range(0,len(homeids),max(1,len(homeids)//8)))|{len(homeids)-1})
    for index in selected:
        sid=homeids[index];site=town.sites[sid]
        town.transit.add_stop(BusStop(sid,site['road_position'],site['walk_point']))
    for sid in workplaces:
        site=town.sites[sid];town.transit.add_stop(BusStop(sid,site['road_position'],site['walk_point']))
    # Adjacent premises can share the same physical road access but remain
    # separate authored stops. Avoid degenerate bus legs by serving those
    # destinations through the shared residential stop instead.
    def distinct(stops):
        result=[]
        for stop in stops:
            point=town.transit.stops[stop].road_position.point
            if not any(town.transit.stops[s].road_position.point==point for s in result):result.append(stop)
        return tuple(result)
    groups=[('north',distinct(['work',*homeids[0:len(homeids)//2: max(1,len(homeids)//8)],'clinic','bakery-north','cafe-north'])),
            ('south',distinct(['work',*homeids[len(homeids)//2::max(1,len(homeids)//8)],'bakery-south','cafe-south'])),
            ('farm',distinct(['work','farm-north','farm-south']))]
    # Register every route's residential stop even for small-population tests.
    for _,stops in groups:
        for sid in stops:
            if sid not in town.transit.stops:
                site=town.sites[sid];town.transit.add_stop(BusStop(sid,site['road_position'],site['walk_point']))
    for name,stops in groups:
        town.transit.add_line(BusLine(name,stops,headway_seconds=180))
        for i in range(2):town.transit.add_bus(Bus(f'{name}-bus-{i}',name,capacity=60,
                              service_at=60+i*180,service_until=21600))
    served={stop for line in town.transit.lines.values() for stop in line.stop_ids}
    town.transit.stops={sid:s for sid,s in town.transit.stops.items() if sid in served}
    for i in range(2,4):town.fleet.add(FleetVehicle(f'truck-{i}','truck','work',capacity=120,
                                        fuel_liters=100,liters_per_mile=.3,length=28,width=8))
    town.initial_resources=sum(sum(s['building'].inventory.amounts.values()) for s in town.sites.values())
    town.initial_fuel=sum(v.fuel_liters for v in town.fleet.vehicles.values())+sum(b.fuel_liters for b in town.transit.buses.values())
    patients=[p for p in town.residents.values() if not p.worker][:20]
    for i,p in enumerate(patients):town.schedule(120+i*15,'service_visit',(p.id,'clinic','care'))
    for i,p in enumerate(workers[:20]):town.schedule(900+i*15,'service_visit',(p.id,'cafe-north' if i%2 else 'cafe-south','meal'))
    source.update(numeric_speed_limit_segments=sum(r.speed_limit_mph is not None for r in town.city.roads),fallback_speed_mph=25,business_locations='Fictional business roles attached to preflighted road-access sites',
                  capacities='Six buses, sixty seats each',speed_limits='Numeric OSM maxspeed tags enforced by shared native driving; absent or textual values use 25 mph fallback')
    return town,source


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--duration',type=int,default=3600)
    args=parser.parse_args();start=time.perf_counter();town,source=build_services()
    print(json.dumps(dict(businesses=len(town.businesses),stops=len(town.transit.stops),lines=len(town.transit.lines))),flush=True)
    frames=[]
    for minute in range(args.duration//60+1):
        if minute:town.update(60)
        f=town.report();f.update(
          sites=[dict(id=sid,position=s['walk_point'],food=s['building'].inventory.amounts.get('food',0),
                      residents=s['building'].residents,kind=town.businesses[sid].kind if sid in town.businesses else 'home',
                      inventory=dict(s['building'].inventory.amounts),staff=town.staff[sid]) for sid,s in town.sites.items()],
          cars=[dict(id=c.id,position=c.position,kind=c.source_type) for c in town.transit.traffic.cars],
          people=[dict(id=p.id,position=(p.x,p.y)) for p in town.transit.engine.pedestrian_states()],
          parked_cars=sum(v.phase=='parked' and v.kind=='car' for v in town.fleet.vehicles.values()),
          bus_waiting=sum(len(q) for q in town.transit.queues.values()),bus_onboard=sum(len(b.passengers) for b in town.transit.buses.values()),
          stops=[dict(id=sid,position=s.walk_point,waiting=sum(len(q) for (line,stop),q in town.transit.queues.items() if stop==sid)) for sid,s in town.transit.stops.items()],
          buses=[dict(id=b.id,line=b.line_id,passengers=len(b.passengers),capacity=b.capacity,phase=b.phase,position=b.position) for b in town.transit.buses.values()])
        assert f['at_home']+f['at_work']+f['commuting']+f['at_services']==1000
        assert abs(f['resource_balance_error'])<1e-5
        assert all(b['passengers']<=60 for b in f['buses'])
        frames.append(f)
        if minute%5==0:print(json.dumps({k:f[k] for k in ('time','at_work','bus_waiting','deliveries','treated','meals_served','resource_balance_error')}),flush=True)
    data=dict(duration=args.duration,real_network=True,source=source,roads=[r.centerline for r in town.city.roads],frames=frames,
              summary=town.report(),wall_seconds=time.perf_counter()-start,
              lines=[dict(id=l.id,stops=l.stop_ids,headway=l.headway_seconds,geometry=[vehicle_route_points(r) for r in town.transit.legs[l.id]]) for l in town.transit.lines.values()],
              events=town.transit.events+town.events,
              fleet=[dict(id=v.id,phase=v.phase,site=v.site,trips=v.trips,fuel=v.fuel_liters) for v in town.fleet.vehicles.values()])
    Path(args.out).write_text(json.dumps(data,separators=(',',':')))
    print(json.dumps(dict(summary=data['summary'],wall_seconds=data['wall_seconds'])),flush=True)


if __name__=='__main__':main()
