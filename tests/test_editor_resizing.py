"""Real editor resize checks, isolated so native hangs/crashes fail with a timeout."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


def run_scenario(test, name):
    result = subprocess.run(
        [sys.executable, '-X', 'faulthandler', '-m', 'tests.editor_resize_scenarios', name],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        timeout=90,
    )
    test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    for error in ('BadWindow', 'RenderBadPicture', 'Traceback', 'Assertion failed'):
        test.assertNotIn(error, result.stderr, result.stderr)


@unittest.skipUnless(importlib.util.find_spec('panda3d'), 'Panda3D is required')
class OffscreenResizeTests(unittest.TestCase):
    def test_offscreen_view_retains_a_valid_render_target(self):
        run_scenario(self,'offscreen')


@unittest.skipUnless(importlib.util.find_spec('panda3d') and os.environ.get('DISPLAY'),
                     'Panda3D and an X display are required')
class EditorResizeTests(unittest.TestCase):
    def run_scenario(self, name):
        run_scenario(self,name)

    def test_all_registered_canvas_tools_during_resize(self):
        self.run_scenario('tools')

    def test_road_building_placement_and_camera_picking_during_resize(self):
        self.run_scenario('construction')

    def test_save_load_new_and_dashboard_windows_during_resize(self):
        self.run_scenario('files')

    def test_building_clicks_interleaved_with_rapid_resize(self):
        self.run_scenario('rapid')

    def test_inspection_routes_transit_and_demolition_during_resize(self):
        self.run_scenario('actions')

    def test_unmap_restore_and_close_with_pending_resize(self):
        self.run_scenario('lifecycle')


if __name__ == '__main__':
    unittest.main()
