"""Tests for model-owned city inspection data and road hit testing."""

import unittest
import random

from city import CityMap, Terrain
from simulation import TrafficSimulation
from ui.interactions import InteractionMixin
from ui_tools.tools.inspect_tool import inspection_rows
from traffic_testbed import TestTrafficSimulation


class CityInspectorTests(unittest.TestCase):
    def test_constructed_road_is_hit_tested_and_rendered_as_inspection_rows(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)], name="Main Street")

        class Host(InteractionMixin):
            city_map = city
            camera_zoom = 1.0
            unit_system = "imperial"
            simulation = TrafficSimulation()

        host = Host()

        self.assertIs(host.road_at((50, 10)), road)
        title, rows = inspection_rows(host, road)
        values = {row.label: row.value for row in rows}
        self.assertEqual(title, "Road")
        self.assertEqual(values["Name"], "Main Street")
        self.assertEqual(values["Total width"], "24 ft")
        lane_rows = [row for row in rows if row.target in road.lanes]
        self.assertEqual([row.target for row in lane_rows], road.lanes)

        lane_title, lane_rows = inspection_rows(host, road.lanes[0])
        parent_row = next(row for row in lane_rows if row.label == "Parent road")
        self.assertEqual(lane_title, "Lane")
        self.assertIs(parent_row.target, road)

    def test_intersection_is_hit_tested_and_links_to_road_segments(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)], name="East West")
        city.add_road([(50, 0), (50, 100)], name="North South")

        class Host(InteractionMixin):
            city_map = city
            camera_zoom = 1.0
            unit_system = "imperial"
            simulation = TrafficSimulation()

        host = Host()
        intersection = city.standard_intersections[0]

        self.assertIs(host.intersection_at((50, 50)), intersection)
        title, rows = inspection_rows(host, intersection)
        links = [row.target for row in rows if row.target is not None]
        self.assertEqual(title, "Intersection")
        self.assertEqual(links, intersection.connected_roads)

        control_row = next(row for row in rows if row.label == "All-way stop")
        self.assertEqual(control_row.value, "no")
        assert control_row.apply is not None
        control_row.apply("yes")
        self.assertTrue(intersection.is_all_way_stop)

    def test_cul_de_sac_is_hit_tested_and_reports_its_turnaround(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)], name="Dead End")

        class Host(InteractionMixin):
            city_map = city
            camera_zoom = 1.0
            unit_system = "imperial"
            simulation = TrafficSimulation()

        host = Host()
        cul_de_sac = host.cul_de_sac_at((0, 0))

        assert cul_de_sac is not None
        title, rows = inspection_rows(host, cul_de_sac)
        values = {row.label: row.value for row in rows}
        self.assertEqual(title, "Cul-de-sac")
        self.assertEqual(values["Lane connections"], "1")
        self.assertEqual(cul_de_sac.connected_roads, [road])

    def test_routed_test_car_exposes_brain_state_in_inspector(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 0), (200, 0)])
        traffic = TestTrafficSimulation(rng=random.Random(1))
        car = traffic.spawn_car(city, city.cul_de_sacs[0], city.cul_de_sacs[1])
        assert car is not None

        class Host:
            city_map = city
            test_traffic = traffic
            unit_system = "imperial"
            simulation = TrafficSimulation()
            selected_lane = simulation.lanes[0]

        title, rows = inspection_rows(Host(), car)
        values = {row.label: row.value for row in rows}

        self.assertEqual(title, "Routed test car")
        self.assertEqual(values["Brain state"], "cruising")
        self.assertEqual(values["Turn signal"], "none")
        self.assertIn("Desired speed", values)

        class InteractiveHost(InteractionMixin):
            city_map = city
            test_traffic = traffic
            camera_zoom = 1.0

        self.assertIs(InteractiveHost().routed_test_car_at(car.position), car)
        self.assertIsNone(InteractiveHost().routed_test_car_at((1000.0, 1000.0)))


if __name__ == "__main__":
    unittest.main()
