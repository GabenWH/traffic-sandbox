"""Headless tests for junction-generated routed traffic."""

import random
import unittest
from math import dist

from city import CityMap, Terrain
from traffic_testbed import TestTrafficSimulation as TrafficTestbed
from ui.renderer import RendererMixin
from ui_tools.tools.test_traffic_tool import TestTrafficTool as TrafficTool


class TrafficTestbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.city = CityMap(terrain=Terrain(trees=[]))
        self.city.add_road([(0, 100), (400, 100)], name="East West")
        self.city.add_road([(200, 0), (200, 200)], name="North South")
        self.west = next(
            item for item in self.city.cul_de_sacs
            if item.position == (0.0, 100.0)
        )
        self.east = next(
            item for item in self.city.cul_de_sacs
            if item.position == (400.0, 100.0)
        )

    def test_selected_junctions_toggle_as_combined_sources_and_sinks(self) -> None:
        traffic = TrafficTestbed(rng=random.Random(1))

        self.assertTrue(traffic.toggle_junction(self.west))
        self.assertTrue(traffic.toggle_junction(self.east))
        self.assertEqual(traffic.active_junctions(self.city), [self.west, self.east])
        self.assertFalse(traffic.toggle_junction(self.west))
        self.assertEqual(traffic.active_junctions(self.city), [self.east])

    def test_spawns_a_car_over_port_based_route_geometry(self) -> None:
        traffic = TrafficTestbed(rng=random.Random(2))

        car = traffic.spawn_car(self.city, self.west, self.east)

        assert car is not None
        self.assertIs(car.route.edges[0].value, self.west)
        self.assertIs(car.route.edges[-1].value, self.east)
        self.assertGreater(car.total_length, 0)
        self.assertEqual(car.position, car.points[0])
        self.assertIn(car, traffic.cars)

    def test_spawn_is_refused_when_the_first_route_link_is_occupied(self) -> None:
        traffic = TrafficTestbed(spawn_interval=1000.0, rng=random.Random(20))

        first = traffic.spawn_car(self.city, self.west, self.east)
        blocked = traffic.spawn_car(self.city, self.west, self.east)

        self.assertIsNotNone(first)
        self.assertIsNone(blocked)
        self.assertEqual(len(traffic.cars), 1)

    def test_cars_with_different_turns_queue_on_their_shared_approach(self) -> None:
        junction = self.city.standard_intersections[0]
        junction.set_all_way_stop(True)
        north = next(
            item for item in self.city.cul_de_sacs
            if item.position == (200.0, 0.0)
        )
        traffic = TrafficTestbed(spawn_interval=1000.0, rng=random.Random(21))
        first = traffic.spawn_car(self.city, self.west, self.east)
        assert first is not None
        for _ in range(30):
            traffic.update(self.city, 0.05)
        second = traffic.spawn_car(self.city, self.west, north)
        assert second is not None
        self.assertNotEqual(first.points, second.points)

        minimum_separation = float("inf")
        for _ in range(160):
            traffic.update(self.city, 0.05)
            if first not in traffic.cars or second not in traffic.cars:
                break
            minimum_separation = min(
                minimum_separation,
                dist(first.position, second.position),
            )

        self.assertGreaterEqual(
            minimum_separation,
            (first.length + second.length) / 2,
        )

    def test_each_active_junction_periodically_spawns_toward_another(self) -> None:
        traffic = TrafficTestbed(spawn_interval=1.0, rng=random.Random(3))
        traffic.toggle_junction(self.west)
        traffic.toggle_junction(self.east)

        completed = traffic.update(self.city, 1.0)

        self.assertEqual(completed, [])
        self.assertEqual(len(traffic.cars), 2)
        self.assertEqual(
            {(car.source_id, car.destination_id) for car in traffic.cars},
            {(self.west.id, self.east.id), (self.east.id, self.west.id)},
        )

    def test_car_is_removed_after_reaching_its_destination(self) -> None:
        traffic = TrafficTestbed(rng=random.Random(4))
        car = traffic.spawn_car(self.city, self.west, self.east)
        assert car is not None

        completed = traffic.update(self.city, car.total_length / car.speed)

        self.assertEqual(completed, [car])
        self.assertEqual(traffic.cars, [])
        self.assertEqual(car.position, car.points[-1])

    def test_canvas_tool_click_toggles_the_clicked_junction(self) -> None:
        traffic = TrafficTestbed(rng=random.Random(5))

        class Canvas:
            @staticmethod
            def delete(_item: object) -> None:
                pass

        class Host:
            city_map = self.city
            test_traffic = traffic
            canvas = Canvas()

            @staticmethod
            def screen_to_world(point: tuple[float, float]) -> tuple[float, float]:
                return point

            @staticmethod
            def draw_test_traffic_sources() -> None:
                pass

        class Event:
            x, y = self.west.position

        tool = TrafficTool(Host())
        tool.on_canvas_click(Event())

        self.assertTrue(traffic.is_active(self.west))
        self.assertIn("1 active source/sink", tool.message)

    def test_renderer_culls_and_simplifies_test_cars(self) -> None:
        traffic = TrafficTestbed(rng=random.Random(6))
        car = traffic.spawn_car(self.city, self.west, self.east)
        assert car is not None

        class Canvas:
            def __init__(self) -> None:
                self.next_item = 1
                self.created: list[str] = []
                self.configured: list[tuple[object, object]] = []
                self.deleted: list[object] = []

            def create_polygon(self, *_args: object, **_kwargs: object) -> int:
                self.created.append("polygon")
                item = self.next_item
                self.next_item += 1
                return item

            def create_line(self, *_args: object, **_kwargs: object) -> int:
                self.created.append("line")
                item = self.next_item
                self.next_item += 1
                return item

            @staticmethod
            def coords(*_args: object) -> None:
                pass

            def itemconfigure(self, item: object, **kwargs: object) -> None:
                self.configured.append((item, kwargs.get("state")))

            def delete(self, item: object) -> None:
                self.deleted.append(item)

        class Host(RendererMixin):
            canvas = Canvas()
            camera_zoom = 1.0

            @staticmethod
            def visible_world_bounds() -> tuple[float, float, float, float]:
                return (0.0, 0.0, 500.0, 300.0)

            @staticmethod
            def world_to_screen(point: tuple[float, float]) -> tuple[float, float]:
                return point

            @staticmethod
            def world_points(*points: tuple[float, float]) -> list[float]:
                return [coordinate for point in points for coordinate in point]

        host = Host()
        host.draw_test_car(car)
        host.draw_test_car(car)
        self.assertEqual(host.canvas.created, ["polygon"])
        self.assertEqual(host.canvas.configured, [])

        car.position = (1000.0, 1000.0)
        host.draw_test_car(car)
        self.assertEqual(host.canvas.configured, [(car.item, "hidden")])

        car.position = (100.0, 100.0)
        host.camera_zoom = 0.5
        host.draw_test_car(car)
        self.assertEqual(host.canvas.created, ["polygon", "line"])
        self.assertEqual(len(host.canvas.deleted), 1)

    def test_renderer_flashes_two_amber_blinkers_from_simulation_time(self) -> None:
        from car_brain import SignalIntent

        traffic = TrafficTestbed(rng=random.Random(30))
        car = traffic.spawn_car(self.city, self.west, self.east)
        assert car is not None
        car.brain.signal_intent = SignalIntent.LEFT

        class Canvas:
            def __init__(self) -> None:
                self.next_item = 1
                self.ovals: list[dict[str, object]] = []
                self.states: dict[int, str] = {}

            def create_polygon(self, *_args: object, **_kwargs: object) -> int:
                item = self.next_item
                self.next_item += 1
                return item

            def create_oval(self, *_args: object, **kwargs: object) -> int:
                item = self.next_item
                self.next_item += 1
                self.ovals.append(kwargs)
                return item

            @staticmethod
            def coords(*_args: object) -> None:
                pass

            def itemconfigure(self, item: int, **kwargs: object) -> None:
                if "state" in kwargs:
                    self.states[item] = str(kwargs["state"])

            @staticmethod
            def delete(_item: object) -> None:
                pass

        class Host(RendererMixin):
            canvas = Canvas()
            camera_zoom = 1.0
            test_traffic = traffic

            @staticmethod
            def visible_world_bounds() -> tuple[float, float, float, float]:
                return (0.0, 0.0, 500.0, 300.0)

            @staticmethod
            def world_points(*points: tuple[float, float]) -> list[float]:
                return [coordinate for point in points for coordinate in point]

        host = Host()
        traffic.elapsed_time = 0.1
        host.draw_test_car(car)

        self.assertEqual(len(car.signal_items), 2)
        self.assertTrue(all(
            host.canvas.states[item] == "normal" for item in car.signal_items
        ))

        traffic.elapsed_time = 0.6
        host.draw_test_car(car)
        self.assertTrue(all(
            host.canvas.states[item] == "hidden" for item in car.signal_items
        ))


if __name__ == "__main__":
    unittest.main()
