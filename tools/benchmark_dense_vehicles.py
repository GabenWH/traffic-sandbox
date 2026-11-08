"""Dense moving-vehicle and signal-queue benchmark; copy/shared state modes."""
import argparse,json,sys,time,statistics,random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from city import CityMap,Terrain
from mobility import lane_position_at_distance,vehicle_route_points
from traffic_testbed import RoadVehicleSimulation,RoutedRoadVehicle
from tools.benchmark_native_shared import setup
from tools.benchmark_native_spawning import make_city,summarize
parser=argparse.ArgumentParser(description='Dense active traffic, no economy or renderer; 5-second warmup and diagnostic phase timers.')
parser.add_argument('--mode',choices=('copy','shared'),default='copy')
parser.add_argument('--seconds',type=float,default=300)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if args.seconds<5 or abs(args.seconds/.05-round(args.seconds/.05))>1e-7:parser.error('seconds must be at least 5 and a multiple of 0.05')
if args.output.exists():parser.error('output already exists')
args.output.parent.mkdir(parents=True,exist_ok=True)

def platoons(fleet):
 city=CityMap(terrain=Terrain(trees=[]))
 for row in range(20):city.add_road([(0,row*100),(24000,row*100)])
 cars=[]
 for row,road in enumerate(city.roads):
  lane=next(l for l in road.lanes if l.direction=='forward')
  route=city.find_vehicle_route_between(lane_position_at_distance(lane,100),lane_position_at_distance(lane,23900))
  points=vehicle_route_points(route)
  for i in range(fleet//20):
   car=RoutedRoadVehicle(str(row),str(row)+'-end',route,points,25*22/15,'#37e6ff',id=f'platoon-{row}-{i}')
   car.place(1000+i*36);cars.append(car)
 traffic=RoadVehicleSimulation(update_mode='cpp',native_output_mode=args.mode,rng=random.Random(42),cars=cars,max_cars=fleet)
 traffic._native_backend(city);traffic.update(city,0)
 return city,traffic

results=[]
for label,fleet in [('platoons',1000),('signals',250),('signals',1000)]:
 if args.mode=='shared' and fleet==250:continue
 print(json.dumps({'stage':'setup','case':label,'fleet':fleet}),flush=True)
 if label=='platoons':city,traffic=platoons(fleet)
 else:
  city,controllers=make_city('signalized-crossing',42,max(1200,2*((fleet+3)//4*36+150)))
  traffic=setup(city,controllers,args.mode,fleet,42)
 try:
  for _ in range(100):traffic.update(city,.05)
  wall=[];phases={};completed=0;rows=[];active_sum=0;peak_active=0;over50=0
  for tick in range(round(args.seconds/.05)):
   start=time.perf_counter_ns();done=traffic.update(city,.05);elapsed=(time.perf_counter_ns()-start)/1e6
   wall.append(elapsed);completed+=len(done);active=len(traffic.cars);active_sum+=active;peak_active=max(peak_active,active);over50+=elapsed>50
   for name,value in traffic.profiler.samples[-1].timings_ms.items():phases.setdefault(name,[]).append(value)
   if tick%100==99:
    speeds=[c.speed for c in traffic.cars]
    sample=dict(seconds=round((tick+1)*.05,2),active=active,moving=sum(s>1 for s in speeds),stopped=sum(s<=1 for s in speeds),mean_speed_mph=statistics.fmean(speeds)*15/22 if speeds else 0,completed=completed,mean_tick_ms=statistics.fmean(wall[-100:]),max_tick_ms=max(wall[-100:]))
    rows.append(sample)
    if tick%1200==1199:print(json.dumps(dict(stage='progress',case=label,fleet=fleet,**sample)),flush=True)
  result=dict(case=label,initial_fleet=fleet,seconds=args.seconds,warmup_seconds=5,ticks=round(args.seconds/.05),output_mode=args.mode,mean_active=active_sum/len(wall),peak_active=peak_active,final_active=len(traffic.cars),completed=completed,moving_threshold_feet_per_second=1,mean_moving_sampled=statistics.fmean(r['moving'] for r in rows),final_moving=rows[-1]['moving'],mean_speed_mph_sampled=statistics.fmean(r['mean_speed_mph'] for r in rows),tick_ms=summarize(wall),ticks_over_50ms=over50,phases_mean_ms={k:statistics.fmean(v) for k,v in phases.items()},rows=rows)
  results.append(result);args.output.write_text(json.dumps(results,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('rows','phases_mean_ms')}),flush=True)
 finally:traffic._discard_native()
