#!/usr/bin/env python3
"""Timed citywide commute/parking workday on imported Arcata buildings.

Geometry and building categories come from the bundled citywide OSM extract.
Population, job capacities, food stocks, and job assignments are benchmark
assumptions. This does not add synthetic premises, production chains, or buses.
"""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import random
import statistics
import sys
import time
import threading
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from city import ZoneType
from city_simulation import CitySimulation
from households import Household, HousingMemory
from persistent_fleet import FleetVehicle
from tools.run_arcata_scale_test import build_city
from town_simulation import Resident
from commute_schedule import CommutePolicy

STEP = .05


class SetupBudgetExceeded(Exception):
    pass


def start_stack_watch(path,interval,started):
    """Capture only the main Python stack; never inspect mutable world data."""
    stop=threading.Event();main_thread=threading.get_ident()
    def watch():
        while not stop.wait(interval):
            frame=sys._current_frames().get(main_thread)
            if frame is None:return
            lines=traceback.format_stack(frame)
            del frame
            with path.open('a') as stream:
                stream.write(f'Wall {time.perf_counter()-started:.3f}s\n'+''.join(lines)+'\n')
    worker=threading.Thread(target=watch,name='stress-stack-watch',daemon=True)
    worker.start()
    return stop,worker


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hours',type=float,default=14,help='simulated hours (default: 14)')
    parser.add_argument('--start-hour',type=float,default=6,help='initial clock hour (default: 6)')
    parser.add_argument('--population',type=int,default=10000,help='exact resident count within imported housing capacity (default: 10000)')
    parser.add_argument('--cars',type=int,default=1000,help='household cars in the same simulation (default: 1000)')
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--departure-window-minutes',type=float,default=120,help='stable worker departure spread; 0 is a synchronized stress burst (default: 120)')
    parser.add_argument('--departures-per-second',type=float,default=20,help='global trip-start limit (default: 20)')
    parser.add_argument('--max-active-cars',type=int,default=2000,help='active road-vehicle limit for fleet admission (default: 2000)')
    parser.add_argument('--report-every',type=float,default=60,help='simulated seconds per report (default: 60)')
    parser.add_argument('--wall-seconds',type=float,help='total wall-time budget, checked between setup stages and ticks')
    parser.add_argument('--stack-every',type=float,default=30,help='write a diagnostic stack every N wall seconds (0 disables, default: 30)')
    parser.add_argument('--buildings',type=Path,default=ROOT/'benchmarks/arcata/arcata-buildings-citywide-2026-11-04.json.gz')
    parser.add_argument('--output',type=Path,help='new results directory; existing directories are never overwritten')
    args=parser.parse_args(argv)
    for name in ('hours','report_every','wall_seconds'):
        value=getattr(args,name)
        if value is not None and (not math.isfinite(value) or value<=0):
            parser.error(name.replace('_','-')+' must be positive and finite')
    if not math.isfinite(args.start_hour) or not 0<=args.start_hour<24:
        parser.error('start-hour must be in [0,24)')
    if args.cars<0:parser.error('cars must be nonnegative')
    if args.population<1:parser.error('population must be positive')
    if not math.isfinite(args.stack_every) or args.stack_every<0:
        parser.error('stack-every must be nonnegative and finite')
    try:CommutePolicy(departure_window=args.departure_window_minutes*60,
                      starts_per_second=args.departures_per_second,max_active_vehicles=args.max_active_cars)
    except ValueError as error:parser.error(str(error))
    return args


