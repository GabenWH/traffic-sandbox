"""Fixed-time signal behavior and routed-traffic integration tests."""

import random
import unittest

from car_brain import BehaviorState, CarBrain, CarObservation
from city import CityMap, Terrain
from intersection_controls import (
    AllWayStopCoordinator,
    FixedTimeSignalController,
    SignalAspect,
    SignalPhase,
    SignalPlan,
    SignalPlanChange,
    movements_conflict,
)
from models import ControlDefinition, ControlType
from traffic_testbed import RoadVehicleSimulation


class FixedTimeSignalControllerTests(unittest.TestCase):
    def test_phase_boundaries_include_yellow_all_red_and_cycle_wrap(self):
        plan = SignalPlan((
            SignalPhase(10.0, frozenset({"north"}), yellow_seconds=3.0,
                        all_red_seconds=2.0),
            SignalPhase(8.0, frozenset({"east"}), yellow_seconds=3.0,
                        all_red_seconds=1.0),
        ))
        controller = FixedTimeSignalController(plan)

        self.assertEqual(controller.state_at(0.0).aspect, SignalAspect.GREEN)
        self.assertTrue(controller.is_green("north", 9.99))
        self.assertEqual(controller.state_at(10.0).aspect, SignalAspect.YELLOW)
        self.assertFalse(controller.is_green("north", 10.0))
        self.assertEqual(controller.state_at(13.0).aspect, SignalAspect.ALL_RED)
        self.assertTrue(controller.is_green("east", 15.0))
        self.assertEqual(controller.state_at(24.0).aspect, SignalAspect.YELLOW)
        self.assertTrue(controller.is_green("north", 27.0))

    def test_scheduled_plan_change_restarts_cycle_at_requested_time(self):
        initial = SignalPlan((SignalPhase(60.0, frozenset({"north"}), 0.0, 0.0),))
        changed = SignalPlan((SignalPhase(60.0, frozenset({"east"}), 0.0, 0.0),))
        controller = FixedTimeSignalController(
            initial,
            schedule=(SignalPlanChange(17.5, changed),),
        )

        self.assertTrue(controller.is_green("north", 17.49))
        self.assertFalse(controller.is_green("north", 17.5))
        self.assertTrue(controller.is_green("east", 17.5))

    def test_rejects_invalid_phase_durations_and_schedule_order(self):
        with self.assertRaises(ValueError):
            SignalPhase(0.0, frozenset({"north"}))
        plan = SignalPlan((SignalPhase(10.0, frozenset({"north"})),))
        with self.assertRaises(ValueError):
            FixedTimeSignalController(
                plan,
                schedule=(
                    SignalPlanChange(20.0, plan),
                    SignalPlanChange(10.0, plan),
                ),
            )


class SignalBrainTests(unittest.TestCase):
    def test_red_signal_holds_without_stop_sign_dwell_or_claim_request(self):
        brain = CarBrain()

        decision = brain.decide(
            CarObservation(
                cruise_speed=30.0,
                speed=0.0,
                distance_to_stop=0.0,
                signal_red=True,
            ),
            0.5,
        )

        self.assertEqual(decision.state, BehaviorState.WAITING_FOR_PRIORITY)
        self.assertEqual(decision.desired_speed, 0.0)
        self.assertEqual(decision.wait_reason, "red signal")
        self.assertFalse(decision.register_stop)
        self.assertFalse(decision.request_claim)
        self.assertEqual(brain.stopped_elapsed, 0.0)

    def test_green_signal_requests_a_claim_without_stop_dwell(self):
        brain = CarBrain()

        decision = brain.decide(
            CarObservation(
                cruise_speed=30.0,
                speed=0.0,
                distance_to_stop=0.0,
                signal_green=True,
                has_priority=True,
            ),
            0.05,
        )

        self.assertEqual(decision.state, BehaviorState.ENTERING_INTERSECTION)
        self.assertTrue(decision.request_claim)
        self.assertFalse(decision.register_stop)


