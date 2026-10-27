from tests.reference_traffic import as_reference
"""Differential tests run an actual C++ driver, not saved Python decisions."""
import os
import unittest

from merge_lab import scenario_catalog
from native_traffic import NativeTrafficEngine


class NativeTrafficTests(unittest.TestCase):
    def test_native_runs_without_python_driving_callbacks(self):
        scenario = next(s for s in scenario_catalog() if s.name == 'roundabout-clear-entry')
        city, reference = scenario.build(3)
        as_reference(reference)
        native = NativeTrafficEngine.from_simulation(reference)
        initial = {c.id: c.distance for c in reference.cars}
        with native:
            for _ in range(200):
                reference.update(city, 0.05)
                native.step(0.05)
                states = native.snapshot()
                self.assertEqual(set(states), {c.id for c in reference.cars})
                for car in reference.cars:
                    with self.subTest(car=car.id):
                        actual = states[car.id]
                        self.assertAlmostEqual(actual.distance, car.distance, places=7)
                        self.assertAlmostEqual(actual.speed, car.speed, places=7)
                        self.assertEqual(actual.state, car.brain.state.value)
                        self.assertEqual(actual.signal, car.brain.signal_intent.value)
                        self.assertEqual(actual.reason, car.brain.wait_reason)
            self.assertTrue(any(s.distance > initial[key] for key, s in states.items()))


class NativeScenarioParityTests(unittest.TestCase):
    def test_all_merge_lab_trajectories_match_python(self):
        from unittest.mock import patch
        scenarios = scenario_catalog()
        selected = os.environ.get('NATIVE_PARITY_SCENARIO')
        if selected:
            scenarios = tuple(s for s in scenarios if s.name == selected)
            self.assertTrue(scenarios, 'Unknown NATIVE_PARITY_SCENARIO: ' + selected)
        seconds = float(os.environ.get('NATIVE_PARITY_SECONDS', '30'))
        self.assertGreater(seconds, 0)
        seed = int(os.environ.get('NATIVE_PARITY_SEED', '7'))
        for scenario in scenarios:
            with self.subTest(scenario=scenario.name):
                city, reference = scenario.build(seed)
                as_reference(reference)
                with NativeTrafficEngine.from_simulation(reference) as native:
                    original_spawn = reference.spawn_car
                    def spawn(*args, **kwargs):
                        car = original_spawn(*args, **kwargs)
                        if car is not None:
                            native.spawn(car)
                        return car
                    with patch.object(reference, 'spawn_car', side_effect=spawn):
                        for tick in range(round(seconds / 0.05)):
                            completed = reference.update(city, 0.05)
                            native.step(0.05)
                            actual = native.snapshot(include_completed=True)
                            expected = list(reference.cars) + completed
                            self.assertEqual(set(actual), {c.id for c in expected}, (scenario.name, tick))
                            for car in expected:
                                s = actual[car.id]
                                context = (scenario.name, tick, car.id)
                                self.assertAlmostEqual(s.distance, car.distance, places=7, msg=str(context))
                                self.assertAlmostEqual(s.speed, car.speed, places=7, msg=str(context))
                                self.assertAlmostEqual(s.position[0], car.position[0], places=7, msg=str(context))
                                self.assertAlmostEqual(s.position[1], car.position[1], places=7, msg=str(context))
                                self.assertAlmostEqual(s.heading[0], car.heading[0], places=7, msg=str(context))
                                self.assertAlmostEqual(s.heading[1], car.heading[1], places=7, msg=str(context))
                                self.assertAlmostEqual(s.desired_speed, car.brain.desired_speed, places=7, msg=str(context))
                                self.assertAlmostEqual(s.stopped_elapsed, car.brain.stopped_elapsed, places=7, msg=str(context))
                                self.assertEqual(s.state, car.brain.state.value, context)
                                self.assertEqual(s.reason, car.brain.wait_reason, context)
                                self.assertEqual(s.signal, car.brain.signal_intent.value, context)
                                self.assertEqual(s.phantom, car.brain.phantom_target, context)
                                self.assertEqual(s.claim, None if car.claimed_movement is None else car.claimed_movement.id, context)


if __name__ == '__main__':
    unittest.main()
