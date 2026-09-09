"""The same traffic facts should produce different driver choices."""
import unittest
from car_brain import CarBrain, CarObservation
import merge_behavior as merges


class MergeBrainTests(unittest.TestCase):
    def test_merge_behavior_is_selected_per_brain(self):
        self.assertIn('merge_style', CarBrain.__dataclass_fields__)

    def test_rolling_driver_adjusts_speed_into_gap_while_cautious_driver_waits(self):
        self.assertTrue(hasattr(merges, 'MergeObservation'))
        traffic = merges.MergeObservation(40, 14, (
            merges.MergeVehicle('leader', -10, 17.6, 14),
            merges.MergeVehicle('follower', -130, 17.6, 14),
        ))
        observation = CarObservation(cruise_speed=17.6, speed=17.6,
            distance_to_stop=2, must_yield=True, has_priority=True, merge=traffic)
        rolling = CarBrain(merge_style='rolling')
        cautious = CarBrain(merge_style='cautious')
        a, b = rolling.decide(observation, .05), cautious.decide(observation, .05)
        self.assertGreater(a.desired_speed, 0)
        self.assertLess(a.desired_speed, observation.cruise_speed)
        self.assertTrue(a.request_claim)
        self.assertFalse(b.request_claim)
        self.assertEqual(rolling.phantom_target, 'leader')

    def test_empty_merge_does_not_require_stopping_for_either_style(self):
        self.assertTrue(hasattr(merges, 'MergeObservation'))
        for style in ('rolling', 'cautious'):
            brain = CarBrain(merge_style=style)
            result = brain.decide(CarObservation(cruise_speed=17.6, speed=17.6,
                distance_to_stop=0, must_yield=True, has_priority=True,
                merge=merges.MergeObservation(30, 14, ())), .05)
            self.assertTrue(result.request_claim)
            self.assertEqual(result.desired_speed, 17.6)

    def test_both_styles_refuse_to_join_a_stationary_occupied_gap(self):
        self.assertTrue(hasattr(merges, 'MergeObservation'))
        for style in ('rolling', 'cautious'):
            result = CarBrain(merge_style=style).decide(CarObservation(
                cruise_speed=17.6, speed=0, distance_to_stop=0,
                must_yield=True, has_priority=True,
                merge=merges.MergeObservation(30, 14, (
                    merges.MergeVehicle('stopped', 0, 0, 14),))), .05)
            self.assertFalse(result.request_claim)
            self.assertEqual(result.desired_speed, 0)

    def test_rolling_car_follows_circulating_leader_without_stopping(self):
        from test_junction_traffic import cross_city, cars_overlap
        from models import IntersectionKind
        from traffic_testbed import TestTrafficSimulation
        city = cross_city()
        city.standard_intersections[0].kind = IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network()
        ends = {j.position: j for j in city.cul_de_sacs}
        traffic = TestTrafficSimulation()
        leader = traffic.spawn_car(city, ends[(600, 300)], ends[(300, 600)])
        joining = traffic.spawn_car(city, ends[(0, 300)], ends[(600, 300)])
        entry = joining.controlled_movements[0]
        shared = next(s for s in leader.route_segments if s[2] == entry[2].merge_target)
        leader.distance = shared[0] - 10
        joining.distance = entry[1] - 40
        leader.speed = joining.speed = 17.6
        leader.advance(0)
        joining.advance(0)
        saw_phantom = False
        minimum_speed = 17.6
        for _ in range(160):
            traffic.update(city, .05)
            if joining.distance <= entry[1] + joining.length:
                minimum_speed = min(minimum_speed, joining.speed)
                saw_phantom |= joining.brain.phantom_target == leader.id
                self.assertFalse(cars_overlap(joining, leader))
        self.assertTrue(saw_phantom)
        self.assertGreater(joining.distance, entry[1] + joining.length)
        self.assertGreater(minimum_speed, 2.0)

    def test_inspector_changes_only_selected_driver_strategy(self):
        from types import SimpleNamespace
        from test_junction_traffic import cross_city
        from traffic_testbed import TestTrafficSimulation
        from ui_tools.tools.inspect_tool import inspection_rows
        city = cross_city()
        traffic = TestTrafficSimulation()
        a = traffic.spawn_car(city, city.cul_de_sacs[0], city.cul_de_sacs[1])
        host = SimpleNamespace(unit_system='imperial')
        _, rows = inspection_rows(host, a)
        style = next(row for row in rows if row.label == 'Merge style')
        style.apply('cautious')
        self.assertEqual(a.brain.merge_style, 'cautious')
        with self.assertRaises(ValueError):
            style.apply('reckless')
        self.assertEqual(a.brain.merge_style, 'cautious')

    def test_queued_driver_does_not_reserve_a_gap_at_cruise_speed(self):
        for style in ('rolling', 'cautious'):
            result = CarBrain(merge_style=style).decide(CarObservation(
                cruise_speed=17.6, speed=0, distance_to_stop=0,
                must_yield=True, has_priority=True, lead_car_distance=5,
                following_gap=22, merge=merges.MergeObservation(30, 14, ())), .05)
            self.assertEqual(result.desired_speed, 0)
            self.assertFalse(result.request_claim)

    def test_entrance_claim_is_rechecked_until_the_nose_crosses_the_line(self):
        from test_junction_traffic import cross_city
        from models import IntersectionKind
        from traffic_testbed import TestTrafficSimulation
        city = cross_city()
        city.standard_intersections[0].kind = IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network()
        ends = {j.position: j for j in city.cul_de_sacs}
        traffic = TestTrafficSimulation()
        leader = traffic.spawn_car(city, ends[(600, 300)], ends[(300, 600)])
        joining = traffic.spawn_car(city, ends[(0, 300)], ends[(600, 300)])
        entry = joining.controlled_movements[0]
        shared = next(s for s in leader.route_segments if s[2] == entry[2].merge_target)
        leader.distance, leader.speed = shared[0], 0
        joining.distance, joining.speed = entry[0] - joining.length/2 - 5, 0
        leader.advance(0)
        joining.advance(0)
        traffic.stop_coordinator.claim_merge(joining.id, entry[2])
        joining._claimed_movement = entry[2]
        traffic.update(city, 0)
        self.assertIsNone(joining.claimed_movement)
