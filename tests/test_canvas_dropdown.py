"""Headless checks for dropdown-owned canvas tools."""

import unittest

from city import CityMap, Terrain
from ui_tools.tools.road_tool import BuildingTool, BuildTool, RoadTool


class CanvasDropdownTests(unittest.TestCase):
    def test_build_menu_selects_road_mode_and_exposes_inspector(self) -> None:
        selected: list[object] = []

        class Inspector:
            def show_panel(self) -> None:
                pass

        class Host:
            inspector_tool = Inspector()

            @staticmethod
            def select_tool(tool: object) -> None:
                selected.append(tool)

        dropdown = BuildTool(Host())
        actions = dropdown.actions()
        assert actions[0].command is not None

        actions[0].command()

        road = dropdown.owned_canvas_tools[0]
        self.assertIsInstance(road, RoadTool)
        self.assertIsInstance(dropdown.owned_canvas_tools[1], BuildingTool)
        self.assertEqual(selected, [road])
        self.assertIs(road.inspector, dropdown.host.inspector_tool)
        self.assertEqual(actions[-1].label, "Inspector…")

    def test_active_build_button_deactivates_its_canvas_mode(self) -> None:
        deactivated: list[object] = []

        class Host:
            inspector_tool = None

            def __init__(self) -> None:
                self.active_tool: object | None = None

            @staticmethod
            def select_tool(_tool: object) -> None:
                pass

            def deactivate_tool(self, tool: object) -> None:
                deactivated.append(tool)

        host = Host()
        dropdown = BuildTool(host)
        host.active_tool = dropdown.owned_canvas_tools[0]

        result = dropdown._deactivate_from_active_button(object())

        self.assertEqual(result, "break")
        self.assertEqual(deactivated, [host.active_tool])

    def test_finished_road_uses_selected_json_buildable_specs(self) -> None:
        class Canvas:
            @staticmethod
            def delete(_tag: str) -> None:
                pass

        class Host:
            inspector_tool = None
            city_map = CityMap(terrain=Terrain(trees=[]))
            canvas = Canvas()

            @staticmethod
            def redraw_world() -> None:
                pass

        road_tool = RoadTool(Host())
        road_tool.selected_spec = next(
            spec for spec in road_tool.specs if spec.id == "four_lane_avenue"
        )
        road_tool.points = [(0, 0), (100, 0)]

        road_tool.finish()

        road = road_tool.host.city_map.roads[0]
        self.assertEqual(road.name, "Four-lane avenue 1")
        self.assertEqual(road.buildable_id, "four_lane_avenue")
        self.assertEqual((road.forward_lane_count, road.reverse_lane_count), (2, 2))


if __name__ == "__main__":
    unittest.main()
