"""Regression coverage for the native driver's finite car-following lookahead."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class NativeLeaderLookaheadTests(unittest.TestCase):
    def test_128_foot_boundary_and_vehicle_length_bound(self):
        root = Path(__file__).resolve().parents[1]
        source = Path(__file__).with_suffix('.cpp')
        with tempfile.TemporaryDirectory(prefix='native-leader-lookahead-') as directory:
            executable = Path(directory) / 'leader-lookahead-test'
            subprocess.run(
                ['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                 str(source), '-o', str(executable)],
                cwd=root, check=True, capture_output=True, text=True,
            )
            subprocess.run([str(executable)], check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
