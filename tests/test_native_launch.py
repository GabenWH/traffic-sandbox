"""Choose the native simulation from the interactive application's launcher."""
import subprocess
import sys
from pathlib import Path
import unittest
import tempfile
import json


class NativeLaunchTests(unittest.TestCase):
    def test_native_selection_is_available_without_opening_a_window(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / 'freeway_simulator.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--traffic-engine', result.stdout)
        self.assertIn('native', result.stdout)

    def test_parser_accepts_native(self):
        import freeway_simulator
        self.assertTrue(hasattr(freeway_simulator, 'parse_args'), 'Engine selection parser missing')
        self.assertEqual(freeway_simulator.parse_args(['--traffic-engine', 'native']).traffic_engine, 'native')

    def test_headless_benchmark_records_actual_native_spawn_phases(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'timings.json'
            result = subprocess.run([sys.executable, str(root / 'tools/benchmark_native_spawning.py'),
                                     '--seconds', '.1', '--warmup', '0', '--scenario', 'roundabout-clear-entry',
                                     '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual({run['engine'] for run in report['runs']}, {'native', 'data_first'})
            for run in report['runs']:
                self.assertEqual(len(run['samples']), 2)
                self.assertGreater(run['summary']['wall_ms']['mean'], 0)
            native = next(run for run in report['runs'] if run['engine'] == 'native')
            self.assertIn('native_spawning', native['summary'])
            self.assertEqual(native['summary']['native_engine']['ticks'], 2)
            self.assertGreater(native['summary']['native_engine']['decision_ms'], 0)
