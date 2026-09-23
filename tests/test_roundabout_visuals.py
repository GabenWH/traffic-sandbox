"""Roundabout road and island geometry stays shared across the map views."""

import unittest
from math import hypot, inf, nan

from models import Intersection, IntersectionKind


class RoundaboutVisualTests(unittest.TestCase):
    def test_custom_ring_radius_controls_every_circulating_arc(self) -> None:
        from city import CityMap, Terrain
        from mobility import VEHICLE_LAYER

        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)])
        city.add_road([(100, 0), (100, 200)])
        junction = city.standard_intersections[0]
        junction.kind = IntersectionKind.ROUNDABOUT
        junction.roundabout_ring_radius = 42.0
        city.rebuild_mobility_network()

        graph = city.mobility.layers[VEHICLE_LAYER].graph
        arcs = [
            transition.edge.value
            for node in graph.nodes
            for transition in graph.transitions_from(node)
            if transition.edge.kind == "lane"
            and transition.edge.value.road_id == f"roundabout:{junction.id}"
        ]

        self.assertGreater(len(arcs), 0)
        for arc in arcs:
            self.assertGreater(len(arc.points), 2)
            for point in arc.points:
                self.assertAlmostEqual(
                    hypot(point[0] - junction.position[0], point[1] - junction.position[1]),
                    42.0,
                )

    def test_car_path_leaves_clearance_inside_the_roundabout(self) -> None:
        from roundabouts import island_radius, outer_band_width, ring_radius

        junction = Intersection("r", (100, 100), radius=24, kind=IntersectionKind.ROUNDABOUT)

        # A six-foot-wide car following the centerline retains one foot of space.
        clearance = ring_radius(junction) - island_radius(junction) - 3

        self.assertGreaterEqual(clearance, 1)

        junction = Intersection("r", (100, 100), radius=60, kind=IntersectionKind.ROUNDABOUT)
        self.assertEqual(ring_radius(junction), 40.2)
        self.assertEqual(island_radius(junction), 30.0)
        self.assertEqual(outer_band_width(junction), 3.0)

        junction.roundabout_ring_radius = 42.0
        junction.roundabout_island_radius = 28.0
        junction.roundabout_outer_band_width = 0.0
        self.assertEqual(ring_radius(junction), 42.0)
        self.assertEqual(island_radius(junction), 28.0)
        self.assertEqual(outer_band_width(junction), 0.0)

    def test_roundabout_dimensions_reject_invalid_geometry(self) -> None:
        from roundabouts import validate_roundabout_dimensions

        junction = Intersection("r", (100, 100), radius=60, kind=IntersectionKind.ROUNDABOUT)
        validate_roundabout_dimensions(junction)

        invalid_dimensions = (
            ("radius", nan),
            ("roundabout_ring_radius", inf),
            ("roundabout_island_radius", -1.0),
            ("roundabout_outer_band_width", -1.0),
            ("roundabout_ring_radius", 61.0),
            ("roundabout_island_radius", 41.0),
            ("roundabout_island_radius", 36.3),
        )
        for field, value in invalid_dimensions:
            with self.subTest(field=field, value=value):
                candidate = Intersection("r", (100, 100), radius=60, kind=IntersectionKind.ROUNDABOUT)
                setattr(candidate, field, value)
                with self.assertRaises(ValueError):
                    validate_roundabout_dimensions(candidate)

    def test_roundabout_dimensions_reject_zero_island_radius(self) -> None:
        from roundabouts import validate_roundabout_dimensions

        junction = Intersection("r", (100, 100), radius=60, kind=IntersectionKind.ROUNDABOUT)
        junction.roundabout_island_radius = 0.0

        with self.assertRaises(ValueError):
            validate_roundabout_dimensions(junction)


if __name__ == "__main__":
    unittest.main()
