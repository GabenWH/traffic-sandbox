"""Sample exclusive phase costs on one tick in 17; excludes ticks >=50 ms.

Pass the same arguments as run_arcata_city_workday.py, including --output.
Other ticks keep wrappers installed with detailed timing inactive.
"""
import json,sys,time,atexit
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import profile_commute_phases as p
Base=p.PhaseClock
class SampleClock(Base):
 def __init__(self):
  super().__init__();self.i=0;self.samples=[];self.baseline=[];self.totals={}; global clock;clock=self

  from native_spawning import NativeRoadSimulation
  from native_traffic import NativeTrafficEngine
  from traffic_testbed import RoadVehicleSimulation
  from transit import TransitSimulation
  from simulation_profiler import SimulationProfiler
  import native_shared
  for cls,methods,prefix in [
   (NativeRoadSimulation,('update','publish_random'),'bridge'),
   (NativeTrafficEngine,('profile_snapshot','sync','completed_pedestrians','pedestrian_count'),'engine_io'),
   (RoadVehicleSimulation,('update','sync_network','_prepare_signal_frame','_signal_step_limit','_native_backend'),'road'),
   (TransitSimulation,('_check_network','_finish_walk','_service','_trim_walk_routes'),'transit_detail'),
   (SimulationProfiler,('record_tick',),'diagnostics')]:
   for name in methods:setattr(cls,name,self.wrap(getattr(cls,name),prefix+'.'+name))
  native_shared.completed_views=self.wrap(native_shared.completed_views,'engine_io.completed_views')
 def update(self,method,sim_time,dt):
  self.i+=1
  if self.i%17:
   t=time.perf_counter_ns()
   try:return method(dt)
   finally:
    n=time.perf_counter_ns()-t
    if n<50_000_000:self.baseline.append(n)
  else:
   self.rows={};self.active=True;root=self.enter('update.other');start=root[1]
   try:return method(dt)
   finally:
    wall,cpu=self.leave(root);self.active=False;self.ticks+=1;self.total_wall+=wall;self.total_cpu+=cpu
    if wall<50_000_000:
     self.samples.append(wall)
     for k,v in self.rows.items():
      row=self.totals.setdefault(k,[0,0]);row[0]+=v[0];row[1]+=v[4]
def save():
 c=globals().get('clock')
 if not c:return
 n=len(c.samples);data={'sample_count':n,'baseline_count':len(c.baseline),'sample_mean_ms':sum(c.samples)/n/1e6 if n else 0,'baseline_mean_ms':sum(c.baseline)/len(c.baseline)/1e6 if c.baseline else 0,'phases':{k:{'exclusive_ms_per_sample':v[0]/n/1e6,'calls_per_sample':v[1]/n} for k,v in c.totals.items()}}
 (Path(sys.argv[sys.argv.index('--output')+1])/'ordinary_tick_profile.json').write_text(json.dumps(data,indent=2))
atexit.register(save)
p.PhaseClock=SampleClock
p.main()
