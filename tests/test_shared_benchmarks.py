"""The consolidation runner must call the shared-state benchmark API."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.benchmark_cpp_consolidation import CHILD


class SharedBenchmarkTests(unittest.TestCase):
    def test_consolidation_child_measures_current_shared_runtime(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-c', CHILD, str(root), '60'],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['mode'], 'shared')
        self.assertGreater(data['mean_active'], 0)
        self.assertGreater(data['wall_ms']['mean'], 0)
