"""Regression coverage for native merge and intersection claim indexes."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class NativeTrafficIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).with_suffix('.cpp')
        directory = tempfile.TemporaryDirectory(prefix='native-traffic-indexes-')
        cls.addClassCleanup(directory.cleanup)
        cls.executable = Path(directory.name) / 'traffic-indexes-test'
        subprocess.run(
            ['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
             str(source), '-o', str(cls.executable)],
            check=True,
        )

    def run_native(self, *args):
        result = subprocess.run([str(self.executable), *args], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_merge_candidates_and_claim_lifetimes(self):
        self.run_native()

    def test_merge_observations_scale_with_local_traffic(self):
        self.run_native('merge')

    def test_claim_checks_scale_with_local_traffic(self):
        self.run_native('claim')
