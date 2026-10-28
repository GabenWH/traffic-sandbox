"""Run a 24-hour synthetic town and export native transport/economic observations."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from town_simulation import build_town


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--population',type=int,default=1000)
    parser.add_argument('--out',required=True)
    parser.add_argument('--checkpoint',required=True)
    args=parser.parse_args()
    town=build_town(args.population)
    frames=[]
    start=time.perf_counter()
    for minute in range(1441):
        if minute:
            town.update(60)
        f=town.report()
        f['sites']=[dict(id=sid,position=s['walk_point'],food=s['building'].inventory.amounts.get('food',0),
                         residents=s['building'].residents) for sid,s in town.sites.items()]
        f['cars']=[dict(id=c.id,position=c.position,kind=c.source_type) for c in town.transit.traffic.cars]
        f['people']=[dict(id=p.id,position=(p.x,p.y)) for p in town.transit.engine.pedestrian_states()]
        f['parked_cars']=sum(v.phase=='parked' and v.kind=='car' for v in town.fleet.vehicles.values())
        f['bus_waiting']=sum(len(q) for q in town.transit.queues.values())
        f['bus_onboard']=sum(len(b.passengers) for b in town.transit.buses.values())
        frames.append(f)
        if minute%120==0:
            print(json.dumps({'hour':minute//60,'at_home':f['at_home'],'at_work':f['at_work'],
                              'commuting':f['commuting'],'deliveries':f['deliveries']}),flush=True)
    data=dict(scenario='Synthetic 6,000-foot town corridor; uncalibrated fictional population',
              duration=86400, population=args.population, frames=frames,
              roads=[r.centerline for r in town.city.roads],
              events=town.events,transit_events=town.transit.events,
              summary=town.report(),wall_seconds=round(time.perf_counter()-start,3),
              fleet=[dict(id=v.id,kind=v.kind,site=v.site,phase=v.phase,trips=v.trips,
                          fuel=v.fuel_liters,distance=v.distance_feet) for v in town.fleet.vehicles.values()])
    target=Path(args.out); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,separators=(',',':')))
    try:
        saved=town.checkpoint()
        Path(args.checkpoint).write_text(json.dumps(saved,separators=(',',':'),allow_nan=False))
        from town_simulation import TownSimulation
        restored=TownSimulation.from_checkpoint(json.loads(Path(args.checkpoint).read_text()))
        assert restored.report()==town.report(), 'Restored checkpoint report differs'
        print('Checkpoint restore verified',flush=True)
    except Exception as error:
        print('Checkpoint failed: '+str(error),flush=True)
        raise
    print(json.dumps(dict(summary=data['summary'],wall_seconds=data['wall_seconds'])),flush=True)


if __name__=='__main__':
    main()
