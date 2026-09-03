"""Tests for authored road geometry and the road/lane hierarchy."""

from math import dist
import unittest

from city import CityMap, Terrain
from models import (
    CityObject,
    ControlDefinition,
    ControlType,
    Intersection,
    IntersectionKind,
    ManeuverType,
    RoadEnd,
    RoadPortFlow,
)


class RoadConstructionTests(unittest.TestCase):
    def test_add_road_builds_forward_and_reverse_lane_children(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))

        road = city.add_road([(0, 0), (100, 0)], name="Main Street")

        self.assertIs(city.roads[0], road)
        self.assertEqual(road.width, 24.0)
        self.assertEqual(len(road.lanes), 2)
        self.assertEqual(
            [(port.end, port.flow) for port in road.route_inputs],
            [
                (RoadEnd.START, RoadPortFlow.INPUT),
                (RoadEnd.END, RoadPortFlow.INPUT),
            ],
        )
        self.assertEqual(
            [(port.end, port.flow) for port in road.route_outputs],
            [
                (RoadEnd.START, RoadPortFlow.OUTPUT),
                (RoadEnd.END, RoadPortFlow.OUTPUT),
            ],
        )
        forward, reverse = road.lanes
        self.assertEqual((forward.direction, forward.road_id), ("forward", road.id))
        self.assertEqual((reverse.direction, reverse.road_id), ("reverse", road.id))
        self.assertAlmostEqual(forward.points[0][0], 19.0788, places=3)
        self.assertAlmostEqual(forward.points[-1][0], 80.9212, places=3)
        self.assertEqual([point[1] for point in forward.points], [6.0, 6.0])
        self.assertAlmostEqual(reverse.points[0][0], forward.points[-1][0])
        self.assertAlmostEqual(reverse.points[-1][0], forward.points[0][0])
        self.assertEqual([point[1] for point in reverse.points], [-6.0, -6.0])
        self.assertEqual(len(city.cul_de_sacs), 2)
        self.assertTrue(all(cul_de_sac.radius == 20.0 for cul_de_sac in city.cul_de_sacs))
        self.assertTrue(all(
            len(cul_de_sac.lane_connections) == 1
            for cul_de_sac in city.cul_de_sacs
        ))
        self.assertIsInstance(road, CityObject)
        self.assertEqual(road.inspection_title, "Road")
        self.assertEqual(
            {item.label: item.value for item in road.inspection_properties()}["Lanes"],
            2,
        )
        self.assertEqual(road.distance_to((50, 10)), 10.0)

    def test_add_road_rejects_degenerate_polylines(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))

        with self.assertRaises(ValueError):
            city.add_road([(20, 20)])
        with self.assertRaises(ValueError):
            city.add_road([(20, 20), (20, 20)])

    def test_add_road_removes_trees_overlapping_its_paved_footprint(self) -> None:
        city = CityMap(terrain=Terrain(trees=[
            (50, 0),
            (50, 23),
            (50, 24),
            (150, 0),
        ]))

        city.add_road([(0, 0), (100, 0)])

        self.assertEqual(city.terrain.trees, [(50, 24), (150, 0)])

    def test_cul_de_sac_footprint_also_clears_trees(self) -> None:
        city = CityMap(terrain=Terrain(trees=[(0, 30), (0, 32)]))

        city.add_road([(0, 0), (100, 0)])

        self.assertEqual(city.terrain.trees, [(0, 32)])

    def test_one_way_road_endpoints_do_not_create_cul_de_sacs(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))

        road = city.add_road(
            [(0, 0), (100, 0)],
            forward_lane_count=1,
            reverse_lane_count=0,
        )

        self.assertEqual(city.cul_de_sacs, [])
        self.assertEqual(road.lanes[0].points, [(0.0, 0.0), (100.0, 0.0)])

    def test_multi_lane_direction_uses_one_geometric_port_across_its_width(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road(
            [(0, 0), (100, 0)],
            forward_lane_count=2,
            reverse_lane_count=0,
        )

        self.assertEqual(len(road.route_inputs), 1)
        self.assertEqual(len(road.route_outputs), 1)
        road_input = road.route_inputs[0]
        road_output = road.route_outputs[0]
        self.assertEqual(road_input.position, (0.0, 0.0))
        self.assertEqual(road_output.position, (100.0, 0.0))
        self.assertEqual(road_input.heading, (1.0, 0.0))
        self.assertEqual(road_output.heading, (1.0, 0.0))
        self.assertEqual(road_input.width, 24.0)
        self.assertEqual(road_input.lanes, tuple(road.lanes))

    def test_cul_de_sac_is_a_generic_multi_road_intersection(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        main_road = city.add_road([(0, 0), (200, 0)], name="Main road")
        original = next(
            intersection for intersection in city.cul_de_sacs
            if intersection.position == (0.0, 0.0)
        )

        driveway = city.add_road(
            [(0, 100), (0, 0)],
            name="Driveway",
            forward_lane_count=1,
            reverse_lane_count=0,
        )

        cul_de_sac = next(
            intersection for intersection in city.cul_de_sacs
            if intersection.position == (0.0, 0.0)
        )
        self.assertIsInstance(cul_de_sac, Intersection)
        self.assertEqual(cul_de_sac.kind, IntersectionKind.CUL_DE_SAC)
        self.assertEqual(cul_de_sac.id, original.id)
        self.assertEqual(cul_de_sac.connected_roads, [main_road, driveway])
        self.assertTrue(any(
            connection.source_output.road is driveway
            and connection.destination_input.road is main_road
            for connection in cul_de_sac.lane_connections
        ))

    def test_loading_road_geometry_does_not_modify_saved_trees(self) -> None:
        city = CityMap(terrain=Terrain(trees=[(50, 0)]))

        city.add_road([(0, 0), (100, 0)], create_intersections=False)

        self.assertEqual(city.terrain.trees, [(50, 0)])

    def test_road_split_preserves_the_start_segment_identity(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (50, 0), (100, 0)], name="Main Street")
        original_lane_ids = [lane.id for lane in road.lanes]

        first, second = road.split((75, 0))

        self.assertEqual(first.centerline, [(0.0, 0.0), (50.0, 0.0), (75.0, 0.0)])
        self.assertEqual(second.centerline, [(75.0, 0.0), (100.0, 0.0)])
        self.assertEqual(first.id, road.id)
        self.assertNotEqual(second.id, road.id)
        self.assertEqual([lane.id for lane in first.lanes], original_lane_ids)

    def test_crossing_roads_split_and_create_an_explicit_intersection(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)], name="East West")

        city.add_road([(50, 0), (50, 100)], name="North South")

        self.assertEqual(len(city.roads), 4)
        self.assertEqual(len(city.standard_intersections), 1)
        intersection = city.standard_intersections[0]
        self.assertEqual(intersection.position, (50.0, 50.0))
        self.assertEqual(len(intersection.connected_roads), 4)
        self.assertEqual(intersection.radius, 24.0)
        self.assertTrue(all(intersection.position in road.centerline for road in city.roads))

        self.assertEqual(len(intersection.incoming_ports()), 4)
        self.assertEqual(len(intersection.outgoing_ports()), 4)
        self.assertEqual(len(intersection.lane_connections), 12)
        self.assertEqual(
            {connection.maneuver.kind for connection in intersection.lane_connections},
            {ManeuverType.LEFT_TURN, ManeuverType.RIGHT_TURN, ManeuverType.THROUGH},
        )
        self.assertTrue(all(
            connection.source_output.road is not connection.destination_input.road
            for connection in intersection.lane_connections
        ))
        through_connections = [
            connection for connection in intersection.lane_connections
            if connection.maneuver.kind is ManeuverType.THROUGH
        ]
        for connection in through_connections:
            direction = connection.source_output.heading
            self.assertTrue(all(
                (end[0] - start[0]) * direction[0]
                + (end[1] - start[1]) * direction[1] >= -1e-9
                for start, end in zip(connection.path, connection.path[1:])
            ))

    def test_upstream_split_retains_control_on_unchanged_geometric_ports(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (400, 100)], name="Main")
        city.add_road([(300, 0), (300, 200)], name="Junction road")
        junction = next(
            item for item in city.standard_intersections
            if item.position == (300.0, 100.0)
        )
        controlled = next(
            connection for connection in junction.lane_connections
            if connection.source_output.road.name == "Main"
        )
        controlled.control = ControlDefinition(ControlType.STOP)
        movement_geometry = (
            controlled.source_output.geometric_key,
            controlled.destination_input.geometric_key,
        )

        city.add_road([(150, 0), (150, 200)], name="Upstream crossing")

        rebuilt = next(
            connection for connection in junction.lane_connections
            if (
                connection.source_output.geometric_key,
                connection.destination_input.geometric_key,
            ) == movement_geometry
        )
        self.assertEqual(rebuilt.control.kind, ControlType.STOP)

    def test_standard_intersection_can_toggle_all_way_stop(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)])
        city.add_road([(50, 0), (50, 100)])
        intersection = city.standard_intersections[0]

        intersection.set_all_way_stop(True)
        self.assertTrue(intersection.is_all_way_stop)
        self.assertTrue(all(
            connection.control.kind is ControlType.STOP
            for connection in intersection.lane_connections
        ))

        intersection.set_all_way_stop(False)
        self.assertFalse(intersection.is_all_way_stop)
        self.assertTrue(all(
            connection.control.kind is ControlType.UNCONTROLLED
            for connection in intersection.lane_connections
        ))

    def test_cul_de_sac_rejects_all_way_stop(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (100, 0)])

        with self.assertRaisesRegex(ValueError, "standard intersection"):
            city.cul_de_sacs[0].set_all_way_stop(True)

    def test_three_crossing_roads_create_one_six_way_intersection(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        centre = (50.0, 50.0)
        city.add_road([(0, 50), (100, 50)], name="East West")
        city.add_road([(50, 0), (50, 100)], name="North South")

        city.add_road([(0, 0), (100, 100)], name="Diagonal")

        self.assertEqual(len(city.standard_intersections), 1)
        intersection = city.standard_intersections[0]
        self.assertEqual(intersection.position, centre)
        self.assertEqual(len(city.roads), 6)
        self.assertEqual(len(intersection.connected_roads), 6)
        self.assertEqual(
            {road.name for road in intersection.connected_roads},
            {"East West", "North South", "Diagonal"},
        )
        self.assertEqual(
            len({road.id for road in intersection.connected_roads}),
            6,
        )
        self.assertTrue(all(
            centre in (road.centerline[0], road.centerline[-1])
            for road in intersection.connected_roads
        ))

    def test_nearby_hand_drawn_crossings_coalesce_into_six_way_intersection(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        centre = (50.0, 50.0)
        city.add_road([(0, 50), (100, 50)], name="East West")
        city.add_road([(50, 0), (50, 100)], name="North South")

        city.add_road([(0, 2), (100, 100)], name="Hand-drawn diagonal")

        self.assertEqual(len(city.standard_intersections), 1)
        intersection = city.standard_intersections[0]
        self.assertEqual(intersection.position, centre)
        self.assertEqual(len(city.roads), 6)
        self.assertEqual(len(intersection.connected_roads), 6)
        self.assertTrue(all(
            min(dist(centre, road.centerline[0]), dist(centre, road.centerline[-1]))
            <= 12.0
            for road in intersection.connected_roads
        ))

    def test_new_road_colliding_with_intersection_footprint_reuses_junction(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)], name="East West")
        city.add_road([(100, 0), (100, 200)], name="North South")

        city.add_road([(40, 140), (160, 140)], name="Nearby road")

        self.assertEqual(len(city.standard_intersections), 1)
        intersection = city.standard_intersections[0]
        nearby_segments = [road for road in city.roads if road.name == "Nearby road"]
        self.assertEqual(len(nearby_segments), 2)
        self.assertTrue(all(
            intersection.position in (road.centerline[0], road.centerline[-1])
            for road in nearby_segments
        ))
        self.assertEqual(len(intersection.connected_roads), 6)

    def test_new_road_endpoint_inside_intersection_footprint_snaps_to_junction(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)], name="East West")
        city.add_road([(100, 0), (100, 200)], name="North South")

        spur = city.add_road([(40, 115), (85, 115)], name="Spur")

        self.assertEqual(len(city.standard_intersections), 1)
        self.assertEqual(spur.centerline[-1], (100.0, 100.0))
        self.assertIn(spur, city.standard_intersections[0].connected_roads)

    def test_road_outside_existing_junction_footprint_creates_new_intersection(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)], name="East West")
        city.add_road([(100, 0), (100, 200)], name="North South")

        city.add_road([(40, 160), (160, 160)], name="Far road")

        self.assertEqual(len(city.standard_intersections), 2)
        self.assertEqual(
            {intersection.position for intersection in city.standard_intersections},
            {(100.0, 100.0), (100.0, 160.0)},
        )


if __name__ == "__main__":
    unittest.main()
