"""Reproduce roundabout failures without changing the driving implementation.

Run from the repository root. Experimental switches replace ONE behavior for
this process only. They are diagnostic counterfactuals, not proposed fixes.
"""
from __future__ import annotations
import argparse
import json
from math import dist
from pathlib import Path
import random
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import merge_behavior as merges
import traffic_testbed as traffic
from persistence import world_from_dict
from test_junction_traffic import cars_overlap


def isolated_checks():
    """Remove the map and traffic queue to test individual dependencies."""
    observation = merges.MergeObservation(203.58, 14, (
        merges.MergeVehicle('ahead', 40, 17.6, 14),))
    empty = merges.MergeObservation(203.58, 14, ())
    rolling = merges.RollingMerge()
    target = ('lane', 'shared')
    connection = SimpleNamespace(merge_target=target)
    joining = SimpleNamespace(speed=17.6, distance=0, length=14,
        route_segments=((30, 130, target, 0),))
    approaching = SimpleNamespace(id='approaching', speed=17.6, distance=0,
        length=14, controlled_movements=(), route_segments=((250, 350, target, 0),))
    unrelated = SimpleNamespace(id='unrelated', speed=100, distance=0, length=14,
        controlled_movements=(), route_segments=(), occupancy_position=lambda: None)
    observe = lambda cars: [v.id for v in merges.observe_merge(
        joining, (0, 30, connection), cars).vehicles]
    return dict(
        rolling_empty_desired=rolling.decide(empty, 0, 17.6).desired_speed,
        rolling_with_distant_leader_desired=rolling.decide(observation, 0, 17.6).desired_speed,
        cautious_with_distant_leader_desired=merges.CautiousMerge().decide(observation, 0, 17.6).desired_speed,
        observed_without_unrelated_fast_car=observe([joining, approaching]),
        observed_with_unrelated_fast_car=observe([joining, approaching, unrelated]))


def waiting_elsewhere(other, movement):
    # A future arrival from another entrance is not yet circulating traffic.
    return any(m[2].intersection_id == movement[2].intersection_id
        and m[2].merge_target is not None
        and other.distance + other.length/2 < m[0]
        for m in other.controlled_movements)


def run(args):
    random.seed(args.seed)
    city = world_from_dict(json.loads(args.map.read_text())).city_map
    sim = traffic.TestTrafficSimulation(rng=random.Random(args.seed))
    for junction in city.cul_de_sacs:
        sim.toggle_junction(junction)
    original_observe = traffic.observe_merge
    original_decide = merges.RollingMerge.decide
    if args.experiment == 'exclude_waiting':
        def observe(car, movement, cars):
            return original_observe(car, movement, [other for other in cars
                if other is car or not waiting_elsewhere(other, movement)])
        traffic.observe_merge = observe
    if args.experiment == 'free_acceleration':
        def decide(self, observation, speed, cruise):
            if observation.distance_to_join >= 128:
                return merges.MergeChoice(cruise,
                    merges._gap_at_arrival(observation, speed, cruise, .8))
            return original_decide(self, observation, speed, cruise)
        merges.RollingMerge.decide = decide
    completed = overlaps = 0
    first_collision = None
    longest = None
    stopped_for = {}
    false_veto = None
    try:
        steps = round(args.seconds / args.dt)
        for tick in range(steps):
            # Reverse just the processing order, not source/destination draws.
            # Once behavior diverges, spawn success can also diverge; this is
            # a sensitivity check, not a matched-state proof of causation.
            if args.experiment == 'reverse_order':
                sim.cars.sort(key=lambda c: int(c.id.rsplit('-', 1)[1]), reverse=True)
            completed += len(sim.update(city, args.dt))
            for index, a in enumerate(sim.cars):
                for b in sim.cars[index+1:]:
                    if dist(a.position, b.position) < 16 and cars_overlap(a, b):
                        overlaps += 1
                        if first_collision is None:
                            first_collision = dict(time=round(sim.elapsed_time, 3),
                                cars=[a.id, b.id], positions=[a.position, b.position],
                                speeds=[a.speed, b.speed],
                                links=[a.occupancy_position(), b.occupancy_position()])
            for car in sim.cars:
                m = traffic._next_controlled_movement(car, sim.stop_coordinator)
                # This only rules out an indexed leader in the 128ft query;
                # it does not establish an empty road all the way to the join.
                if (m and m[2].merge_target and car.speed < .1
                        and sim.occupancy.lead_gap(car, 128) is None):
                    stopped_for[car.id] = stopped_for.get(car.id, 0) + args.dt
                    if longest is None or stopped_for[car.id] > longest['duration']:
                        longest = dict(car=car.id, time=round(sim.elapsed_time, 3),
                            duration=round(stopped_for[car.id], 3),
                            nose_before_line=round(m[0]-car.distance-car.length/2, 3),
                            center_before_join=round(m[1]-car.distance, 3),
                            reason=car.brain.wait_reason)
                    if false_veto is None:
                        obs = original_observe(car, m, sim.cars)
                        waiting = {o.id for o in sim.cars if waiting_elsewhere(o, m)}
                        filtered = merges.MergeObservation(obs.distance_to_join, obs.length,
                            tuple(v for v in obs.vehicles if v.id not in waiting))
                        strategy = merges.MERGE_STRATEGIES[car.brain.merge_style]
                        cruise = traffic._route_cruise_speed(car, sim.speed_mph)
                        if (not strategy.decide(obs, car.speed, cruise).can_enter
                                and strategy.decide(filtered, car.speed, cruise).can_enter):
                            false_veto = dict(time=round(sim.elapsed_time, 3), car=car.id,
                                removed=[v.id for v in obs.vehicles if v.id in waiting])
                else:
                    stopped_for[car.id] = 0
        return dict(experiment=args.experiment, seed=args.seed, dt=args.dt,
            seconds=steps*args.dt, completed=completed, remaining=len(sim.cars),
            overlap_pair_ticks=overlaps, first_collision=first_collision,
            longest_stop_without_indexed_leader=longest, false_veto_example=false_veto)
    finally:
        traffic.observe_merge = original_observe
        merges.RollingMerge.decide = original_decide


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', type=Path, default=ROOT/'tests/fixtures/roundabout_test.json')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--seconds', type=float, default=80)
    parser.add_argument('--dt', type=float, default=.05)
    parser.add_argument('--experiment', choices=('baseline', 'reverse_order',
        'free_acceleration', 'exclude_waiting'), default='baseline')
    parser.add_argument('--isolated', action='store_true')
    args = parser.parse_args()
    if args.dt <= 0 or args.dt > .05 or args.seconds <= 0:
        parser.error('Use 0 < dt <= .05 and positive seconds.')
    print(json.dumps(isolated_checks() if args.isolated else run(args), indent=2))
