"""Roundabout road and island geometry stays shared across the map views."""

import unittest

from models import Intersection, IntersectionKind


class RoundaboutVisualTests(unittest.TestCase):
    def test_car_path_leaves_clearance_inside_the_roundabout(self) -> None:
        from roundabouts import island_radius, ring_radius

        junction = Intersection("r", (100, 100), radius=24, kind=IntersectionKind.ROUNDABOUT)

        # A six-foot-wide car following the centerline retains one foot of space.
        clearance = ring_radius(junction) - island_radius(junction) - 3

        self.assertGreaterEqual(clearance, 1)


if __name__ == "__main__":
    unittest.main()
