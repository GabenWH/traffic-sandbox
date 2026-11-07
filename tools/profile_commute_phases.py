#!/usr/bin/env python3
"""Attribute slow workday updates to exclusive wall/main-thread CPU/GC time.

Wraps selected coarse phases only; does not trace every Python function. Phase
timings include instrumentation overhead and are diagnostic, not speed scores.
"""
import gc
import json
from pathlib import Path
import sys
import threading
import time
from functools import wraps

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import run_arcata_city_workday as runner


class PhaseClock:
    def __init__(self):
        self.owner=threading.get_ident();self.stack=[];self.rows={};self.active=False
        self.frames=[[None,0,0,0,0] for _ in range(64)]
        self.slow=[];self.total_wall=self.total_cpu=0;self.ticks=0
        self.gc_starts={};self.gc_events=[]

    def enter(self,name):
        frame=self.frames[len(self.stack)]
        frame[0]=name;frame[1]=time.perf_counter_ns();frame[2]=time.thread_time_ns()
        frame[3]=frame[4]=0
        self.stack.append(frame);return frame

    def leave(self,frame):
        wall=time.perf_counter_ns()-frame[1];cpu=time.thread_time_ns()-frame[2]
        self.stack.pop()
        if self.stack:self.stack[-1][3]+=wall;self.stack[-1][4]+=cpu
        row=self.rows.setdefault(frame[0],[0,0,0,0,0])
        row[0]+=wall-frame[3];row[1]+=cpu-frame[4];row[2]+=wall;row[3]+=cpu;row[4]+=1
        return wall,cpu

    def wrap(self,method,name):
        @wraps(method)
        def timed(*args,**kwargs):
            if not self.active or threading.get_ident()!=self.owner:return method(*args,**kwargs)
            frame=self.enter(name)
            try:return method(*args,**kwargs)
            finally:self.leave(frame)
        return timed

    def callback(self,phase,info):
        thread=threading.get_ident();key=(thread,info['generation'])
        if phase=='start':self.gc_starts[key]=time.perf_counter_ns()
        elif key in self.gc_starts:
            self.gc_events.append((thread,info['generation'],self.gc_starts.pop(key),time.perf_counter_ns()))
        if not self.active or thread!=self.owner:return
        if phase=='start':self.enter('GC.gen'+str(info['generation']))
        elif self.stack and self.stack[-1][0].startswith('GC.'):
            self.leave(self.stack[-1])

    def update(self,method,sim_time,dt):
        self.rows={};self.active=True
        root=self.enter('update.other')
        start=root[1];process_start=time.process_time_ns()
        try:return method(dt)
        finally:
            wall,cpu=self.leave(root);self.active=False
            self.ticks+=1;self.total_wall+=wall;self.total_cpu+=cpu
            if wall>=50_000_000:
                self.slow.append(dict(sim_start=sim_time,start_ns=start,end_ns=start+wall,
                    wall_ms=wall/1e6,thread_cpu_ms=cpu/1e6,process_cpu_ms=(time.process_time_ns()-process_start)/1e6,
                    phases=[dict(name=k,exclusive_wall_ms=v[0]/1e6,exclusive_cpu_ms=v[1]/1e6,
                                 inclusive_wall_ms=v[2]/1e6,inclusive_cpu_ms=v[3]/1e6,calls=v[4])
                            for k,v in sorted(self.rows.items(),key=lambda p:p[1][0],reverse=True)]))


def profile(runtime,original,kwargs,out):
    from city_simulation import CitySimulation
    from transit import TransitSimulation
    from parking_trips import ParkingTrips
    from commute_routing import BackgroundRoutes
    from native_spawning import NativeRoadSimulation
    from native_walking import NativeWalkingGraph
    from native_traffic import NativeTrafficEngine
    clock=PhaseClock();patches=[]
    def patch(cls,method,name):
        previous=getattr(cls,method);patches.append((cls,method,previous,method in cls.__dict__))
        setattr(cls,method,clock.wrap(previous,name))
    for method in ('sync_network','_run_event','_service_departures','_arrivals','_settle_economy','_settle_households'):
        patch(CitySimulation,method,'city.'+method)
    for method in ('update','journey_path','walking_cost'):
        patch(TransitSimulation,method,'transit.'+method)
    for method in ('configure','receive_generated','publish_bookkeeping'):
        patch(NativeRoadSimulation,method,'traffic.'+method)
    for method in ('_attempt','defer','wake_capacity'):
        patch(ParkingTrips,method,'parking.'+method)
    for method in ('get_route','begin_update'):
        patch(BackgroundRoutes,method,'routing.'+method)
    for method in ('__init__','route','cost','_project','_tree'):
        patch(NativeWalkingGraph,method,'walking.'+method)
    call=NativeTrafficEngine._call
    native_calls={name:clock.wrap(call,'native.'+name) for name in
                  ('nt_step','nt_generate','nt_rng_set','nt_sources','nt_signal_aspects','nt_admit','nt_route','nt_graph')}
    def native(engine,name,*args):
        return native_calls.get(name,call)(engine,name,*args)
    patches.append((NativeTrafficEngine,'_call',call,True));NativeTrafficEngine._call=native
    update=runtime.update
    runtime.update=lambda dt:clock.update(update,runtime.time,dt)
    gc.callbacks.append(clock.callback)
    try:return original(runtime,**kwargs)
    finally:
        runtime.update=update;gc.callbacks.remove(clock.callback)
        for cls,method,previous,owned in reversed(patches):
            if owned:setattr(cls,method,previous)
            else:delattr(cls,method)
        for row in clock.slow:
            row['all_thread_gc_overlap_ms']=sum(max(0,min(row['end_ns'],end)-max(row['start_ns'],begin))
                for thread,gen,begin,end in clock.gc_events)/1e6
        out.joinpath('phase_profile.json').write_text(json.dumps(dict(
            notes='Exclusive phase times partition each tick. GC is its own phase; do not add inclusive times. CPU is the simulation owner thread only; wall-minus-CPU is waiting/descheduling, not proof of a specific cause.',
            ticks=clock.ticks,mean_wall_ms=clock.total_wall/max(1,clock.ticks)/1e6,
            mean_thread_cpu_ms=clock.total_cpu/max(1,clock.ticks)/1e6,slow_ticks=clock.slow),indent=2))


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--output' not in args:raise ValueError('An explicit new --output directory is required')
    out=Path(args[args.index('--output')+1]);original=runner.run_workday
    runner.run_workday=lambda runtime,**kwargs:profile(runtime,original,kwargs,out)
    try:return runner.main(args)
    finally:runner.run_workday=original


if __name__=='__main__':raise SystemExit(main())
