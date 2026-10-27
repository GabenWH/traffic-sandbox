"""Signal permissions follow light state; physical bodies own clearance."""
import random
import unittest
from unittest.mock import patch

from car_brain import BehaviorState
from city import CityMap, Terrain
from intersection_controls import (FixedTimeSignalController, SignalAspect,
                                   SignalPhase, SignalPlan, SignalPlanChange)
from models import ControlDefinition, ControlType, IntersectionKind
from traffic_testbed import RoadVehicleSimulation


def scenario(mode):
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0, 300), (600, 300)])
    city.add_road([(300, 0), (300, 600)])
    ends = {j.position: j for j in city.cul_de_sacs}
    traffic = RoadVehicleSimulation(spawn_interval=1000, rng=random.Random(7),
                                    update_mode=mode)
    car = traffic.spawn_car(city, ends[(0., 300.)], ends[(600., 300.)])
    start, end, movement = next(item for item in car.controlled_movements
                               if item[2].maneuver.kind.value != 'u_turn')
    for connection in city.standard_intersections[0].lane_connections:
        connection.control = ControlDefinition(ControlType.SIGNAL, 'main')
    traffic.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
        SignalPhase(120., {movement.id}, 0., 0.),)))
    car.distance, car.speed = start - car.length / 2 - 6., 0.
    car.advance(0)
    return city, traffic, car, (start, end, movement), ends


