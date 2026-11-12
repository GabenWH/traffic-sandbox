"""Cross-projection contract tests for canonical construction drafts."""
import unittest
from ui_tools.construction_preview import road_preview, building_preview


class ConstructionPreviewParityTests(unittest.TestCase):
    def test_road_draft_is_identical_in_both_projections(self):
        preview = road_preview("two-lane", [(0., 0.)], [10.], (25., 10.), 20., 12., 1, 1)
        self.assertIs(preview.for_projection("2d"), preview.for_projection("3d"))
        self.assertEqual(preview.vertices, ((0., 0.), (25., 10.)))
        self.assertEqual(preview.elevation, (10., 20.))
        self.assertEqual(preview.width, 24.)

    def test_building_footprint_is_identical_in_both_projections(self):
        preview = building_preview("home", (50., 60.), 20., 10.)
        self.assertIs(preview.for_projection("2d"), preview.for_projection("3d"))
        self.assertEqual(preview.vertices, ((40., 55.), (60., 55.),
                                            (60., 65.), (40., 65.)))

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            road_preview("road", [(0., 0.)], [], None, 0., 12., 1, 1)
        with self.assertRaises(ValueError):
            building_preview("house", (0., 0.), 10., float("nan"))
        with self.assertRaises(ValueError):
            road_preview("road", [], [], None, 0., 12., 0, 0)

    def test_preview_does_not_mutate_draft(self):
        points = [(0., 0.)]
        elevations = [0.]
        road_preview("road", points, elevations, (10., 0.), 0., 12., 1, 1)
        self.assertEqual(points, [(0., 0.)])
        self.assertEqual(elevations, [0.])


if __name__ == "__main__":
    unittest.main()
