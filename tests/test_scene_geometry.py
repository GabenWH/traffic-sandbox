"""Road deck coordinates used by the 3D scene."""

import unittest
from math import hypot

from models import Road
from ui.scene_geometry import road_deck_quads
from ui.scene_geometry import roundabout_deck_quads


class SceneGeometryTests(unittest.TestCase):
    def test_roundabout_geometry_uses_custom_island_and_outer_band(self) -> None:
        from models import Intersection, IntersectionKind

        junction = Intersection("r", (100, 100), radius=24, kind=IntersectionKind.ROUNDABOUT)
        junction.roundabout_ring_radius = 18.0
        junction.roundabout_island_radius = 9.0
        junction.roundabout_outer_band_width = 5.0

        deck, band, island = roundabout_deck_quads(junction)
        island_radii = {
            round(hypot(vertex[0] - junction.position[0], vertex[1] - junction.position[1]), 6)
            for quad in island for vertex in quad
        }
        band_radii = {
            round(hypot(vertex[0] - junction.position[0], vertex[1] - junction.position[1]), 6)
            for quad in band for vertex in quad
        }

        self.assertEqual(len(deck), 32)
        self.assertEqual(island_radii, {0.0, 9.0})
        self.assertEqual(max(band_radii), junction.radius + 5.0)

    def test_zero_width_roundabout_band_is_degenerate_and_keeps_island(self) -> None:
        from models import Intersection, IntersectionKind

        junction = Intersection("r", (100, 100), radius=24, kind=IntersectionKind.ROUNDABOUT)
        junction.roundabout_ring_radius = 18.0
        junction.roundabout_island_radius = 9.0
        junction.roundabout_outer_band_width = 0.0

        _, band, island = roundabout_deck_quads(junction)
        band_radii = {
            round(hypot(vertex[0] - 100, vertex[1] - 100), 6)
            for quad in band for vertex in quad
        }
        island_radii = {
            round(hypot(vertex[0] - 100, vertex[1] - 100), 6)
            for quad in island for vertex in quad
        }

        self.assertEqual(len(band), 32)
        self.assertEqual(band_radii, {24.0})
        self.assertEqual(island_radii, {0.0, 9.0})

    def test_roundabout_geometry_has_road_ring_and_raised_central_island(self) -> None:
        from models import Intersection, IntersectionKind
        approach = Road(
            "approach", "Approach", [(0, 100), (100, 100)], elevations=[0, 5],
        )
        junction = Intersection(
            "r", (100, 100), connected_roads=[approach], radius=24,
            kind=IntersectionKind.ROUNDABOUT, elevation=3,
        )
        deck, outer_band, island = roundabout_deck_quads(junction)
        self.assertEqual(len(deck), 32)
        self.assertEqual(len(outer_band), 32)
        self.assertEqual(len(island), 32)
        # Keep the apron just below connected road ends so approach decks remain visible.
        self.assertTrue(all(vertex[2] == 4.98 for quad in deck for vertex in quad))
        self.assertTrue(all((100, 100, 4.98) in quad for quad in deck))
        self.assertTrue(all(
            {round(((vertex[0] - 100) ** 2 + (vertex[1] - 100) ** 2) ** 0.5, 6)
             for vertex in quad} == {24, 27}
            for quad in outer_band
        ))
        self.assertTrue(all(
            round(((vertex[0] - 100) ** 2 + (vertex[1] - 100) ** 2) ** 0.5, 6) in {0, 12}
            for quad in island for vertex in quad
        ))
        self.assertTrue(all(vertex[2] > 4.98 for quad in island for vertex in quad))
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
