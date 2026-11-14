"""Reproducible authored-city stress scenario; synthetic premises on cached Arcata roads."""
import sys,json,time,random,traceback,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collections import Counter
from city import Building,Parcel
from models import BuildablePhase,point_at_polyline_distance,polyline_length
from city_simulation import CitySimulation
from building_operations import validate_operation
from households import Household,HousingMemory
from town_simulation import Resident
from transit import BusStop,BusLine,Bus
from mobility import nearest_lane_position
from run_arcata_scale_test import build_city

AUTHORED=os.environ.get('STRESS_AUTHORED_JOBS')=='1'
OUT=Path('benchmarks/arcata/results/resource-workday-1000'+('-authored-jobs' if AUTHORED else ''));OUT.mkdir(parents=True,exist_ok=True)
t0=time.perf_counter()
def log(**kw):print(json.dumps(dict(wall=round(time.perf_counter()-t0,2),**kw)),flush=True)
root=Path(__file__).resolve().parents[1]
city,_,meta=build_city([root/'benchmarks/arcata/arcata-roads-2026-06-01.json'],root/'benchmarks/arcata/arcata-city-boundary.osm')
log(stage='map_loaded',roads=len(city.roads))
roads=[r for r in city.roads if r.lanes and r.pedestrian_lanes]
hub=next(r for r in roads if r.name.startswith('H Street'))
def point(r,f=.5):
 l=r.pedestrian_lanes[0];return point_at_polyline_distance(list(l.points),polyline_length(list(l.points))*f)
hp=point(hub);chosen=[]
for r in sorted(roads,key=lambda r:r.id):
 try:
  city.find_pedestrian_route(point(r),hp);city.find_pedestrian_route(hp,point(r))
 except ValueError:continue
 chosen.append(r)
 if len(chosen)%25==0:log(stage='preflight',connected=len(chosen))
 if len(chosen)>=100:break
