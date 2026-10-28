"""Record a synthetic bus-and-walking scenario with the native traffic engine."""
import argparse
import json
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from city import CityMap, Terrain
from mobility import lane_position_at_distance
from transit import Bus, BusLine, BusStop, TransitSimulation


def capture():
    city = CityMap(terrain=Terrain(trees=[]))
    road = city.add_road([(0, 0), (6000, 0)])
    lane = next(l for l in road.lanes if l.direction == 'forward')
    sim = TransitSimulation(city)
    sim.add_stop(BusStop('A', lane_position_at_distance(lane, 100), (120, 15)))
    sim.add_stop(BusStop('B', lane_position_at_distance(lane, 5700), (5720, 15)))
    sim.add_line(BusLine('L', ('A', 'B'), headway_seconds=300))
    sim.add_bus(Bus('bus-1', 'L', capacity=2, service_at=30))
    for i in range(4):
        sim.request_trip(i, (100-i*10, 15), (5740+i*10, 15))
    frames = []
    for _ in range(1301):
        frames.append(dict(time=round(sim.time, 3),
                           buses=[dict(id=b.id, position=b.position, phase=b.phase,
                                       passengers=len(b.passengers), capacity=b.capacity,
                                       fuel=round(b.fuel_liters, 4)) for b in sim.buses.values()],
                           people=[dict(id=p.id, position=(p.x, p.y)) for p in sim.engine.pedestrian_states()],
                           phases=dict(Counter(p.phase for p in sim.people.values())),
                           waiting=sum(len(q) for q in sim.queues.values())))
        if sim.time < 1300:
            sim.update(1)
    return dict(scenario='Synthetic 6,000-foot corridor; not a real Humboldt bus service',
                roads=[r.centerline for r in city.roads],
                walkways=[l.points for r in city.roads for l in r.pedestrian_lanes],
                stops=[dict(id=s.id, position=s.walk_point) for s in sim.stops.values()],
                frames=frames, events=sim.events,
                arrivals={p.id:p.arrived_at for p in sim.people.values()},
                limitations=['Recorded C++ simulation, not live browser computation',
                             'Assumed off-road stop bays; no bus pull-in maneuver',
                             'One line per journey; no passenger transfers',
                             'No transit save/load, driver staffing, idling fuel or wheelchair rules'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    data = capture()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, separators=(',', ':')))
    print(json.dumps({'frames':len(data['frames']), 'arrivals':data['arrivals']}))