class SignalClaimTests(unittest.TestCase):
    def test_signal_claim_blocks_conflicting_movement_until_release(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        movements = city.standard_intersections[0].lane_connections
        first = movements[0]
        conflict = next(item for item in movements
                        if item is not first and movements_conflict(first, item))
        compatible = next(item for item in movements
                          if item is not first and not movements_conflict(first, item))
        coordinator = AllWayStopCoordinator()
        first.control = ControlDefinition(ControlType.SIGNAL, "main")

        self.assertTrue(coordinator.can_claim_signal("northbound", first))
        self.assertTrue(coordinator.claim_signal("northbound", first))
        self.assertFalse(coordinator.can_claim_signal("crossing", conflict))
        self.assertTrue(coordinator.can_claim_signal("parallel", compatible))

        coordinator.release("northbound", first)
        self.assertTrue(coordinator.can_claim_signal("crossing", conflict))


class RoutedSignalIntegrationTests(unittest.TestCase):
    def make_scenario(self, update_mode, *, scheduled_red=False):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)], name="East West")
        city.add_road([(300, 0), (300, 600)], name="North South")
        west = next(item for item in city.cul_de_sacs
                    if item.position == (0.0, 300.0))
        east = next(item for item in city.cul_de_sacs
                    if item.position == (600.0, 300.0))
        route = city.find_vehicle_route_between(west, east)
        assert route is not None
        movement = next(
            link.value for link in route.edges
            if link.kind == "lane_connection"
        )
        movement.control = ControlDefinition(ControlType.SIGNAL, "main")
        green = SignalPlan((SignalPhase(
            120.0, frozenset({movement.id}), yellow_seconds=0.0,
            all_red_seconds=0.0,
        ),))
        red = SignalPlan((SignalPhase(
            120.0, frozenset(), yellow_seconds=0.0, all_red_seconds=0.0,
        ),))
        schedule = (SignalPlanChange(0.1, red),) if scheduled_red else ()
        traffic = RoadVehicleSimulation(
            spawn_interval=1000.0,
            rng=random.Random(7),
            update_mode=update_mode,
            signal_controllers={
                "main": FixedTimeSignalController(green, schedule=schedule),
            },
        )
        car = traffic.spawn_car(city, west, east)
        assert car is not None
        start, _, _ = next(
            item for item in car.controlled_movements if item[2] is movement
        )
        car.distance = start - car.length / 2 - 6.0
        car.speed = 0.0
        car.advance(0.0)
        return city, traffic, car, movement

    def test_red_signal_stops_both_update_modes_without_claiming(self):
        for mode in ("legacy", "data_first"):
            with self.subTest(mode=mode):
                city, traffic, car, movement = self.make_scenario(mode)
                controller = FixedTimeSignalController(SignalPlan((SignalPhase(
                    120.0, frozenset(), yellow_seconds=0.0, all_red_seconds=0.0,
                ),)))
                traffic.signal_controllers["main"] = controller
                start = next(item[0] for item in car.controlled_movements
                             if item[2] is movement)

                for _ in range(300):
                    traffic.update(city, 0.05)

                self.assertLessEqual(car.distance + car.length / 2, start + 1e-6)
                self.assertIsNone(car.claimed_movement)
                self.assertEqual(car.brain.wait_reason, "red signal")

    def test_signal_without_a_controller_fails_closed(self):
        for mode in ("legacy", "data_first"):
            with self.subTest(mode=mode):
                city, traffic, car, movement = self.make_scenario(mode)
                traffic.signal_controllers.clear()
                start = next(item[0] for item in car.controlled_movements
                             if item[2] is movement)

                for _ in range(300):
                    traffic.update(city, 0.05)

                self.assertLessEqual(car.distance + car.length / 2, start + 1e-6)
                self.assertIsNone(car.claimed_movement)
                self.assertEqual(car.brain.wait_reason, "red signal")

    def test_deadlock_recovery_cannot_override_a_red_signal(self):
        for mode in ("legacy", "data_first"):
            with self.subTest(mode=mode):
                city, traffic, car, movement = self.make_scenario(mode)
                red = SignalPlan((SignalPhase(
                    120.0, frozenset(), yellow_seconds=0.0, all_red_seconds=0.0,
                ),))
                traffic.signal_controllers["main"] = FixedTimeSignalController(red)
                traffic.deadlock_resolver.stall_seconds = 10.0
                traffic.deadlock_resolver.winner_id = car.id
                traffic.deadlock_resolver.winner_movement_id = movement.id
                start = next(item[0] for item in car.controlled_movements
                             if item[2] is movement)

                traffic.update(city, 0.05)

                self.assertLessEqual(car.distance + car.length / 2, start + 1e-6)
                self.assertIsNone(car.claimed_movement)

    def test_green_claim_carries_car_through_phase_change_and_releases_rear_clear(self):
        for mode in ("legacy", "data_first"):
            with self.subTest(mode=mode):
                city, traffic, car, movement = self.make_scenario(
                    mode, scheduled_red=True,
                )

                traffic.update(city, 0.05)
                self.assertIs(car.claimed_movement, movement)
                before_red = car.distance

                traffic.update(city, 0.05)
                self.assertGreater(car.distance, before_red)
                self.assertIs(car.claimed_movement, movement)

                for _ in range(300):
                    traffic.update(city, 0.05)

                self.assertIsNone(car.claimed_movement)


if __name__ == "__main__":
    unittest.main()
