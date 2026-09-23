"""Road deck coordinates used by the 3D scene."""

import unittest

from models import Road
from ui.scene_geometry import road_deck_quads


class SceneGeometryTests(unittest.TestCase):
    def test_ramp_deck_follows_vertex_elevations(self) -> None:
        road = Road("r", "Ramp", [(0, 0), (100, 0)], elevations=[0, 20])

        quads = road_deck_quads(road)

        self.assertEqual(quads, [
            ((0, -12, 0), (0, 12, 0), (100, 12, 20), (100, -12, 20)),
        ])

    def test_turning_road_keeps_each_segment_road_width(self) -> None:
        road = Road(
            "r", "Turn", [(0, 0), (100, 0), (100, 100)],
            elevations=[0, 0, 20],
        )

        quads = road_deck_quads(road)

        self.assertEqual(len(quads), 2)
        self.assertEqual(quads[1], (
            (112, 0, 0), (88, 0, 0), (88, 100, 20), (112, 100, 20),
        ))


if __name__ == "__main__":
    unittest.main()
