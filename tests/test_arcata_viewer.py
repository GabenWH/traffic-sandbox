"""Zoom keeps the map location under the cursor fixed, including after panning."""
import unittest

from tools import arcata_workday_view as viewer


class ArcataViewerZoomTests(unittest.TestCase):
    def test_cursor_stays_anchored_after_panning(self):
        zoom, pan = viewer.zoom_at(1, (40, -20), (700, 200), (1000, 600), 1.2)
        self.assertAlmostEqual(zoom, 1.2)
        self.assertAlmostEqual(pan[0], 8)
        self.assertAlmostEqual(pan[1], -4)
        zoom, pan = viewer.zoom_at(zoom, pan, (700, 200), (1000, 600), 1/1.2)
        self.assertAlmostEqual(zoom, 1)
        self.assertAlmostEqual(pan[0], 40)
        self.assertAlmostEqual(pan[1], -20)

    def test_zoom_limit_keeps_pan_fixed(self):
        zoom, pan = viewer.zoom_at(30, (40, -20), (700, 200), (1000, 600), 1.2)
        self.assertEqual(zoom, 30)
        self.assertEqual(pan, (40, -20))
