"""Exercise native merge observations and the lifetime of intersection claims."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class NativeTrafficIndexTests(unittest.TestCase):
    def test_merge_candidates_and_claim_lifetimes(self):
        source = Path(__file__).with_suffix('.cpp')
        with tempfile.TemporaryDirectory(prefix='native-traffic-indexes-') as directory:
            executable = Path(directory) / 'traffic-indexes-test'
            build = subprocess.run(
                ['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                 str(source), '-o', str(executable)],
                capture_output=True, text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
