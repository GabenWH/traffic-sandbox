"""Behavior tests for constructed-road routed car brains."""

import random
import unittest

from car_brain import BehaviorState, CarBrain, CarObservation, SignalIntent
from city import CityMap, Terrain
from models import ControlDefinition, ControlType, ManeuverType
from traffic_testbed import TestTrafficSimulation
from ui.dashboards import routed_car_debug_lines


class CarBrainTests(unittest.TestCase):
    def test_brain_signals_for_upcoming_turns_and_u_turns(self) -> None:
        cases = (
            (ManeuverType.LEFT_TURN, SignalIntent.LEFT),
            (ManeuverType.RIGHT_TURN, SignalIntent.RIGHT),
            (ManeuverType.U_TURN, SignalIntent.LEFT),
            (ManeuverType.THROUGH, SignalIntent.NONE),
        )
        for maneuver, expected in cases:
            with self.subTest(maneuver=maneuver):
                brain = CarBrain()
                brain.decide(
                    CarObservation(
                        cruise_speed=40.0,
                        speed=30.0,
                        next_maneuver=maneuver,
                        distance_to_maneuver=80.0,
                    ),
                    0.1,
                )
                self.assertEqual(brain.signal_intent, expected)

    def test_brain_does_not_signal_a_distant_turn(self) -> None:
        brain = CarBrain()

        brain.decide(
            CarObservation(
                cruise_speed=40.0,
                speed=30.0,
                next_maneuver=ManeuverType.LEFT_TURN,
                distance_to_maneuver=101.0,
            ),
            0.1,
        )

        self.assertEqual(brain.signal_intent, SignalIntent.NONE)

    def test_brain_keeps_signal_on_inside_turn(self) -> None:
        brain = CarBrain()

        brain.decide(
            CarObservation(
                cruise_speed=40.0,
                speed=20.0,
                next_maneuver=ManeuverType.RIGHT_TURN,
                distance_to_maneuver=0.0,
                inside_maneuver=True,
            ),
            0.1,
        )

        self.assertEqual(brain.signal_intent, SignalIntent.RIGHT)

    def test_brain_approaches_a_stop_line_without_crossing_it(self) -> None:
        brain = CarBrain()

        decision = brain.decide(
            CarObservation(
                cruise_speed=40.0,
                speed=30.0,
                distance_to_stop=8.0,
                must_stop=True,
            ),
            0.1,
        )

        self.assertEqual(decision.state, BehaviorState.APPROACHING_STOP)
        self.assertLess(decision.desired_speed, 30.0)

    def test_brain_waits_after_reaching_stop_line(self) -> None:
        brain = CarBrain()

        decision = brain.decide(
            CarObservation(
                cruise_speed=40.0,
                speed=0.0,
                distance_to_stop=0.0,
                must_stop=True,
                has_priority=False,
            ),
            0.5,
        )

        self.assertEqual(decision.state, BehaviorState.WAITING_FOR_PRIORITY)
        self.assertEqual(decision.desired_speed, 0.0)
        self.assertEqual(decision.wait_reason, "waiting for all-way-stop priority")

    def test_spawned_car_owns_an_inspectable_brain(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (400, 100)])
        city.add_road([(200, 0), (200, 200)])
        junction = city.standard_intersections[0]
        for connection in junction.lane_connections:
            connection.control = ControlDefinition(ControlType.STOP)
        west = next(item for item in city.cul_de_sacs if item.position == (0.0, 100.0))
        east = next(item for item in city.cul_de_sacs if item.position == (400.0, 100.0))
        traffic = TestTrafficSimulation(rng=random.Random(1))

        car = traffic.spawn_car(city, west, east)

        assert car is not None
        self.assertIsInstance(car.brain, CarBrain)
        self.assertTrue(any(link.kind == "lane_connection" for link in car.route.edges))
        self.assertEqual(car.brain.state, BehaviorState.CRUISING)

    def test_existing_car_observes_stop_control_enabled_after_spawn(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (400, 100)])
        city.add_road([(200, 0), (200, 200)])
        west = next(item for item in city.cul_de_sacs if item.position == (0.0, 100.0))
        east = next(item for item in city.cul_de_sacs if item.position == (400.0, 100.0))
        traffic = TestTrafficSimulation(spawn_interval=1000.0, rng=random.Random(8))
        car = traffic.spawn_car(city, west, east)
        assert car is not None

        city.standard_intersections[0].set_all_way_stop(True)
        for _ in range(200):
            traffic.update(city, 0.05)
            if car.brain.state is BehaviorState.APPROACHING_STOP:
                break

        self.assertEqual(car.brain.state, BehaviorState.APPROACHING_STOP)

    def test_test_car_stops_and_dwells_before_crossing_all_way_stop(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (400, 100)])
        city.add_road([(200, 0), (200, 200)])
        junction = city.standard_intersections[0]
        for connection in junction.lane_connections:
            connection.control = ControlDefinition(ControlType.STOP)
        west = next(item for item in city.cul_de_sacs if item.position == (0.0, 100.0))
        east = next(item for item in city.cul_de_sacs if item.position == (400.0, 100.0))
        traffic = TestTrafficSimulation(spawn_interval=1000.0, rng=random.Random(2))
        car = traffic.spawn_car(city, west, east)
        assert car is not None
        stop_distance = car.controlled_movements[0][0]
        saw_full_stop = False
        stopped_frames = 0

        for _ in range(300):
            traffic.update(city, 0.05)
            if car.brain.state in (
                BehaviorState.STOPPED,
                BehaviorState.WAITING_FOR_PRIORITY,
            ):
                saw_full_stop = True
                stopped_frames += 1
                self.assertLessEqual(
                    car.distance + car.length / 2,
                    stop_distance + 1e-6,
                )
                self.assertIsNone(car.claimed_movement)
            if car.distance > stop_distance + 1.0:
                break

        self.assertTrue(saw_full_stop)
        self.assertGreaterEqual(stopped_frames, 9)
        self.assertGreater(car.distance, stop_distance + 1.0)
        self.assertIn(
            car.brain.state,
            (BehaviorState.ENTERING_INTERSECTION, BehaviorState.CLEARING_INTERSECTION),
        )

    def test_debug_lines_expose_each_car_brain_decision(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (200, 0)])
        traffic = TestTrafficSimulation(rng=random.Random(4))
        car = traffic.spawn_car(city, city.cul_de_sacs[0], city.cul_de_sacs[1])
        assert car is not None
        car.brain.wait_reason = "following queued car"
        car.brain.signal_intent = SignalIntent.LEFT

        lines = routed_car_debug_lines([car])

        self.assertEqual(len(lines), 1)
        self.assertIn(car.id, lines[0])
        self.assertIn("cruising", lines[0])
        self.assertIn("following queued car", lines[0])
        self.assertIn("signal=left", lines[0])


if __name__ == "__main__":
    unittest.main()
