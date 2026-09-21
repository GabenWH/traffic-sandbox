"""The traffic debugger records facts without steering a car."""

import random
import unittest

from city import CityMap, Terrain
from traffic_debugger import TrafficDebugger
from traffic_testbed import TestTrafficSimulation


class TrafficDebuggerTests(unittest.TestCase):
    def setUp(self):
        self.city = CityMap(terrain=Terrain(trees=[]))
        self.city.add_road([(0, 100), (400, 100)])
        self.city.add_road([(200, 0), (200, 200)])
        self.ends = self.city.cul_de_sacs

    def test_records_one_frame_with_decision_and_phase_timing(self):
        debugger = TrafficDebugger(max_frames=4)
        traffic = TestTrafficSimulation(
            spawn_interval=1000, rng=random.Random(1), debugger=debugger,
        )
        car = traffic.spawn_car(self.city, self.ends[0], self.ends[1])

        traffic.update(self.city, 0.05)

        self.assertIsNotNone(car)
        frame = debugger.latest_frame
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.car_count, 1)
        self.assertEqual(frame.cars[0].car_id, car.id)
        self.assertIn("decision", frame.timings_ms)
        self.assertGreaterEqual(frame.timings_ms["total"], 0)
        self.assertEqual(frame.cars[0].speed_after, car.speed)
        self.assertEqual(frame.deadlock_stall_seconds, 0.0)
        self.assertIsNone(frame.temporary_winner_id)
        self.assertFalse(frame.hard_gridlock)

    def test_trace_is_bounded_and_serializable(self):
        debugger = TrafficDebugger(max_frames=2)
        traffic = TestTrafficSimulation(
            spawn_interval=1000, rng=random.Random(2), debugger=debugger,
        )
        traffic.spawn_car(self.city, self.ends[0], self.ends[1])

        for _ in range(3):
            traffic.update(self.city, 0.05)

        self.assertEqual(len(debugger.frames), 2)
        exported = debugger.as_dict()
        self.assertEqual(len(exported["frames"]), 2)
        self.assertIn("timings_ms", exported["frames"][-1])
