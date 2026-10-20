"""Focused tests for the experimental strategic-only scheduler."""

import unittest

from strategic_intent_scheduler import StrategicDecisionScheduler


class StrategicDecisionSchedulerTests(unittest.TestCase):
    def test_new_vehicle_requires_immediate_decision(self):
        scheduler = StrategicDecisionScheduler()
        self.assertTrue(scheduler.due("car-1", 0))
        scheduler.completed("car-1", 0)
        self.assertFalse(scheduler.due("car-1", 0.1))
        self.assertTrue(scheduler.due("car-1", 1.5))

    def test_invalidation_forces_refresh(self):
        scheduler = StrategicDecisionScheduler()
        scheduler.completed("car-1", 2)
        self.assertTrue(scheduler.due("car-1", 2.01, invalidate=True))

    def test_exited_cars_are_forgotten(self):
        scheduler = StrategicDecisionScheduler()
        scheduler.completed("car-1", 0)
        scheduler.completed("car-2", 0)
        scheduler.retain({"car-2"})
        self.assertTrue(scheduler.due("car-1", 0.01))
        self.assertFalse(scheduler.due("car-2", 0.01))

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            StrategicDecisionScheduler(0)


if __name__ == "__main__":
    unittest.main()
