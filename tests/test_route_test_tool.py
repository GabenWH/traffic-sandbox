"""Headless checks for the interactive constructed-road route tool."""

import unittest

from city import CityMap, Terrain
from ui_tools.tools.route_test_tool import (
    RouteTestTool,
    constructed_lane_at,
    constructed_lane_position_at,
    constructed_junction_at,
    route_polylines,
)
from mobility import nearest_lane_position
from models import polyline_length


class RouteTestToolTests(unittest.TestCase):
    def test_lane_selection_survives_building_another_network_through_it(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (300, 100)], name="First east west")
        city.add_road([(100, 0), (100, 300)], name="First north south")
        city.add_road([(0, 200), (300, 200)], name="Second east west")
        city.add_road([(200, 0), (200, 300)], name="Second north south")

        for road in city.roads:
            for lane in road.lanes:
                for point in (*lane.points, (150.0, 150.0)):
                    selected, _distance = nearest_lane_position(lane, point)
                    self.assertGreaterEqual(selected.distance, 0.0)
                    self.assertLessEqual(
                        selected.distance,
                        polyline_length(lane.points),
                    )

    def test_constructed_lane_hit_testing_chooses_nearest_direction(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)])
        forward = next(lane for lane in road.lanes if lane.direction == "forward")
        reverse = next(lane for lane in road.lanes if lane.direction == "reverse")

        self.assertIs(constructed_lane_at(city, forward.points[0]), forward)
        self.assertIs(constructed_lane_at(city, reverse.points[0]), reverse)
        self.assertIsNone(constructed_lane_at(city, (50, 100)))
        selected = constructed_lane_position_at(city, (50, 6))
        assert selected is not None
        self.assertEqual(selected.point, (50.0, 6.0))

    def test_two_lane_selections_find_and_extract_an_intersection_route(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)], name="East West")
        city.add_road([(50, 0), (50, 100)], name="North South")
        west = next(road for road in city.roads if road.centerline[0] == (0.0, 50.0))
        east = next(road for road in city.roads if road.centerline[-1] == (100.0, 50.0))
        start = next(lane for lane in west.lanes if lane.direction == "forward")
        destination = next(lane for lane in east.lanes if lane.direction == "forward")

        class Host:
            city_map = city
            unit_system = "imperial"

        tool = RouteTestTool(Host())
        tool.select_lane(start)
        tool.select_lane(destination)

        assert tool.route is not None
        self.assertEqual(
            [kind for kind, _points in route_polylines(tool.route)],
            ["lane", "lane_connection", "lane"],
        )
        self.assertIn("Route found", tool.message)

        tool.select_lane(destination)
        self.assertIs(tool.start_lane, destination)
        self.assertIsNone(tool.destination_lane)
        self.assertIsNone(tool.route)

    def test_disconnected_one_way_selection_reports_no_route(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        first = city.add_road(
            [(0, 0), (100, 0)], forward_lane_count=1, reverse_lane_count=0,
        )
        second = city.add_road(
            [(0, 100), (100, 100)], forward_lane_count=1, reverse_lane_count=0,
        )

        class Host:
            city_map = city
            unit_system = "imperial"

        tool = RouteTestTool(Host())
        tool.select_lane(first.lanes[0])
        tool.select_lane(second.lanes[0])

        self.assertIsNone(tool.route)
        self.assertIn("No directed route", tool.message)

    def test_precise_positions_limit_the_drawn_route_to_clicked_length(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)])
        lane = next(lane for lane in road.lanes if lane.direction == "forward")
        start, _ = nearest_lane_position(lane, (60, 6))
        destination, _ = nearest_lane_position(lane, (160, 6))

        class Host:
            city_map = city
            unit_system = "imperial"

        tool = RouteTestTool(Host())
        tool.select_position(start)
        tool.select_position(destination)

        assert tool.route is not None
        self.assertAlmostEqual(tool.route.cost, 100)
        geometry = route_polylines(tool.route)
        self.assertEqual(geometry, (("lane", [start.point, destination.point]),))

    def test_clicking_junction_footprints_selects_the_junction_itself(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)], name="East West")
        city.add_road([(100, 0), (100, 200)], name="North South")
        intersection = city.standard_intersections[0]
        cul_de_sac = next(
            item for item in city.cul_de_sacs if item.position == (0.0, 100.0)
        )

        self.assertIs(constructed_junction_at(city, intersection.position), intersection)
        self.assertIs(constructed_junction_at(city, cul_de_sac.position), cul_de_sac)

        class Host:
            city_map = city
            unit_system = "imperial"

        tool = RouteTestTool(Host())
        tool.select_endpoint(cul_de_sac)
        tool.select_endpoint(intersection)

        self.assertIs(tool.start_endpoint, cul_de_sac)
        self.assertIs(tool.destination_endpoint, intersection)
        self.assertIsNotNone(tool.route)


if __name__ == "__main__":
    unittest.main()
