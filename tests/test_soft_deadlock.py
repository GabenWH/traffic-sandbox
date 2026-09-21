"""Soft-deadlock resolution keeps hesitant traffic from waiting forever."""

import json
import unittest
from pathlib import Path

from car_brain import BehaviorState, CarBrain, CarObservation
from merge_behavior import MergeObservation, MergeVehicle
from persistence import world_from_dict
from soft_deadlock import DeadlockCandidate, SoftDeadlockResolver, merge_space_clear
from traffic_testbed import TestTrafficSimulation


class SoftDeadlockResolverTests(unittest.TestCase):
    def test_moving_priority_traffic_is_not_overridden(self):
        moving = MergeVehicle("circulating", -100.0, 4.0, 14.0)
        stopped_far_away = MergeVehicle("circulating", -100.0, 0.0, 14.0)
        stopped_but_able_to_restart = MergeVehicle(
            "queued-circulating", -100.0, 0.0, 14.0, cruise_speed=12.0,
        )

        self.assertFalse(merge_space_clear(14.0, (moving,), ()))
        self.assertTrue(merge_space_clear(14.0, (stopped_far_away,), ()))
        self.assertFalse(merge_space_clear(14.0, (stopped_but_able_to_restart,), ()))

    def test_waits_for_sustained_global_stall_before_selecting_winner(self):
        resolver = SoftDeadlockResolver(stall_threshold=5.0)
        candidates = (
            DeadlockCandidate("newer", path_clear=True),
            DeadlockCandidate("older", path_clear=True),
        )

        resolver.observe_frame(4.95, made_progress=False, candidate_ids=("older",))
        resolver.observe_frame(0.04, made_progress=False,
                               candidate_ids=("older", "newer"))
        self.assertIsNone(resolver.choose_winner(candidates))

        resolver.observe_frame(0.01, made_progress=False,
                               candidate_ids=("older", "newer"))
        self.assertEqual(resolver.choose_winner(candidates), "older")

    def test_never_selects_a_physically_blocked_candidate(self):
        resolver = SoftDeadlockResolver(stall_threshold=1.0)
        candidates = (
            DeadlockCandidate("boxed-in", path_clear=False),
            DeadlockCandidate("also-boxed-in", path_clear=False),
        )
        resolver.observe_frame(1.0, made_progress=False,
                               candidate_ids=tuple(item.car_id for item in candidates))

        self.assertIsNone(resolver.choose_winner(candidates))
        self.assertTrue(resolver.hard_gridlock)

    def test_real_progress_clears_the_override_and_stall_timer(self):
        resolver = SoftDeadlockResolver(stall_threshold=1.0)
        candidates = (DeadlockCandidate("car-a", path_clear=True),)
        resolver.observe_frame(1.0, made_progress=False, candidate_ids=("car-a",))
        self.assertEqual(resolver.choose_winner(candidates), "car-a")

        resolver.observe_frame(
            0.05,
            made_progress=True,
            candidate_ids=("car-a",),
            winner_resolved=True,
        )

        self.assertIsNone(resolver.choose_winner(candidates))
        self.assertEqual(resolver.stall_seconds, 0.0)

    def test_committed_winner_is_not_replaced_when_its_path_temporarily_blocks(self):
        resolver = SoftDeadlockResolver(stall_threshold=1.0)
        resolver.observe_frame(1.0, made_progress=False,
                               candidate_ids=("first", "second"))
        self.assertEqual(resolver.choose_winner((
            DeadlockCandidate("first", path_clear=True),
            DeadlockCandidate("second", path_clear=True),
        )), "first")

        selected = resolver.choose_winner((
            DeadlockCandidate("first", path_clear=False),
            DeadlockCandidate("second", path_clear=True),
        ))

        self.assertIsNone(selected)
        self.assertEqual(resolver.winner_id, "first")

    def test_unrelated_progress_does_not_clear_committed_winner(self):
        resolver = SoftDeadlockResolver(stall_threshold=1.0)
        candidates = (DeadlockCandidate("winner", path_clear=True),)
        resolver.observe_frame(1.0, made_progress=False, candidate_ids=("winner",))
        self.assertEqual(resolver.choose_winner(candidates), "winner")

        resolver.observe_frame(0.05, made_progress=True, candidate_ids=("winner",))

        self.assertEqual(resolver.winner_id, "winner")
        self.assertEqual(resolver.choose_winner(candidates), "winner")

    def test_winner_does_not_carry_override_into_its_next_movement(self):
        resolver = SoftDeadlockResolver(stall_threshold=1.0)
        resolver.observe_frame(1.0, made_progress=False,
                               candidate_ids=("first", "second"))
        self.assertEqual(resolver.choose_winner((
            DeadlockCandidate("first", path_clear=True, movement_id="junction-a"),
            DeadlockCandidate("second", path_clear=True, movement_id="junction-a"),
        )), "first")

        selected = resolver.choose_winner((
            DeadlockCandidate("first", path_clear=True, movement_id="junction-b"),
            DeadlockCandidate("second", path_clear=True, movement_id="junction-a"),
        ))

        self.assertIsNone(selected)
        self.assertIsNone(resolver.winner_id)
        self.assertEqual(resolver.stall_seconds, 0.0)


