"""Measure idle work with real native loading bodies and the shared transit clock.

Run from the repository root:
    python3 tools/benchmark_truck_stops.py --output build/parking-fix/truck-stop-idle.json

Only TransitSimulation.update is profiled; city construction and stop placement
are excluded identically for every count. No controller or transport is mocked.
"""
import argparse
import cProfile
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from city import CityMap, Terrain
from mobility import lane_position_at_distance
from transit import TransitSimulation
from truck_stops import LaneObstacle


def benchmark(counts=(0, 128), seconds=86400):
    results = []
    road_length = max(12000, 120 + 80 * max(counts, default=0))
    for count in counts:
        if count < 0:
            raise ValueError('Stationary truck counts must be nonnegative')
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 100), (road_length, 100)])
        transit = TransitSimulation(city)
        try:
            for index in range(count):
                transit.traffic.set_lane_obstacle(str(index),
                    lane_position_at_distance(road.lanes[0], 40 + index * 80),
                    length=28, width=8)
            engine = transit.engine
            before = engine.profile_snapshot()
            profile = cProfile.Profile()
            with profile:
                transit.update(seconds)
            after = engine.profile_snapshot()
            rows = profile.getstats()
            results.append(dict(stationary_trucks=count, simulated_seconds=transit.time,
                native_ticks=after['ticks']-before['ticks'],
                driver_visits=after['vehicle_visits']-before['vehicle_visits'],
                obstacle_pose_reads=sum(row.callcount for row in rows
                    if row.code == LaneObstacle.occupancy_position.__code__),
                python_calls=sum(row.callcount for row in rows)))
        finally:
            transit.traffic._discard_native()
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counts', nargs='+', type=int, default=[0, 128])
    parser.add_argument('--seconds', type=float, default=86400)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(benchmark(args.counts, args.seconds), indent=2) + '\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
    print(result, end='')