def build_scenario(city, *, cars=1000, seed=42, start_hour=6, population=None,commute_policy=None):
    homes=sorted((b for b in city.buildings if b.residents),key=lambda b:b.id)
    workplaces=sorted((b for b in city.buildings if b.category!=ZoneType.RESIDENTIAL),key=lambda b:b.id)
    if not homes or not workplaces:
        raise ValueError('The extract needs homes and nonresidential workplaces')
    capacity=sum(b.residents for b in homes)
    population=capacity if population is None else population
    if population<1 or population>capacity:
        raise ValueError(f'Population {population} exceeds valid housing capacity 1..{capacity}')
    rng=random.Random(seed)
    shuffled=homes.copy();rng.shuffle(shuffled)
    sizes={b.id:[] for b in homes};remaining=population
    for b in shuffled:
        occupied=min(b.residents,remaining);remaining-=occupied
        sizes[b.id]=[min(4,occupied-i) for i in range(0,occupied,4)]
    workers=(population+1)//2
    # Benchmark staffing assumption, not measured OSM employment. Existing
    # parking geometry is preserved; adding jobs does not enlarge the lots.
    for b in workplaces:b.jobs=math.ceil(workers/len(workplaces))
    for b in homes:b.inventory.amounts['food']=sum(sizes[b.id])*3
    runtime=CitySimulation(city,commute_policy=commute_policy)
    start=start_hour*3600
    runtime.time=runtime.transit.time=runtime.transit.traffic.elapsed_time=start
    runtime.transit.engine._call('nt_clock',start,0.,0.)
    runtime._last_economy=runtime._last_construction=runtime._last_construction_work=start
    runtime._last_household_economy=start
    drivers=[]
    for home in homes:
        for size in sizes[home.id]:
            hid=f'household-{runtime._next_household}';runtime._next_household+=1
            members=[]
            for k in range(size):
                pid=runtime._next_person;runtime._next_person+=1
                person=Resident(pid,home.id,pid%2==0,mode='walk',workplace=None)
                runtime.residents[pid]=person;members.append(pid);runtime._membership[pid]=hid
            runtime.households[hid]=Household(hid,home.id,members,memory=HousingMemory(updated_at=start))
            first_worker=next((pid for pid in members if runtime.residents[pid].worker),None)
            if first_worker is not None:drivers.append((first_worker,hid))
    slots=[b.id for b in workplaces for _ in range(b.jobs)]
    rng.shuffle(slots)
    for p in runtime.residents.values():
        if p.worker:p.workplace=slots.pop()
    rng.shuffle(drivers)
    for pid,hid in drivers:
        if len(runtime.fleet.vehicles)>=cars:break
        p=runtime.residents[pid]
        if runtime.sites[p.home]['road_position'] is None:continue
        vehicle=FleetVehicle('car-'+hid,'car',p.home,driver=pid)
        try:runtime.fleet.add(vehicle)
        except ValueError:continue # A shared home lot can already be full.
        p.mode='car';p.car_id=vehicle.id
    if len(runtime.fleet.vehicles)!=cars:
        raise ValueError(f'Only {len(runtime.fleet.vehicles)} household cars fit; requested {cars}')
    runtime.initial_fuel=sum(v.fuel_liters for v in runtime.fleet.vehicles.values())
    runtime._refresh_occupancy();runtime._sync_workforce_mode()
    runtime.assign_jobs();runtime._wake_economy()
    config=dict(buildings=len(city.buildings),homes=len(homes),workplaces=len(workplaces),
                population=len(runtime.residents),workers=workers,cars=len(runtime.fleet.vehicles),
                requested_population=population,housing_capacity=capacity,
                occupied_homes=sum(bool(chunks) for chunks in sizes.values()),
                pedestrians=sum(p.worker and p.mode=='walk' for p in runtime.residents.values()),
                jobs={b.id:b.jobs for b in workplaces},
                assignments=dict(Counter(p.workplace for p in runtime.residents.values() if p.worker)),
                categories=dict(Counter(b.category.value for b in city.buildings)),
                parking_lots=len(city.parking_lots),parking_spaces=sum(l.capacity for l in city.parking_lots),
                buildings_without_vehicle_access=sum(runtime.sites[b.id]['road_position'] is None for b in city.buildings),
                workplaces_without_vehicle_access=sum(runtime.sites[b.id]['road_position'] is None for b in workplaces),
                seed=seed,start_hour=start_hour,synthetic_locations=False,
                employment_setup='seeded random assignment to mapped nonresidential buildings',
                assumptions='four residents per home; half workers; assumed job capacity and initial food stocks',
                scope='commuting, shared parking, and household consumption; no added production, services, or buses',
                commute_policy=asdict(runtime.commute_policy),routing='native background destination trees; following-day learning',
                step_seconds=STEP,engine='cpp',python=sys.version.split()[0],platform=platform.platform())
    return runtime,config


def _snapshot(runtime):
    report=runtime.report()
    report['states']=dict(runtime.resident_state_counts())
    report['clock_hour']=round(runtime.time/3600,5)
    cars=[v for v in runtime.fleet.vehicles.values() if v.kind=='car' and v.driver in runtime.residents]
    report['cars_parked_at_work']=sum(v.phase=='parked' and v.site==runtime.residents[v.driver].workplace for v in cars)
    report['cars_parked_in_overflow']=sum(v.phase=='parked' and v.site.startswith('parking-endpoint:') for v in cars)
    report['cars_driving']=sum(v.phase=='driving' for v in cars)
    due=[p for p in runtime.residents.values() if p.car_id and p.state=='home' and p.workplace
         and runtime.work_start+runtime.commute_policy.offset(p.id,p.workplace)<=runtime.time%86400<runtime._shift_end(p)]
    report['cars_waiting_to_depart']=len(due)
    report['cars_blocked_by_full_destination']=sum(runtime.fleet._available_space(
        runtime.fleet.vehicles[p.car_id],p.workplace) is False for p in due)
    report['cars_blocked_by_missing_access']=sum(runtime.sites[p.home]['road_position'] is None or
        runtime.sites[p.workplace]['road_position'] is None for p in due)
    return report


