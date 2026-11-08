"""Persistent native configuration must still apply live Python edits."""
import random
import unittest
from unittest.mock import patch

from city import CityMap, Terrain
from models import ControlDefinition, ControlType
from traffic_testbed import RoadVehicleSimulation


class ConfigurationChangesTests(unittest.TestCase):
    def setUp(self):
        self.city = CityMap(terrain=Terrain(trees=[]))
        self.city.add_road([(0, 100), (500, 100)])
        self.city.add_road([(250, -150), (250, 100)])
        self.simulation = RoadVehicleSimulation(update_mode='cpp', rng=random.Random(42))
        self.backend = self.simulation._native_backend(self.city)
        self.addCleanup(self.simulation._discard_native)

    def test_unchanged_configuration_does_not_scan_connections_or_resend_settings(self):
        self.backend.configure()
        self.backend.publish_random()
        class NoScan(list):
            def __iter__(self):
                raise AssertionError('unchanged tick scanned all connections')
        self.backend.engine._connections = NoScan(self.backend.engine._connections)
        with patch.object(self.backend.engine, '_call', wraps=self.backend.engine._call) as calls:
            self.backend.configure()
        names = [call.args[0] for call in calls.call_args_list]
        self.assertNotIn('nt_rng_set', names)
        self.assertNotIn('nt_speed', names)
        self.assertNotIn('nt_trace_enable', names)

    def test_control_edit_is_sent_once_without_rescanning_network(self):
        self.backend.configure()
        connection = self.backend.engine._connections[0]
        new_kind = ControlType.STOP if connection.control.kind != ControlType.STOP else ControlType.YIELD
        connection.control = ControlDefinition(new_kind)
        with patch.object(self.backend.engine, 'set_control', wraps=self.backend.engine.set_control) as calls:
            self.backend.configure()
            self.backend.configure()
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(calls.call_args.args, (connection, new_kind))

    def test_external_rng_draw_is_imported_before_next_native_draw(self):
        self.backend.configure()
        self.backend.publish_random()
        self.simulation.rng.random()
        expected = random.Random()
        expected.setstate(self.simulation.rng.getstate())
        self.backend.configure()
        actual = self.backend.engine._call('nt_choice', 12345)
        self.backend.publish_random()
        self.assertEqual(actual, expected.randrange(12345))
        self.assertEqual(self.simulation.rng.getstate(), expected.getstate())

    def test_unchanged_native_rng_skips_python_state_reconstruction(self):
        self.backend.configure()
        self.backend.publish_random()
        with patch.object(self.simulation.rng, 'setstate', side_effect=AssertionError('unchanged RNG export')):
            self.backend.publish_random()
            self.backend.configure()
            self.backend.publish_random()

    def test_native_rng_draws_still_publish_across_state_block_boundaries(self):
        self.backend.configure()
        self.backend.publish_random()
        expected = random.Random()
        expected.setstate(self.simulation.rng.getstate())
        for _ in range(700):
            self.assertEqual(self.backend.engine._call('nt_choice', 12345), expected.randrange(12345))
            self.backend.publish_random()
        self.assertEqual(self.simulation.rng.getstate(), expected.getstate())

    def test_rng_reseed_and_gaussian_cache_survive_publication(self):
        self.backend.configure()
        self.backend.publish_random()
        self.simulation.rng.seed(123)
        self.simulation.rng.gauss(0, 1)
        expected = random.Random()
        expected.setstate(self.simulation.rng.getstate())
        self.backend.configure()
        self.backend.publish_random()
        self.backend.configure()
        self.backend.publish_random()
        self.assertEqual(self.simulation.rng.getstate(), expected.getstate())
        self.assertEqual(self.backend.engine._call('nt_choice', 17), expected.randrange(17))
        self.backend.publish_random()
        self.assertEqual(self.simulation.rng.getstate(), expected.getstate())

    def test_speed_and_debug_changes_are_applied_after_cached_configuration(self):
        from traffic_debugger import TrafficDebugger
        self.backend.configure()
        self.simulation.speed_mph = 19
        self.simulation.debugger = TrafficDebugger()
        with patch.object(self.backend.engine, '_call', wraps=self.backend.engine._call) as calls:
            self.backend.configure()
            self.backend.configure()
        speeds = [call.args[1] for call in calls.call_args_list if call.args[0] == 'nt_speed']
        traces = [call.args[1] for call in calls.call_args_list if call.args[0] == 'nt_trace_enable']
        self.assertEqual(speeds, [19])
        self.assertEqual(traces, [1])

    def test_changing_signal_controller_revokes_old_green_permission(self):
        from intersection_controls import SignalState, SignalAspect
        connection = self.backend.engine._connections[0]
        connection.control = ControlDefinition(ControlType.SIGNAL, 'first')
        self.simulation._signal_states = {
            'first': SignalState(SignalAspect.GREEN, 0, frozenset({connection.id}))}
        self.backend.configure()
        index = self.backend.engine._connection_ids[id(connection)]
        self.assertEqual(self.backend.engine._signal_aspects[index], 1)
        connection.control = ControlDefinition(ControlType.SIGNAL, 'second')
        self.backend.configure()
        self.assertEqual(self.backend.engine._signal_aspects[index], 0)
