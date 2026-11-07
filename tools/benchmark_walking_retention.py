#!/usr/bin/env python3
"""Controlled Arcata parking admission and query-retention comparisons.

This is not a full commute replay. Full-GC probes are deliberately triggered
inside a 50 ms city update. Candidate enumeration stresses retention with the
same scheduled queries, without actor motion. All measurements are serial.
"""
import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import city_simulation
from native_walking import NativeWalkingGraph
from persistent_fleet import FleetVehicle
from walking_cache import WalkingRouteCache
from tools.run_arcata_city_workday import build_city,build_scenario,CommutePolicy

BASELINE='9e8d39218837ab68c757fa9f806aba1f410ee03d'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--wait-for',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    def emit(x):
        x=dict(elapsed_wall=round(time.perf_counter()-started,3),**x)
        line=json.dumps(x,allow_nan=False);print(line,flush=True)
        with (args.output/'metrics.jsonl').open('a') as f:f.write(line+'\n')
    city,_,_=build_city([ROOT/'benchmarks/arcata/arcata-roads-2026-06-01.json'],ROOT/'benchmarks/arcata/arcata-city-boundary.osm',building_paths=[ROOT/'benchmarks/arcata/arcata-buildings-citywide-2026-11-04.json.gz'],building_progress=lambda row:emit(dict(stage='setup_progress',detail=row)))
    if args.wait_for:
        emit(dict(stage='awaiting_serial_measurement'))
        while not args.wait_for.exists():time.sleep(.25)
    original_class=city_simulation.ParkingTrips
    module=types.ModuleType('retention_benchmark_baseline')
    code=subprocess.check_output(['git','show',BASELINE+':parking_trips.py'],cwd=ROOT)
    exec(compile(code,BASELINE+':parking_trips.py','exec'),module.__dict__)
    original_route=NativeWalkingGraph.route
    queries=0
    def route(obj,*a,**kw):
        nonlocal queries
        queries+=1
        return original_route(obj,*a,**kw)
    NativeWalkingGraph.route=route
    results={}
    try:
        for label,parking,cache_factory in [('baseline_eager_unbounded',module.ParkingTrips,dict),('fixed_lazy_bounded',original_class,WalkingRouteCache)]:
            city_simulation.ParkingTrips=parking
            r,config=build_scenario(city,cars=1000,seed=42,start_hour=7,population=16000,commute_policy=CommutePolicy())
            r.transit._walk_cache=cache_factory()
            try:
                # Controlled cold admissions; alternate forced-full primary lots.
                drivers=[p for p in r.residents.values() if p.mode=='car' and r.sites[p.workplace]['road_position'] is not None and r.fleet._lot_key(p.home)!=r.fleet._lot_key(p.workplace)]
                drivers.sort(key=lambda p:(-len(r.parking_trips.access.candidates(p.workplace)),p.id))
                selected=[];seen=set()
                for p in drivers:
                    if p.workplace not in seen:selected.append(p);seen.add(p.workplace)
                    if len(selected)==12:break
                probes=[]
                for i,p in enumerate(selected):
                    if i%2:
                        n=0
                        while r.fleet._available_space(r.fleet.vehicles[p.car_id],p.workplace) is not False:
                            r.fleet.add(FleetVehicle(f'probe-{i}-{n}','car',p.workplace));n+=1
                    q=queries;t=time.perf_counter_ns();admitted=r._safe_depart(p)
                    row=dict(person=p.id,destination=p.workplace,chosen=r.fleet.vehicles[p.car_id].destination,primary_forced_full=bool(i%2),admitted=admitted,wall_ms=(time.perf_counter_ns()-t)/1e6,walking_queries=queries-q,cache_entries=len(r.transit._walk_cache))
                    probes.append(row);emit(dict(stage='admission',variant=label,**row))
                results[label]=dict(admissions=probes)
                failed=next((row for row in probes if not row['admitted']),None)
                if failed is not None:
                    # The explicit API probes above can block. Now test the
                    # same difficult destination through actual 50-ms updates.
                    r.update(.05)  # separate cold native configuration
                    person=r.residents[failed['person']]
                    r.parking_trips.plans.pop(person.id,None)
                    r.transit._walk_cache.clear()
                    r.configure_commutes(r.commute_policy)
                    r._pending_departures[person.id]=(False,r.time)
                    ticks=[]
                    for tick in range(20):
                        q=queries;t=time.perf_counter_ns();r.update(.05)
                        ticks.append(dict(tick=tick,wall_ms=(time.perf_counter_ns()-t)/1e6,walking_queries=queries-q))
                    results[label]['difficult_destination_updates']=dict(person=person.id,destination=person.workplace,ticks=ticks,max_walking_queries=max(t['walking_queries'] for t in ticks),max_tick_ms=max(t['wall_ms'] for t in ticks))
                    emit(dict(stage='difficult_destination',variant=label,**results[label]['difficult_destination_updates']))
            finally:r.close()
            city.gameplay=None
            del r
            gc.collect(2)
        before=results['baseline_eager_unbounded']['admissions']
        after=results['fixed_lazy_bounded']['admissions']
        signature=lambda rows:[(x['person'],x['destination'],x['primary_forced_full'],x['admitted'],x['chosen']) for x in rows]
        assert signature(before)==signature(after),'Admission outcomes changed between variants'
        # Same current world logic for both retention policies; force complete
        # options enumeration to feed equivalent hypothetical path workloads.
        city_simulation.ParkingTrips=original_class
        r,config=build_scenario(city,cars=1000,seed=42,start_hour=7,population=16000,commute_policy=CommutePolicy())
        try:
            r.update(.05)
            due=sorted((r.work_start+r.commute_policy.offset(p.id,p.workplace),p.id) for p in r.residents.values() if p.worker and p.workplace and r.work_start+r.commute_policy.offset(p.id,p.workplace)<=8.75*3600)
            # Compile walking topology outside timing and keep it identical.
            p=r.residents[due[0][1]]
            r.transit._walk(r.sites[p.home]['walk_point'],r.sites[p.workplace]['walk_point'])
            original_event=r._run_event
            def event(self,kind,value):
                if kind=='retention_gc_probe':
                    key,_=value;self._scheduled.discard(key);gc.collect(2)
                else:original_event(kind,value)
            r._run_event=types.MethodType(event,r)
            for label,factory in [('unbounded_query_cache',dict),('bounded_query_cache',WalkingRouteCache)]:
                r.transit._walk_cache.clear();r.transit._walk_cache=factory();r.parking_trips._options.clear();gc.collect(2)
                q=queries;hydrate_start=time.perf_counter_ns()
                for i,(_,pid) in enumerate(due):
                    p=r.residents[pid]
                    try:
                        if p.mode=='car':tuple(r.parking_trips.options(p.workplace))
                        else:r.transit._walk(r.sites[p.home]['walk_point'],r.sites[p.workplace]['walk_point'])
                    except ValueError:pass
                    if i%1000==0:emit(dict(stage='retention_workload',variant=label,tasks=i+1,cache_entries=len(r.transit._walk_cache)))
                gc.collect(2)
                tracked=len(gc.get_objects(2));samples=[]
                for repeat in range(3):
                    r._once('retention-gc-probe',r.time,'retention_gc_probe')
                    t=time.perf_counter_ns();r.update(.05)
                    samples.append((time.perf_counter_ns()-t)/1e6)
                row=dict(tasks=len(due),walking_queries=queries-q,cache_entries=len(r.transit._walk_cache),geometry_units=getattr(r.transit._walk_cache,'units',None),generation_2_objects=tracked,forced_gc_tick_ms=samples,median_forced_gc_tick_ms=statistics.median(samples),workload_wall_ms=(time.perf_counter_ns()-hydrate_start)/1e6,population_accounted_for=sum(Counter(p.state for p in r.residents.values()).values()))
                results[label]=row;emit(dict(stage='retention_complete',variant=label,**row))
                assert row['population_accounted_for']==16000
                if label=='bounded_query_cache':assert row['cache_entries']<=512 and row['geometry_units']<=65536
        finally:r.close()
        result=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),baseline_parking_commit=BASELINE,configuration=config,results=results,limits=['Controlled cold admissions and forced full-GC updates, not a full-morning throughput comparison.','Retention workload deliberately exhausts all alternative candidates to test worst-case retention; ordinary fixed admissions are lazy and bounded.','Second retention pass can repeat previously evicted queries; retained geometry rather than query count is the controlled cache bound.','No active commuter mode selection is enabled.'])
        (args.output/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        emit(dict(stage='complete',summary=str(args.output/'summary.json')))
    finally:
        city_simulation.ParkingTrips=original_class;NativeWalkingGraph.route=original_route

if __name__=='__main__':main()
