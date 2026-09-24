"""Road access points for the virtual construction provider and buildings."""

import unittest

from city import Building, CityMap, Parcel, Terrain
from construction import (
    UnlimitedConstructionProvider,
    building_access_points,
    distance_from_parcel,
    provider_access_points,
)
from mobility import LanePosition
from models import IntersectionKind


class ConstructionAccessTests(unittest.TestCase):
    def city(self) -> CityMap:
        return CityMap(width=500, height=300, terrain=Terrain(trees=[]))

    def test_two_way_west_edge_gate_uses_existing_cul_de_sac(self) -> None:
        city = self.city()
        city.add_road([(0, 100), (300, 100)])
        gate = next(
            intersection for intersection in city.intersections
            if intersection.position == (0.0, 100.0)
        )

        self.assertEqual(gate.kind, IntersectionKind.CUL_DE_SAC)
        self.assertIn(gate, provider_access_points(city))
        self.assertIn(gate, UnlimitedConstructionProvider().access_points(city))

    def test_one_way_inbound_west_edge_gate_is_a_lane_position(self) -> None:
        city = self.city()
        road = city.add_road(
            [(0, 100), (300, 100)],
            forward_lane_count=1,
            reverse_lane_count=0,
        )

        gates = provider_access_points(city)

        self.assertTrue(any(
            isinstance(gate, LanePosition)
            and gate.lane in road.lanes
            and gate.lane.direction == "forward"
            and gate.point[0] == 0
            for gate in gates
        ))

    def test_building_access_covers_lanes_on_both_sides_and_rejects_far_buildings(self) -> None:
        city = self.city()
        city.add_road([(0, 100), (300, 100)])
        south = Building("South", Parcel(50, 112, 40, 30))
        north = Building("North", Parcel(50, 58, 40, 30))
        far = Building("Far", Parcel(50, 250, 40, 30))

        south_access = building_access_points(city, south)
        north_access = building_access_points(city, north)

        self.assertTrue(south_access)
        self.assertTrue(north_access)
        self.assertEqual(
            {position.lane.direction for position in (*south_access, *north_access)},
            {"forward", "reverse"},
        )
        self.assertEqual(building_access_points(city, far), ())
        self.assertTrue(all(
            distance_from_parcel(building.parcel, position.point) <= 24
            for building, positions in ((south, south_access), (north, north_access))
            for position in positions
        ))

    def test_distance_from_parcel_measures_from_rectangle_edges(self) -> None:
        parcel = Parcel(10, 20, 30, 40)

        self.assertEqual(distance_from_parcel(parcel, (25, 35)), 0)
        self.assertEqual(distance_from_parcel(parcel, (40, 20)), 0)
        self.assertAlmostEqual(distance_from_parcel(parcel, (50, 70)), 10 * 2**0.5)

    def test_provider_with_no_west_edge_road_has_no_access(self) -> None:
        self.assertEqual(provider_access_points(self.city()), ())
        self.assertEqual(
            UnlimitedConstructionProvider().access_points(self.city()),
            (),
        )


if __name__ == "__main__":
    unittest.main()
