import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'run_arcata_workday_stress.py'


class WorkdayDurationTests(unittest.TestCase):
    def test_invalid_duration_is_rejected_before_loading_map(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--hours', '-1'],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('hours must be greater than zero', result.stderr)
        self.assertNotIn('map_loaded', result.stdout)

    def test_duration_is_documented_in_help(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--help'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--hours', result.stdout)


if __name__ == '__main__':
    unittest.main()