class TemporaryWinnerBrainTests(unittest.TestCase):
    def test_temporary_winner_commits_to_a_cautious_crawl(self):
        brain = CarBrain(merge_style="rolling")
        blocked_merge = MergeObservation(
            distance_to_join=8.0,
            length=14.0,
            vehicles=(MergeVehicle("stopped-nearby", -25.0, 0.0, 14.0),),
        )

        decision = brain.decide(
            CarObservation(
                cruise_speed=20.0,
                speed=0.0,
                distance_to_stop=0.0,
                must_yield=True,
                merge=blocked_merge,
                has_priority=False,
                temporary_winner=True,
            ),
            0.05,
        )

        self.assertEqual(decision.state, BehaviorState.ENTERING_INTERSECTION)
        self.assertTrue(decision.request_claim)
        self.assertGreater(decision.desired_speed, 0.0)
        self.assertLessEqual(decision.desired_speed, 3.0)
        self.assertEqual(decision.wait_reason, "breaking soft deadlock")

    def test_committed_winner_keeps_crawl_cap_after_it_owns_the_claim(self):
        decision = CarBrain().decide(
            CarObservation(
                cruise_speed=20.0,
                speed=0.5,
                temporary_winner=True,
            ),
            0.05,
        )

        self.assertEqual(decision.state, BehaviorState.ENTERING_INTERSECTION)
        self.assertEqual(decision.desired_speed, 3.0)
        self.assertEqual(decision.wait_reason, "breaking soft deadlock")


class TemporaryWinnerSimulationTests(unittest.TestCase):
    def test_blocked_committed_winner_pauses_even_when_it_already_has_a_claim(self):
        fixture = Path(__file__).parent / "fixtures/slip_lanes.json"
        city = world_from_dict(json.loads(fixture.read_text())).city_map
        traffic = TestTrafficSimulation(spawn_interval=1000.0)
        ends = {junction.position: junction for junction in city.cul_de_sacs}
        joining = traffic.spawn_car(
            city, ends[(2630.0, 1846.0)], ends[(3356.0, 1770.0)],
        )
        circulating = traffic.spawn_car(
            city, ends[(2968.0, 1586.0)], ends[(3356.0, 1770.0)],
        )
        assert joining is not None and circulating is not None
        first, entry = joining.controlled_movements[:2]
        target = next(
            segment for segment in circulating.route_segments
            if segment[2] == entry[2].merge_target
        )
        joining.distance = first[0] - joining.length / 2 - 5.0
        joining.speed = 0.0
        joining.brain.state = BehaviorState.ENTERING_INTERSECTION
        joining.advance(0)
        circulating.distance = target[0] - 65.0
        circulating.speed = 17.6
        circulating.advance(0)
        self.assertTrue(traffic.stop_coordinator.claim_temporary_winner(
            joining.id, first[2],
        ))
        joining._claimed_movement = first[2]
        traffic.deadlock_resolver.stall_seconds = 5.0
        traffic.deadlock_resolver.winner_id = joining.id
        traffic.deadlock_resolver.winner_movement_id = first[2].id
        before = joining.distance

        traffic.update(city, 0.05)

        self.assertEqual(joining.distance, before)
        self.assertEqual(joining.brain.desired_speed, 0.0)
        self.assertEqual(traffic.deadlock_resolver.winner_id, joining.id)

        traffic.cars.remove(circulating)
        traffic.stop_coordinator.forget_car(circulating.id)
        traffic.update(city, 0.05)

        self.assertGreater(joining.distance, before)
        self.assertLessEqual(joining.brain.desired_speed, 3.0)
        self.assertEqual(traffic.deadlock_resolver.winner_id, joining.id)


if __name__ == "__main__":
    unittest.main()
