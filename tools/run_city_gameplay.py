"""Exercise gameplay using the actual building tool and construction pipeline.

Run: python tools/run_city_gameplay.py --output docs/city-gameplay-run.json
The settlement and rates are synthetic; no map download or UI display is needed.
"""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from city import CityMap, Terrain
from city_simulation import CitySimulation
from construction import ConstructionSimulation, UnlimitedConstructionProvider
from households import HousingMemory, YEAR
from models import BuildablePhase
from persistence import world_to_dict,world_from_dict
from resources import load_construction_catalog
from traffic_testbed import RoadVehicleSimulation
from ui_tools.tools.road_tool import BuildingTool


def run():
    started=perf_counter()
    city=CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0,1000),(4500,1000)],name='Authored town street')
    host=SimpleNamespace(city_map=city,redraw_world=lambda:None)
    tool=BuildingTool(host)
    def place(template,x,y=1045):
        tool.selected_spec=next(s for s in tool.specs if s.id==template)
        return tool.place_building((x,y))
    homes=[place('apartment_building',x) for x in (250,1200,3700)]
    sites={role:place(role,x) for role,x in [('market',2800),('cafe',3000),('bakery',3200),('clinic',3400),('farm',4050)]}
    stops=[place('bus_stop',x,1030) for x in (400,1900,3600)]
    traffic=RoadVehicleSimulation(update_mode='cpp',spawn_interval=10000)
    resources,trucks=load_construction_catalog()
    construction=ConstructionSimulation(resources,trucks,UnlimitedConstructionProvider(),road_vehicles=traffic)
    runtime=CitySimulation(city,traffic,construction)
    while not all(b.phase==BuildablePhase.OPERATIONAL for b in city.buildings) and runtime.time<7200:
        runtime.update(60)
    if not all(b.phase==BuildablePhase.OPERATIONAL for b in city.buildings):
        raise AssertionError('Construction did not finish')
    construction_completed=runtime.time
    runtime.create_line([stops[0].id,stops[2].id])
    runtime.create_line([stops[0].id,stops[1].id,stops[2].id])
    households=[runtime.invite_household(homes[i%2].id,4,car=i%3==0) for i in range(8)]
    workers=[p for p in runtime.residents.values() if p.worker]
    for role,site in sites.items():
        if any(p.workplace==site.id for p in workers):continue
        counts={sid:sum(p.workplace==sid for p in workers) for sid in (b.id for b in sites.values())}
        p=next(p for p in workers if counts.get(p.workplace,0)>1)
        runtime.assign_workplace(p.id,site.id)
    for pid in (2,6,10,14):
        runtime._once('demo-care:'+str(pid),10*3600,'service_visit',(pid,sites['clinic'].id,'care'))
    for home in homes:runtime.import_resources(home.id,'food',50)
    for role,resource,amount in [('farm','seed',800),('bakery','grain',200),('market','food',300),('cafe','food',80),('clinic','medicine',40)]:
        runtime.import_resources(sites[role].id,resource,amount)
    for _ in range(2):runtime.commission_truck(sites['market'].id)
    runtime.update(8*3600-runtime.time)
    before=runtime.report()
    saved=world_to_dict(city,unit_system='imperial',camera_x=0,camera_y=0,camera_zoom=1)
    restored=CitySimulation(world_from_dict(json.loads(json.dumps(saved,allow_nan=False))).city_map)
    snapshot_matches=restored.report()==before
    if not snapshot_matches:raise AssertionError('Snapshot changed accounting')
    restored.update(60)
    # Explicit relocation exercises the same conserved movement used by the
    # desirability planner, after everyone has returned from work.
    runtime.update(21*3600-runtime.time)
    household=households[0]
    runtime.relocate(household.id,homes[2].id)
    runtime.update(3*3600)
    result=runtime.report()
    assert household.home==homes[2].id
    assert result['population']==32
    assert result['meals_served']>0
    assert result['treated']==4
    assert abs(result['resource_balance_error'])<1e-6,result
    quiet=CitySimulation(CityMap(terrain=Terrain(trees=[])))
    idle_started=perf_counter();quiet.update(3*YEAR);idle_ms=(perf_counter()-idle_started)*1000
    memory=HousingMemory(buffer=60,target=10)
    return dict(scenario='Authored buildings, persistent households and services',
        construction_completed_seconds=construction_completed,
        completed_buildings=len(city.buildings),buses=len(runtime.transit.buses),bus_capacity=60,
        snapshot_accounting_matches=snapshot_matches,report=result,
        scheduling_counters=dict(runtime.counters),
        empty_city_three_years_wall_ms=idle_ms,empty_city_decision_events=dict(quiet.counters),
        moving_buffer_after_two_years=memory.value_at(2*YEAR),
        wall_seconds=perf_counter()-started,
        assumptions=['Synthetic layout, stocks, staffing choices and service rates.',
            'Building entrances and off-road stop bays are inferred.',
            'Drivers and loaders are assumed available; care does not model health.',
            'Construction traffic requeues after load using its existing persistence behavior.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=run();encoded=json.dumps(result,indent=2,allow_nan=False)+'\n'
    if args.output:args.output.write_text(encoded)
    print(encoded)