def run_workday(runtime, *, hours, report_every, emit, deadline=None):
    start=runtime.time;end=start+hours*3600;next_report=start+report_every;run_start=time.perf_counter()
    tick_times=[];ticks=0;total_wall=0.;max_tick=0.;over_50ms=over_100ms=0
    last_report=None
    def report():
        nonlocal last_report
        ordered=sorted(tick_times)
        def quantile(q):return ordered[max(0,math.ceil(q*len(ordered))-1)]*1000 if ordered else 0.
        frame=_snapshot(runtime)
        frame.update(stage='progress',simulated_seconds=round(runtime.time-start,6),ticks=ticks,
                     tick_mean_ms=statistics.fmean(ordered)*1000 if ordered else 0.,
                     tick_p50_ms=quantile(.5),tick_p95_ms=quantile(.95),tick_p99_ms=quantile(.99),
                     tick_max_ms=max(ordered,default=0.)*1000,run_max_tick_ms=max_tick*1000,
                     ticks_over_50ms=over_50ms,ticks_over_100ms=over_100ms,
                     updates_per_wall_second=ticks/max(1e-9,time.perf_counter()-run_start))
        emit(frame);tick_times.clear();last_report=runtime.time
    report();reason='duration'
    try:
        while runtime.time<end-1e-7:
            if deadline is not None and time.perf_counter()>=deadline:
                reason='wall_limit';break
            before=time.perf_counter();runtime.update(min(STEP,end-runtime.time));elapsed=time.perf_counter()-before
            ticks+=1;total_wall+=elapsed;max_tick=max(max_tick,elapsed);tick_times.append(elapsed)
            over_50ms+=elapsed>.05;over_100ms+=elapsed>.1
            if runtime.time>=next_report-1e-7:
                report();next_report=runtime.time+report_every
    except KeyboardInterrupt:
        reason='interrupted'
    if abs(runtime.time-last_report)>1e-7:report()
    return dict(stop_reason=reason,simulated_seconds=round(runtime.time-start,6),
                requested_simulated_seconds=hours*3600,ticks=ticks,step_wall_seconds=total_wall,
                run_wall_seconds=time.perf_counter()-run_start,
                mean_tick_ms=total_wall/max(1,ticks)*1000,max_tick_ms=max_tick*1000,
                ticks_over_50ms=over_50ms,ticks_over_100ms=over_100ms,final=_snapshot(runtime))


def main(argv=None):
    args=parse_args(argv)
    start=time.perf_counter()
    deadline=start+args.wall_seconds if args.wall_seconds else None
    out=args.output or ROOT/'benchmarks/arcata/results'/('city-workday-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True,exist_ok=False)
    stack_watch=None
    if args.stack_every:
        stack_watch=start_stack_watch(out/'stacks.log',args.stack_every,start)
    def emit(record):
        value=dict(wall=round(time.perf_counter()-start,3),**record)
        line=json.dumps(value,allow_nan=False)
        print(line,flush=True)
        with (out/'metrics.jsonl').open('a') as stream:stream.write(line+'\n')
    def setup_progress(record):
        emit(record)
        if deadline is not None and time.perf_counter()>=deadline:raise SetupBudgetExceeded()
    try:
        emit(dict(stage='loading_map',output=str(out)))
        city,_,source=build_city([ROOT/'benchmarks/arcata/arcata-roads-2026-06-01.json'],
                                 ROOT/'benchmarks/arcata/arcata-city-boundary.osm',building_paths=[args.buildings],
                                 building_progress=setup_progress)
        emit(dict(stage='map_loaded',roads=len(city.roads),buildings=len(city.buildings)))
        if deadline is not None and time.perf_counter()>=deadline:
            summary=dict(stop_reason='wall_limit_during_setup',wall_seconds=time.perf_counter()-start)
        else:
            policy=CommutePolicy(departure_window=args.departure_window_minutes*60,
                starts_per_second=args.departures_per_second,max_active_vehicles=args.max_active_cars)
            runtime,config=build_scenario(city,cars=args.cars,seed=args.seed,start_hour=args.start_hour,
                                           population=args.population,commute_policy=policy)
            config.update(source=source,duration_hours=args.hours,wall_limit_seconds=args.wall_seconds)
            (out/'configuration.json').write_text(json.dumps(config,indent=2))
            emit(dict(stage='ready',**{k:config[k] for k in ('population','workers','cars','parking_lots','parking_spaces')}))
            summary=run_workday(runtime,hours=args.hours,report_every=args.report_every,deadline=deadline,emit=emit)
            summary.update(configuration=config,wall_seconds=time.perf_counter()-start)
        (out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
        emit(dict(stage='complete',stop_reason=summary['stop_reason'],
                  simulated_seconds=summary.get('simulated_seconds',0),summary=str(out/'summary.json')))
        return 130 if summary['stop_reason']=='interrupted' else 0
    except SetupBudgetExceeded:
        summary=dict(stop_reason='wall_limit_during_setup',wall_seconds=time.perf_counter()-start)
        (out/'summary.json').write_text(json.dumps(summary,indent=2))
        emit(dict(stage='complete',**summary,summary=str(out/'summary.json')))
        return 0
    except Exception:
        (out/'error.txt').write_text(traceback.format_exc())
        raise
    finally:
        if stack_watch:
            stop,worker=stack_watch
            stop.set();worker.join(timeout=1)
        if 'runtime' in locals():runtime.close()


if __name__=='__main__':
    raise SystemExit(main())