log(stage='connected_roads',count=len(chosen))
rng=random.Random(20261031);rng.shuffle(chosen)
def add(i,role,residents=0,jobs=0,inputs=None,output=None,rate=0,targets=None,stock=None):
 r=chosen[i%len(chosen)];p=point(r,.1+.8*((i//len(chosen))%10)/9)
 b=Building(f'{role}-{i}',Parcel(p[0]-10,p[1]-10,20,20),residents=residents,jobs=jobs,id=f'stress-{i}',phase=BuildablePhase.OPERATIONAL,
 operation=validate_operation(dict(role=role,inputs=inputs or {},output=output,rate=rate,targets=targets or {})))
 b.inventory.amounts.update(stock or {});city.buildings.append(b);city.parcels.append(b.parcel);return b
homes=[add(i,'home',residents=4 if i<500 else 8,stock={'food':6 if i<500 else 12}) for i in range(1000)]
business=[]
for j in range(20):
 role='market' if j<8 else ('cafe' if j<16 else 'clinic')
 business.append(add(1000+j,role,jobs=150,inputs={},output=None,rate=0,targets={'medicine':100} if role=='clinic' else {'food':1000},stock={'medicine':100} if role=='clinic' else {'food':500,'grain':500}))
farms=[add(1020+i,'farm',jobs=150,inputs={'seed':.1},output='grain',rate=12,stock={'seed':5000,'grain':1000}) for i in range(3)]
factory=add(1023,'bakery',jobs=500,inputs={'grain':1},output='food',rate=12,targets={'grain':10000},stock={'grain':10000,'food':3000})
company=add(1024,'construction_company',jobs=20)
site=add(1025,'workplace');site.phase=BuildablePhase.UNDER_CONSTRUCTION;site.construction_workers=2;site.construction_work=7200
from resources import load_construction_catalog
from construction import ConstructionSimulation,UnlimitedConstructionProvider
from traffic_testbed import RoadVehicleSimulation
traffic=RoadVehicleSimulation(update_mode='cpp',spawn_interval=1000000)
resources,trucks=load_construction_catalog();construction=ConstructionSimulation(resources,trucks,UnlimitedConstructionProvider(),road_vehicles=traffic)
runtime=CitySimulation(city,traffic,construction)
log(stage='runtime_ready',buildings=len(city.buildings))
# Twelve spatially spread stops with a shared central transfer stop, three lines.
refs=[company]
from math import dist
hubpos=runtime.sites[company.id]['road_position']
for i in range(1000):
 b=homes[(i*97)%1000];pos=runtime.sites[b.id]['road_position']
 if pos is None or any(dist(pos.point,runtime.sites[x.id]['road_position'].point)<300 for x in refs):continue
 if city.find_vehicle_route_between(hubpos,pos) is None or city.find_vehicle_route_between(pos,hubpos) is None:continue
 refs.append(b)
 if len(refs)>=11:break
if len(refs)<7:raise RuntimeError('Insufficient bus-accessible stops')
for b in refs:
 s=runtime.sites[b.id]
 runtime.transit.add_stop(BusStop(b.id,s['road_position'],s['walk_point']))
for n in range(3):
 stops=[refs[0].id]+[b.id for b in refs[1+n::3]]
 # Avoid stops sharing the exact physical lane access.
 unique=[]
 for sid in stops:
  if all(runtime.transit.stops[sid].road_position.point!=runtime.transit.stops[x].road_position.point for x in unique):unique.append(sid)
 lid=f'stress-line-{n}';runtime.transit.add_line(BusLine(lid,tuple(unique),headway_seconds=300))
 for k in range(4):runtime.transit.add_bus(Bus(f'{lid}-{k}',lid,capacity=60,service_at=21600,service_until=86400,fuel_liters=1000))
log(stage='bus_network',lines=len(runtime.transit.lines),buses=len(runtime.transit.buses))
# Bulk seed identities; call real assignment/scheduling once to avoid timing repeated UI invitations.
for home in homes:
 for j in range(home.residents//4):
  hid=f'household-{runtime._next_household}';runtime._next_household+=1;members=[]
  for k in range(4):
   pid=runtime._next_person;runtime._next_person+=1
   runtime.residents[pid]=Resident(pid,home.id,k<2,mode='bus',workplace=None);members.append(pid);runtime._membership[pid]=hid
  runtime.households[hid]=Household(hid,home.id,members,memory=HousingMemory())
runtime._refresh_occupancy();runtime._sync_workforce_mode()
log(stage='population_seeded',residents=len(runtime.residents))
if AUTHORED:
 workplaces=[company,*farms,factory,*business];assigned=Counter();cursor=0
 for p in runtime.residents.values():
  if not p.worker:continue
  for _ in workplaces:
   b=workplaces[cursor%len(workplaces)];cursor+=1
   if assigned[b.id]<b.jobs:
    p.workplace=b.id;assigned[b.id]+=1;break
runtime.assign_jobs();runtime._wake_economy()
for b in [*business,*farms,factory]:
 try:runtime.commission_truck(b.id)
 except ValueError:pass
runtime.initial_fuel=sum(v.fuel_liters for v in runtime.fleet.vehicles.values())+sum(b.fuel_liters for b in runtime.transit.buses.values())
configuration=dict(employment_setup='authored job roster' if AUTHORED else 'automatic job selection',houses=500,apartments=500,population=len(runtime.residents),businesses=20,farms=3,factory=1,buses=len(runtime.transit.buses),lines=len(runtime.transit.lines),source=meta,synthetic_locations=True)
(OUT/'configuration.json').write_text(json.dumps(configuration,indent=2))
log(stage='assigned',workers=sum(p.worker for p in runtime.residents.values()),assigned=sum(p.workplace is not None for p in runtime.residents.values()))
runtime.time=runtime.transit.time=runtime.transit.traffic.elapsed_time=21600.0
runtime.transit.engine._call('nt_clock',21600.0,0.0,0.0)
runtime._last_economy=runtime._last_construction=runtime._last_construction_work=21600.0
runtime._last_household_economy=21600.0
import heapq
runtime._events=[(max(t,21600.0),seq,kind,value) for t,seq,kind,value in runtime._events];heapq.heapify(runtime._events)
frames=[]
watch_seconds=int(os.environ.get('STRESS_WATCH_SECONDS','0'))
if watch_seconds:
 import threading
 main_thread=threading.get_ident()
 def watch():
  start=time.perf_counter()
  while True:
   time.sleep(15)
   sample=dict(elapsed=time.perf_counter()-start,time=runtime.time,transit_time=runtime.transit.time,states=dict(Counter(p.state for p in runtime.residents.values())),access_cache=len(runtime._access_times),stack=traceback.format_stack(sys._current_frames()[main_thread]))
   with (OUT/'watch.jsonl').open('a') as f:f.write(json.dumps(sample)+'\n')
   log(stage='watch',elapsed=sample['elapsed'],time=sample['time'],states=sample['states'])
   if sample['elapsed']>=watch_seconds:os._exit(124)
 threading.Thread(target=watch,daemon=True).start()
try:
 for hour in range(6,21):
  start=time.perf_counter()
  if hour>6:runtime.update(3600)
  f=runtime.report();f.update(hour=hour,step_wall=time.perf_counter()-start,states=dict(Counter(p.state for p in runtime.residents.values())),staff=dict(runtime.staff),bus_waiting=sum(map(len,runtime.transit.queues.values())),bus_onboard=sum(len(b.passengers) for b in runtime.transit.buses.values()),production=runtime.produced,unmet=runtime.unmet,construction_phase=str(site.phase))
  frames.append(f);(OUT/'hourly.json').write_text(json.dumps(frames,indent=2));log(stage='hour',**f)
 summary=dict(configuration=configuration,hours=frames,wall_seconds=time.perf_counter()-t0,business_inventory={b.id:dict(b.inventory.amounts) for b in [*business,*farms,factory]},events=dict(Counter(e['event'] for e in runtime.events)),transit_events=dict(Counter(e['event'] for e in runtime.transit.events)))
 (OUT/'summary.json').write_text(json.dumps(summary,indent=2));log(stage='complete',wall_seconds=summary['wall_seconds'])
except Exception:
 (OUT/'error.txt').write_text(traceback.format_exc());raise
