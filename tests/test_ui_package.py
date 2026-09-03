"""Headless checks for the split UI package and viewport math."""

import unittest

import ui
from city import CityMap, Terrain
from models import ControlDefinition, ControlType
from ui import FreewaySimulator
from ui.renderer import RendererMixin
from ui.viewport import Viewport


class UIPackageTests(unittest.TestCase):
    def test_public_import_reexports_application(self) -> None:
        self.assertIs(ui.FreewaySimulator, FreewaySimulator)
        self.assertEqual(FreewaySimulator.__module__, "ui.app")

    def test_viewport_projection_round_trip(self) -> None:
        viewport = Viewport(100, 50, 2)

        screen = viewport.world_to_screen((125, 80))

        self.assertEqual(screen, (50, 60))
        self.assertEqual(viewport.screen_to_world(screen), (125, 80))

    def test_renderer_draws_an_empty_world_with_configured_dimensions(self) -> None:
        class FakeCanvas:
            def __init__(self) -> None:
                self.rectangles: list[tuple[object, ...]] = []

            def winfo_width(self) -> int:
                return 1

            def winfo_height(self) -> int:
                return 1

            def delete(self, _tag: str) -> None:
                pass

            def create_rectangle(self, *args: object, **_kwargs: object) -> None:
                self.rectangles.append(args)

            def create_text(self, *_args: object, **_kwargs: object) -> None:
                pass

            def tag_lower(self, _tag: str) -> None:
                pass

        class Host(RendererMixin):
            canvas = FakeCanvas()
            city_map = CityMap(terrain=Terrain(trees=[]))
            blank_map = True
            camera_zoom = 1.0

            @staticmethod
            def visible_world_bounds() -> tuple[float, float, float, float]:
                return (0, 0, 1000, 640)

            @staticmethod
            def world_to_screen(point: tuple[float, float]) -> tuple[float, float]:
                return point

        host = Host()

        host.draw_scene()

        self.assertEqual(host.canvas.rectangles[0], (0, 0, 1000, 640))

    def test_two_way_road_divider_uses_the_smallest_drawable_width_when_zoomed_out(self) -> None:
        class FakeCanvas:
            def __init__(self) -> None:
                self.lines: list[dict[str, object]] = []

            def create_line(self, *_args: object, **kwargs: object) -> None:
                self.lines.append(kwargs)

            @staticmethod
            def create_oval(*_args: object, **_kwargs: object) -> None:
                pass

        class Host(RendererMixin):
            canvas = FakeCanvas()
            city_map = CityMap(terrain=Terrain(trees=[]))
            camera_zoom = 0.35

            @staticmethod
            def world_points(*points: tuple[float, float]) -> list[float]:
                return [coordinate for point in points for coordinate in point]

        host = Host()
        host.city_map.add_road([(0, 0), (100, 0)])

        host.draw_city_roads()

        self.assertEqual(host.canvas.lines[-1]["width"], 1)
        host.canvas.lines.clear()
        host.camera_zoom = 3.0
        host.draw_city_roads()
        self.assertEqual(host.canvas.lines[-1]["width"], 2)

    def test_all_way_stop_draws_a_stop_bar_for_each_incoming_port(self) -> None:
        class FakeCanvas:
            def __init__(self) -> None:
                self.lines: list[dict[str, object]] = []

            def create_line(self, *_args: object, **kwargs: object) -> None:
                self.lines.append(kwargs)

            @staticmethod
            def create_oval(*_args: object, **_kwargs: object) -> None:
                pass

        class Host(RendererMixin):
            canvas = FakeCanvas()
            city_map = CityMap(terrain=Terrain(trees=[]))
            camera_zoom = 1.0

            @staticmethod
            def world_points(*points: tuple[float, float]) -> list[float]:
                return [coordinate for point in points for coordinate in point]

            @staticmethod
            def world_to_screen(point: tuple[float, float]) -> tuple[float, float]:
                return point

        host = Host()
        host.city_map.add_road([(0, 50), (100, 50)])
        host.city_map.add_road([(50, 0), (50, 100)])
        host.city_map.standard_intersections[0].set_all_way_stop(True)

        host.draw_city_roads()

        stop_bars = [
            line for line in host.canvas.lines
            if "stop_lines" in line.get("tags", ())
        ]
        self.assertEqual(len(stop_bars), 4)

    def test_static_city_objects_are_culled_and_simplified_at_low_zoom(self) -> None:
        class FakeCanvas:
            def __init__(self) -> None:
                self.lines: list[dict[str, object]] = []
                self.ovals: list[dict[str, object]] = []

            def create_line(self, *_args: object, **kwargs: object) -> None:
                self.lines.append(kwargs)

            def create_oval(self, *_args: object, **kwargs: object) -> None:
                self.ovals.append(kwargs)

        class Host(RendererMixin):
            canvas = FakeCanvas()
            city_map = CityMap(terrain=Terrain(trees=[]))
            camera_zoom = 1.0

            @staticmethod
            def visible_world_bounds() -> tuple[float, float, float, float]:
                return (0.0, 0.0, 200.0, 200.0)

            @staticmethod
            def world_points(*points: tuple[float, float]) -> list[float]:
                return [coordinate for point in points for coordinate in point]

            @staticmethod
            def world_to_screen(point: tuple[float, float]) -> tuple[float, float]:
                return point

        host = Host()
        host.city_map.add_road([(0, 100), (100, 100)])
        host.city_map.add_road([(1000, 100), (1100, 100)])

        host.draw_city_roads()
        self.assertEqual(len(host.canvas.lines), 3)
        self.assertEqual(len(host.canvas.ovals), 4)

        host.canvas.lines.clear()
        host.canvas.ovals.clear()
        host.camera_zoom = 0.5
        host.draw_city_roads()
        self.assertEqual(len(host.canvas.lines), 2)
        self.assertEqual(len(host.canvas.ovals), 2)

    def test_split_roads_render_edges_before_surfaces_without_junction_edge_ring(self) -> None:
        class FakeCanvas:
            def __init__(self) -> None:
                self.lines: list[dict[str, object]] = []
                self.ovals: list[dict[str, object]] = []

            def create_line(self, *_args: object, **kwargs: object) -> None:
                self.lines.append(kwargs)

            def create_oval(self, *_args: object, **kwargs: object) -> None:
                self.ovals.append(kwargs)

        class Host(RendererMixin):
            canvas = FakeCanvas()
            city_map = CityMap(terrain=Terrain(trees=[]))
            camera_zoom = 1.0

            @staticmethod
            def world_points(*points: tuple[float, float]) -> list[float]:
                return [coordinate for point in points for coordinate in point]

            @staticmethod
            def world_to_screen(point: tuple[float, float]) -> tuple[float, float]:
                return point

        host = Host()
        host.city_map.add_road([(0, 50), (100, 50)])
        host.city_map.add_road([(50, 0), (50, 100)])

        host.draw_city_roads()

        fills = [line["fill"] for line in host.canvas.lines]
        self.assertEqual(fills[:4], ["#c9cdd0"] * 4)
        self.assertEqual(fills[4:8], ["#4d535a"] * 4)
        self.assertEqual(fills[8:], ["#f4c542"] * 4)
        self.assertEqual(
            [oval["fill"] for oval in host.canvas.ovals],
            ["#c9cdd0"] * 4 + ["#4d535a"] * 5,
        )


if __name__ == "__main__":
    unittest.main()
