"""Tests for model-owned city inspection data and road hit testing."""

import unittest
import random
from types import SimpleNamespace

from city import CityMap, Terrain
from models import IntersectionKind
from simulation import TrafficSimulation
from ui.interactions import InteractionMixin
from ui_tools.tools import inspect_tool
from ui_tools.tools.inspect_tool import inspection_rows
from traffic_testbed import TestTrafficSimulation


class CityInspectorTests(unittest.TestCase):
    def test_metric_ring_edit_converts_units_and_rebuilds_after_clearing_cars(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)])
        city.add_road([(100, 0), (100, 200)])
        junction = city.standard_intersections[0]

        class Traffic:
            def __init__(self):
                self.cars = [SimpleNamespace(item=101, signal_items=[102, None, 103])]

            def clear_cars(self):
                cars, self.cars = self.cars, []
                return cars

        class Canvas:
            def __init__(self):
                self.deleted = []

            def delete(self, item):
                self.deleted.append(item)

        class Host:
            unit_system = "metric"
            city_map = city

            def __init__(self):
                self.test_traffic = Traffic()
                self.canvas = Canvas()
                self.redraw_count = 0

            def redraw_world(self):
                self.redraw_count += 1

        host = Host()
        rebuild = city.rebuild_mobility_network
        rebuild_calls = []

        def counted_rebuild():
            rebuild_calls.append(True)
            rebuild()

        city.rebuild_mobility_network = counted_rebuild
        {row.label: row for row in inspection_rows(host, junction)[1]}["Junction type"].apply("roundabout")
        host.test_traffic.cars = [SimpleNamespace(item=101, signal_items=[102, None, 103])]
        host.canvas.deleted.clear()
        host.redraw_count = 0
        rebuild_calls.clear()

        ring_row = {row.label: row for row in inspection_rows(host, junction)[1]}["Circulating radius"]
        self.assertAlmostEqual(float(ring_row.value), 12.25296, places=3)
        ring_row.apply("15.24")
        self.assertAlmostEqual(junction.roundabout_ring_radius, 50.0)
        self.assertEqual(len(rebuild_calls), 1)
        self.assertEqual(host.redraw_count, 1)
        self.assertEqual(host.canvas.deleted, [101, 102, 103])
        self.assertEqual(host.test_traffic.cars, [])

    def test_invalid_geometry_edits_preserve_values_and_do_not_refresh(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)])
        city.add_road([(100, 0), (100, 200)])
        junction = city.standard_intersections[0]

        class Host:
            unit_system = "metric"
            city_map = city

            def __init__(self):
                self.redraw_count = 0
                self.test_traffic = SimpleNamespace(clear_cars=lambda: self.fail_clear())

            def fail_clear(self):
                raise AssertionError("Invalid edit cleared cars")

            def redraw_world(self):
                self.redraw_count += 1

        host = Host()
        host.test_traffic = None
        {row.label: row for row in inspection_rows(host, junction)[1]}["Junction type"].apply("roundabout")
        host.test_traffic = SimpleNamespace(clear_cars=lambda: host.fail_clear())
        host.redraw_count = 0
        old_ring = junction.roundabout_ring_radius
        old_radius = junction.radius
        old_island = junction.roundabout_island_radius

        with self.assertRaises(ValueError):
            inspect_tool.set_intersection_trait(host, junction, "roundabout_ring_radius", "1")
        with self.assertRaises(ValueError):
            inspect_tool.set_intersection_trait(host, junction, "roundabout_island_radius", "20")
        with self.assertRaises(ValueError):
            inspect_tool.set_intersection_trait(host, junction, "radius", "1")
        with self.assertRaises(ValueError):
            inspect_tool.set_intersection_trait(host, junction, "radius", "nan")
        self.assertEqual(junction.roundabout_ring_radius, old_ring)
        self.assertEqual(junction.roundabout_island_radius, old_island)
        self.assertEqual(junction.radius_override, None)
        self.assertEqual(junction.radius, old_radius)
        self.assertEqual(host.redraw_count, 0)

    def test_island_and_band_edits_only_redraw(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)])
        city.add_road([(100, 0), (100, 200)])
        junction = city.standard_intersections[0]

        class Host:
            unit_system = "metric"
            city_map = city

            def __init__(self):
                self.redraw_count = 0
                self.test_traffic = SimpleNamespace(clear_cars=lambda: self.fail_clear())

            def fail_clear(self):
                raise AssertionError("Visual edit cleared cars")

            def redraw_world(self):
                self.redraw_count += 1

        host = Host()
        host.test_traffic = None
        {row.label: row for row in inspection_rows(host, junction)[1]}["Junction type"].apply("roundabout")
        host.test_traffic = SimpleNamespace(clear_cars=lambda: host.fail_clear())
        host.redraw_count = 0
        rebuild = city.rebuild_mobility_network
        def fail_rebuild():
            raise AssertionError("Visual edit rebuilt routes")
        city.rebuild_mobility_network = fail_rebuild

        inspect_tool.set_intersection_trait(host, junction, "roundabout_island_radius", "7.62")
        inspect_tool.set_intersection_trait(host, junction, "roundabout_outer_band_width", "0")
        self.assertAlmostEqual(junction.roundabout_island_radius, 25.0)
        self.assertEqual(junction.roundabout_outer_band_width, 0)
        self.assertEqual(host.redraw_count, 2)
        self.assertEqual(float({row.label: row for row in inspection_rows(host, junction)[1]}["Outer band width"].value), 0)
        city.rebuild_mobility_network = rebuild

    def test_intersection_geometry_rows_match_junction_kind(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)])
        city.add_road([(100, 0), (100, 200)])

        class Host:
            unit_system = "imperial"
            city_map = city

            def redraw_world(self):
                pass

        host = Host()
        junction = city.standard_intersections[0]
        _, rows = inspection_rows(host, junction)
        rows_by_label = {row.label: row for row in rows}
        self.assertIn("Junction radius", rows_by_label)
        self.assertEqual(rows_by_label["Junction radius"].editor, "text")
        self.assertIsNotNone(rows_by_label["Junction radius"].apply)
        self.assertEqual(rows_by_label["Junction type"].editor, "text")
        self.assertEqual(rows_by_label["All-way stop"].editor, "text")
        self.assertIsNone(rows_by_label["Lane connections"].editor)
        self.assertIsNone(rows_by_label["Connected segments"].apply)

        cul_de_sac = city.cul_de_sacs[0]
        _, rows = inspection_rows(host, cul_de_sac)
        rows_by_label = {row.label: row for row in rows}
        self.assertEqual(rows_by_label["Turnaround radius"].editor, "text")
        self.assertIsNotNone(rows_by_label["Turnaround radius"].apply)
        self.assertNotIn("Junction type", rows_by_label)

        rows_by_label["Turnaround radius"].apply(str(cul_de_sac.radius + 5))
        self.assertEqual(cul_de_sac.radius_override, cul_de_sac.radius)

        _, rows = inspection_rows(host, junction)
        {row.label: row for row in rows}["Junction type"].apply("roundabout")
        _, rows = inspection_rows(host, junction)
        rows_by_label = {row.label: row for row in rows}
        for label in ("Junction radius", "Circulating radius", "Island radius", "Outer band width"):
            with self.subTest(label=label):
                self.assertEqual(rows_by_label[label].editor, "text")
                self.assertIsNotNone(rows_by_label[label].apply)
        self.assertIsNone(rows_by_label["Lane connections"].editor)

    def test_roundabout_dimensions_survive_kind_changes_and_invalid_return_is_rejected(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)])
        city.add_road([(100, 0), (100, 200)])

        class Host:
            unit_system = "imperial"
            city_map = city

            def redraw_world(self):
                pass

        host = Host()
        junction = city.standard_intersections[0]

        def row(label):
            rows_by_label = {item.label: item for item in inspection_rows(host, junction)[1]}
            self.assertIn(label, rows_by_label)
            return rows_by_label[label]

        row("Junction type").apply("roundabout")
        row("Junction radius").apply("70")
        row("Circulating radius").apply("65")
        row("Island radius").apply("30")
        row("Outer band width").apply("0")
        row("Junction type").apply("standard")
        self.assertEqual(junction.kind, IntersectionKind.STANDARD)
        self.assertEqual((junction.roundabout_ring_radius, junction.roundabout_island_radius,
                          junction.roundabout_outer_band_width), (65, 30, 0))
        row("Junction type").apply("roundabout")
        self.assertEqual(junction.kind, IntersectionKind.ROUNDABOUT)
        self.assertEqual((junction.radius, junction.roundabout_ring_radius,
                          junction.roundabout_island_radius, junction.roundabout_outer_band_width),
                         (70, 65, 30, 0))

        row("Junction type").apply("standard")
        row("Junction radius").apply("25")
        with self.assertRaises(ValueError):
            row("Junction type").apply("roundabout")
        self.assertEqual(junction.kind, IntersectionKind.STANDARD)
        self.assertEqual(junction.radius, 25)

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

        self.assertEqual(title, "Road car")
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
