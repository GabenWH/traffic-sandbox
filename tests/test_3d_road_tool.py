"""The existing road tool can author heights from the embedded 3D view."""

from types import SimpleNamespace
import unittest

from city import CityMap, Terrain
from ui_tools.tools.road_tool import RoadTool


class RoadTool3DTests(unittest.TestCase):
    def test_page_keys_set_road_vertex_heights(self) -> None:
        class Canvas:
            def delete(self, _tag: str) -> None:
                pass

        class Host:
            canvas = Canvas()
            city_map = CityMap(terrain=Terrain(trees=[]))
            view3d_active = True

            @staticmethod
            def road_point_from_event(event: object, _height: float) -> tuple[float, float]:
                return (event.x, event.y)

            @staticmethod
            def redraw_world() -> None:
                pass

        tool = RoadTool(Host())
        tool.adjust_elevation(1)
        tool.adjust_elevation(1)
        tool.on_canvas_click(SimpleNamespace(x=0, y=0))
        tool.adjust_elevation(-1)
        tool.on_canvas_click(SimpleNamespace(x=100, y=0))
        tool.finish()

        self.assertEqual(Host.city_map.roads[0].elevations, [20, 10])
        self.assertEqual(tool.draft_elevation, 0)

    def test_page_down_stops_at_ground(self) -> None:
        tool = RoadTool(SimpleNamespace())
        tool.adjust_elevation(-1)

        self.assertEqual(tool.draft_elevation, 0)

    def test_first_vertex_inherits_an_elevated_road_endpoint(self) -> None:
        class Host:
            view3d_active = True

            @staticmethod
            def road_endpoint_from_event(_event: object):
                return ((100.0, 200.0), 30.0)

            @staticmethod
            def road_point_from_event(_event: object, _height: float):
                return (1.0, 2.0)

        tool = RoadTool(Host())
        tool.on_canvas_click(SimpleNamespace(x=25, y=40))

        self.assertEqual(tool.points, [(100.0, 200.0)])
        self.assertEqual(tool.elevations, [30.0])
        self.assertEqual(tool.draft_elevation, 30.0)

    def test_height_key_reprojects_preview_at_stationary_cursor(self) -> None:
        class Host:
            view3d_active = True

            @staticmethod
            def road_point_from_event(event: object, height: float):
                return (event.x + height, event.y)

        tool = RoadTool(Host())
        tool.on_canvas_motion(SimpleNamespace(x=25, y=40))
        tool.adjust_elevation(1)

        self.assertEqual(tool.pointer, (35.0, 40))


if __name__ == "__main__":
    unittest.main()