class SignalPermissionTests(unittest.TestCase):
    def test_each_car_reads_one_shared_signal_aspect_per_update(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, _, _ = scenario(mode)
                with patch.object(t, '_signal_aspect', wraps=t._signal_aspect) as read_aspect:
                    t.update(city, .05)
                self.assertEqual(read_aspect.call_count, 0)
                self.assertGreater(car.speed, 0)

    def test_data_first_only_rechecks_signal_after_a_new_claim(self):
        city, t, car, _, _ = scenario('cpp')
        with patch.object(
            t.stop_coordinator,
            'can_enter_signal',
            wraps=t.stop_coordinator.can_enter_signal,
        ) as check_entry:
            t.update(city, .05)
        self.assertEqual(check_entry.call_count, 0)
        self.assertGreater(car.speed, 0)

    def test_far_green_approach_defers_physical_clearance_check(self):
        city, t, car, (start, _, _), _ = scenario('cpp')
        car.distance = start - car.length / 2 - 200.
        car.speed = 10.
        car.advance(0)
        before = car.distance
        with patch.object(
            t.stop_coordinator,
            'can_enter_signal',
            wraps=t.stop_coordinator.can_enter_signal,
        ) as check_entry:
            t.update(city, .05)
        self.assertEqual(check_entry.call_count, 0)
        self.assertGreater(car.distance, before)

    def test_legacy_refreshes_signal_occupancy_incrementally_per_car(self):
        city, t, car, _, _ = scenario('cpp')
        with patch.object(
            t,
            '_observe_signal_occupancy',
            wraps=t._observe_signal_occupancy,
        ) as refresh_all:
            t.update(city, .05)
        self.assertEqual(refresh_all.call_count, 0)

    def test_data_first_refreshes_signal_occupancy_incrementally_after_batch(self):
        city, t, car, _, _ = scenario('cpp')
        with patch.object(
            t,
            '_observe_signal_occupancy',
            wraps=t._observe_signal_occupancy,
        ) as refresh_all:
            t.update(city, .05)
        self.assertEqual(refresh_all.call_count, 0)

    def test_signal_merge_latches_entry_speed_without_reserving(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city = CityMap(terrain=Terrain(trees=[]))
                city.add_road([(0, 300), (600, 300)])
                city.add_road([(300, 0), (300, 600)])
                city.standard_intersections[0].kind = IntersectionKind.ROUNDABOUT
                city.rebuild_mobility_network()
                ends = {j.position: j for j in city.cul_de_sacs}
                t = RoadVehicleSimulation(spawn_interval=1000, update_mode=mode)
                car = t.spawn_car(city, ends[(0., 300.)], ends[(600., 300.)])
                start, end, m = next(x for x in car.controlled_movements if x[2].merge_target)
                m.control = ControlDefinition(ControlType.SIGNAL, 'main')
                t.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
                    SignalPhase(120., {m.id}, 0., 0.),)))
                car.distance, car.speed = start-car.length/2, 10.
                car.advance(0)
                t.update(city, .05)
                self.assertIsNone(car.claimed_movement)
                self.assertIsNotNone(car._merge_entry_speed)
                self.assertGreater(car.distance+car.length/2, start)
                car._merge_entry_speed = car.speed = 4.
                t.update(city, .05)
                self.assertLessEqual(car.speed, 4.)

    def test_signal_entry_rechecks_yield_claims_granted_in_same_batch(self):
        city, t, car, (start, _, m), ends = scenario('cpp')
        other = t.spawn_car(city, ends[(300., 0.)], ends[(300., 600.)])
        ostart, _, n = next(x for x in other.controlled_movements
                            if x[2].maneuver.kind.value != 'u_turn')
        n.control = ControlDefinition(ControlType.YIELD)
        car.distance, car.speed = start-car.length/2, 10.
        other.distance, other.speed = ostart-other.length/2, 10.
        car.advance(0)
        other.advance(0)
        t.update(city, .05)
        both_entered = (car.distance+car.length/2 > start+1e-8
                        and other.distance+other.length/2 > ostart+1e-8)
        self.assertFalse(both_entered)

    def test_conflicting_yellow_and_green_controllers_are_rejected(self):
        city, t, car, (start, _, m), ends = scenario('cpp')
        other = t.spawn_car(city, ends[(300., 0.)], ends[(300., 600.)])
        ostart, _, n = next(x for x in other.controlled_movements
                            if x[2].maneuver.kind.value != 'u_turn')
        n.control = ControlDefinition(ControlType.SIGNAL, 'other')
        t.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
            SignalPhase(.1, {m.id}, 3., 1.),)))
        t.signal_controllers['other'] = FixedTimeSignalController(SignalPlan((
            SignalPhase(20., {n.id}, 0., 0.),)))
        t.elapsed_time = .1
        car.distance, car.speed = start-car.length/2, 10.
        other.distance, other.speed = ostart-other.length/2, 10.
        car.advance(0)
        other.advance(0)
        with self.assertRaisesRegex(ValueError, 'Conflicting protected'):
            t.update(city, .05)

    def test_conflicting_protected_greens_are_configuration_errors(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, (_, _, m), ends = scenario(mode)
                other = t.spawn_car(city, ends[(300., 0.)], ends[(300., 600.)])
                n = next(x[2] for x in other.controlled_movements
                         if x[2].maneuver.kind.value != 'u_turn')
                t.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
                    SignalPhase(120., {m.id, n.id}, 0., 0.),)))
                with self.assertRaisesRegex(ValueError, 'Conflicting protected'):
                    t.update(city, .05)

    def test_green_followers_enter_before_leader_rear_clears(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, leader, (start, end, m), ends = scenario(mode)
                t.update(city, .05)
                leader.distance, leader.speed = start + 20., 5.
                leader.advance(0)
                follower = t.spawn_car(city, ends[(0., 300.)], ends[(600., 300.)])
                follower.distance, follower.speed = start - follower.length / 2, 0.
                follower.advance(0)
                before = follower.distance
                t.update(city, .05)
                self.assertLess(leader.distance - leader.length / 2, end)
                self.assertGreater(follower.distance, before)
                self.assertIsNone(leader.claimed_movement)
                self.assertIsNone(follower.claimed_movement)

    def test_stoppable_approach_does_not_keep_permission_after_green(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, (start, end, m), _ = scenario(mode)
                t.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
                    SignalPhase(10., {m.id}, 3., 1.),
                    SignalPhase(20., set(), 3., 1.),)))
                t.elapsed_time = 9.9
                t.update(city, .05)
                for _ in range(120): t.update(city, .05)
                self.assertLessEqual(car.distance + car.length / 2, start + 1e-7)
                self.assertIsNone(car.claimed_movement)

    def test_yellow_cannot_force_impossible_braking(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, (start, end, m), _ = scenario(mode)
                t.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
                    SignalPhase(10., {m.id}, 3., 1.),)))
                t.elapsed_time = 9.9
                car.distance, car.speed = start - car.length / 2 - 26., 25 * 22 / 15
                car.advance(0)
                for _ in range(30):
                    speed = car.speed
                    t.update(city, .05)
                    self.assertLessEqual((speed - car.speed) / .05, 24. + 1e-6)
                self.assertGreater(car.distance + car.length / 2, start)

    def test_ordinary_red_is_not_deadlock(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, _, _ = scenario(mode)
                t.signal_controllers.clear()
                for _ in range(180): t.update(city, .05)
                self.assertFalse(t.deadlock_resolver.hard_gridlock)
                self.assertIsNone(t.deadlock_resolver.winner_id)

    def test_old_winner_does_not_reserve_a_signal_on_green(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, (_, _, m), _ = scenario(mode)
                t.deadlock_resolver.stall_seconds = 10.
                t.deadlock_resolver.winner_id = car.id
                t.deadlock_resolver.winner_movement_id = m.id
                car.brain.state = BehaviorState.WAITING_FOR_PRIORITY
                t.update(city, .05)
                self.assertIsNone(car.claimed_movement)
                self.assertIsNone(t.deadlock_resolver.winner_id)

    def test_blank_controller_id_cannot_bind_empty_key(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, (start, _, m), _ = scenario(mode)
                t.signal_controllers[''] = t.signal_controllers.pop('main')
                m.control = ControlDefinition(ControlType.SIGNAL, None)
                t.update(city, .05)
                self.assertIsNone(car.claimed_movement)
                self.assertFalse(t.signal_is_green(m))

    def test_boundary_at_end_of_tick_does_not_admit_early(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, (start, _, m), _ = scenario(mode)
                t.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
                    SignalPhase(.025, set(), 0., 0.),
                    SignalPhase(2., {m.id}, 0., 0.),)))
                car.distance = start - car.length / 2
                car.advance(0)
                t.update(city, .025)
                self.assertEqual(car.distance + car.length / 2, start)
                t.update(city, .025)
                self.assertGreater(car.distance + car.length / 2, start)

    def test_opposing_green_waits_for_physical_rear_and_removal_clears_it(self):
        for mode in ('cpp',):
            with self.subTest(mode=mode):
                city, t, car, (start, end, m), ends = scenario(mode)
                other = t.spawn_car(city, ends[(300., 0.)], ends[(300., 600.)])
                ostart, _, n = next(x for x in other.controlled_movements
                                    if x[2].maneuver.kind.value != 'u_turn')
                car.distance, car.speed = start + 10., 0.
                car.speed_cap_mph = .01
                car.advance(0)
                other.distance, other.speed = ostart - other.length / 2, 0.
                other.advance(0)
                t.signal_controllers['main'] = FixedTimeSignalController(SignalPlan((
                    SignalPhase(120., {n.id}, 0., 0.),)))
                t.update(city, .05)
                self.assertEqual(other.distance + other.length / 2, ostart)
                t.remove_vehicle(car.id)
                t.update(city, .05)
                self.assertGreater(other.distance + other.length / 2, ostart)


class SafeScheduleTests(unittest.TestCase):
    def test_decimal_boundaries_agree_with_next_event_over_many_cycles(self):
        controller = FixedTimeSignalController(SignalPlan((
            SignalPhase(.1, {'a'}, 0., 0.), SignalPhase(.1, {'b'}, 0., 0.))))
        for at in (.1, .3, .5, 10.1):
            with self.subTest(at=at):
                self.assertTrue(controller.is_green('b', at))
                self.assertGreater(controller.next_boundary_after(at), at+.09)
        realistic = FixedTimeSignalController(SignalPlan((
            SignalPhase(1.03, {'a'}, .07, .02),)))
        self.assertEqual(realistic.state_at(9.99).aspect, SignalAspect.YELLOW)

    def test_requests_during_green_yellow_and_all_red_wait_for_clearance(self):
        original = SignalPlan((SignalPhase(10., {'north'}, 3., 2.),))
        changed = SignalPlan((SignalPhase(20., {'east'}, 3., 1.),))
        for requested in (5., 10.5, 13.5):
            with self.subTest(requested=requested):
                controller = FixedTimeSignalController(original, (
                    SignalPlanChange(requested, changed),))
                self.assertFalse(controller.is_green('east', requested))
                self.assertEqual(controller.state_at(13.5).aspect, SignalAspect.ALL_RED)
                self.assertTrue(controller.is_green('east', 15.))

    def test_latest_request_before_clearance_wins(self):
        original = SignalPlan((SignalPhase(10., {'north'}, 3., 2.),))
        controller = FixedTimeSignalController(original, (
            SignalPlanChange(5., SignalPlan((SignalPhase(20., {'east'}),))),
            SignalPlanChange(8., SignalPlan((SignalPhase(20., {'west'}),))),))
        self.assertTrue(controller.is_green('north', 9.))
        self.assertFalse(controller.is_green('east', 15.))
        self.assertTrue(controller.is_green('west', 15.))


if __name__ == '__main__': unittest.main()
