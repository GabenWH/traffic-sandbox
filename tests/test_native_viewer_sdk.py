"""SDK selection must not pass incompatible headers to native Panda code."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_viewer
from panda3d.core import PandaSystem


class NativeViewerSDKTests(unittest.TestCase):
    def make_sdk(self, include, version, *, eigen=False):
        include.mkdir(parents=True)
        (include / 'nodePath.h').write_text('')
        (include / 'pandaVersion.h').write_text(f'#define PANDA_VERSION_STR "{version}"\n')
        (include / 'dtool_config.h').write_text('#define HAVE_EIGEN 1\n' if eigen else '#undef HAVE_EIGEN\n')

    def test_explicit_incompatible_sdk_is_rejected_before_native_build(self):
        with tempfile.TemporaryDirectory() as directory:
            include = Path(directory) / 'include'
            self.make_sdk(include, '0.0.0')
            with patch.dict(os.environ, {'PANDA3D_INCLUDE_DIR': str(include)}, clear=True):
                with self.assertRaises(RuntimeError) as raised:
                    native_viewer._sdk_paths()
            self.assertIn('0.0.0', str(raised.exception))
            self.assertIn(PandaSystem.get_version_string(), str(raised.exception))
            self.assertIn(str(include), str(raised.exception))

    def test_missing_explicit_include_does_not_fall_back_to_another_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'missing'
            with patch.dict(os.environ, {'PANDA3D_INCLUDE_DIR': str(missing)}, clear=True):
                with self.assertRaises(RuntimeError) as raised:
                    native_viewer._sdk_paths()
            self.assertIn(str(missing), str(raised.exception))

    def test_same_version_sdk_with_incompatible_eigen_is_rejected(self):
        runtime_eigen = PandaSystem.get_global_ptr().has_system('eigen')
        with tempfile.TemporaryDirectory() as directory:
            include = Path(directory) / 'include'
            self.make_sdk(include, PandaSystem.get_version_string(), eigen=not runtime_eigen)
            with patch.dict(os.environ, {'PANDA3D_INCLUDE_DIR': str(include)}, clear=True):
                with self.assertRaises(RuntimeError) as raised:
                    native_viewer._sdk_paths()
            self.assertIn('Eigen', str(raised.exception))
            self.assertIn(str(include), str(raised.exception))

    def test_matching_project_sdk_and_its_eigen_are_found(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            include = root / 'build/panda-sdk/usr/include/panda3d'
            eigen = root / 'build/panda-sdk/eigen-3.4.0'
            self.make_sdk(include, PandaSystem.get_version_string(),
                          eigen=PandaSystem.get_global_ptr().has_system('eigen'))
            (eigen / 'Eigen').mkdir(parents=True)
            (eigen / 'Eigen/Core').write_text('')
            with patch.object(native_viewer, '__file__', str(root / 'native_viewer.py')):
                with patch.dict(os.environ, {}, clear=True):
                    found_include, _, found_eigen = native_viewer._sdk_paths()
            self.assertEqual(found_include, include)
            self.assertEqual(found_eigen, eigen)

    def test_real_text_replacement_and_clear(self):
        # Isolate native crashes so the test runner can report them as failures.
        program = '''
from panda3d.core import NodePath, TextNode
from native_viewer import NativeScene
root = NodePath('root')
scene = NativeScene(root)
try:
    scene.replace_texts([(10, 20, 15, .25, .5, .75, 1, 60, 1, 'first label')])
    text = root.find('**/+TextNode').node()
    assert text.get_text() == 'first label'
    assert text.get_align() == TextNode.A_center
    assert abs(text.get_wordwrap() - 4) < 1e-5
    assert all(abs(a-b) < 1e-5 for a,b in zip(text.get_text_color(), (.25, .5, .75, 1)))
    scene.replace_texts([(0, 0, 12, 1, 1, 1, 1, 0, 0, 'second label')])
    assert root.find_all_matches('**/+TextNode').get_num_paths() == 1
    assert root.find('**/+TextNode').node().get_text() == 'second label'
    scene.replace_texts([])
    assert root.find_all_matches('**/+TextNode').get_num_paths() == 0
finally:
    scene.close()
'''
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', program],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
