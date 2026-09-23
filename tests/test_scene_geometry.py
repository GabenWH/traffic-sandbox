"""Road deck coordinates used by the 3D scene."""

import unittest

from models import Road
from ui.scene_geometry import road_deck_quads
from ui.scene_geometry import roundabout_deck_quads


class SceneGeometryTests(unittest.TestCase):
    def test_roundabout_geometry_has_road_ring_and_raised_central_island(self) -> None:
        from models import Intersection, IntersectionKind
        junction = Intersection("r", (100, 100), radius=24, kind=IntersectionKind.ROUNDABOUT, elevation=3)
        road, island = roundabout_deck_quads(junction)
        self.assertEqual(len(road), 32)
        self.assertEqual(len(island), 32)
        self.assertTrue(all(vertex[2] == 3 for quad in road for vertex in quad))
        self.assertTrue(all(vertex[2] > 3 for quad in island for vertex in quad))
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
