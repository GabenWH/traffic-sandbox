"""Closely spaced junctions must not hide the next yield behind the car's rear."""
import json
import random
import unittest
from pathlib import Path
from math import dist
from persistence import world_from_dict
from traffic_testbed import TestTrafficSimulation
from test_junction_traffic import cars_overlap

class ChainedJunctionTests(unittest.TestCase):
    def test_uploaded_slip_lane_map_has_no_overlapping_cars(self):
        city = world_from_dict(json.loads((Path(__file__).parent / 'fixtures/slip_lanes.json').read_text())).city_map
        traffic = TestTrafficSimulation(rng=random.Random(42))
        for junction in city.cul_de_sacs:
            traffic.toggle_junction(junction)
        completed = 0
        for tick in range(1600):
            completed += len(traffic.update(city, .05))
            for index, a in enumerate(traffic.cars):
                for b in traffic.cars[index+1:]:
                    if dist(a.position, b.position) < 16:
                        self.assertFalse(cars_overlap(a, b),
                            f'Collision at {(tick+1)*.05:.2f}s: {a.id}, {b.id}, {a.position}, {b.position}')
        self.assertGreater(completed, 0, 'Stopping every car is not a collision fix')

    def test_releasing_previous_junction_keeps_next_claim(self):
        from intersection_controls import AllWayStopCoordinator
        city = world_from_dict(json.loads((Path(__file__).parent / 'fixtures/slip_lanes.json').read_text())).city_map
        traffic = TestTrafficSimulation()
        ends = city.cul_de_sacs
        car = traffic.spawn_car(city, ends[2], ends[3])
        previous, following = car.controlled_movements[:2]
        coordinator = AllWayStopCoordinator()
        coordinator.observe_approach(car.id, previous[2], 0)
        self.assertTrue(coordinator.claim(car.id, previous[2]))
        self.assertTrue(coordinator.claim_merge(car.id, following[2]))
        self.assertTrue(coordinator.has_claim(car.id, previous[2]))
        coordinator.release(car.id, previous[2])
        self.assertTrue(coordinator.has_claim(car.id, following[2]))
        self.assertFalse(coordinator.has_claim(car.id, previous[2]))
        coordinator.forget_car(car.id)
        self.assertFalse(coordinator.has_claim(car.id, following[2]))

    def test_waits_before_short_link_when_roundabout_gap_is_blocked(self):
        city = world_from_dict(json.loads((Path(__file__).parent / 'fixtures/slip_lanes.json').read_text())).city_map
        traffic = TestTrafficSimulation()
        ends = {j.position: j for j in city.cul_de_sacs}
        joining = traffic.spawn_car(city, ends[(2630.,1846.)], ends[(3356.,1770.)])
        circulating = traffic.spawn_car(city, ends[(2968.,1586.)], ends[(3356.,1770.)])
        first, entry = joining.controlled_movements[:2]
        target = next(s for s in circulating.route_segments if s[2] == entry[2].merge_target)
        joining.distance, joining.speed = first[0] - joining.length/2 - 1, 17.6
        circulating.distance, circulating.speed = target[0] - 65, 17.6
        joining.advance(0)
        circulating.advance(0)
        traffic.update(city, 0)
        self.assertFalse(traffic.stop_coordinator.has_claim(joining.id, first[2]),
                         'Wait before the first junction when the next yield has no gap and no waiting space')

    def test_clearing_previous_junction_does_not_override_next_yield(self):
        from car_brain import CarBrain, CarObservation
        decision = CarBrain().decide(CarObservation(cruise_speed=17.6, speed=5,
            inside_intersection=True, must_yield=True, has_priority=False,
            distance_to_stop=0), .05)
        self.assertEqual(decision.desired_speed, 0)
