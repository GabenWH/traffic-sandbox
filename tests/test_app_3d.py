"""The 3D road view shares the Tk toolbar and road construction tool."""

import importlib.util
import os
import tkinter as tk
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    importlib.util.find_spec("panda3d") and os.environ.get("DISPLAY"),
    "Panda3D and an X display are required",
)
class App3DTests(unittest.TestCase):
    def test_perspective_camera_reprojects_retained_route_overlays(self):
        from ui import FreewaySimulator
        from ui_tools.tools.route_test_tool import RouteTestTool,ROUTE_TEST_TAG
        root=tk.Tk();root.geometry('1200x800');app=None
        try:
            app=FreewaySimulator(root);root.update();app.toggle_3d_view()
            tool=RouteTestTool(app);app.active_tool=tool
            lane=app.city_map.roads[0].lanes[0]
            tool.route=app.city_map.find_vehicle_route(lane,lane);tool.refresh()
            first=next(i for i in app.canvas.find_withtag(ROUTE_TEST_TAG) if app.canvas._items[i][0]=='line')
            before=app.canvas.coords(first)
            app.view3d.orbit.rotate(30,0);app.view3d._apply_camera();app.view3d.step()
            first=next(i for i in app.canvas.find_withtag(ROUTE_TEST_TAG) if app.canvas._items[i][0]=='line')
            self.assertNotEqual(app.canvas.coords(first),before)
        finally:
            if app is not None:app.view3d.close()
            root.destroy()

    def test_road_tool_builds_an_elevated_road_in_embedded_view(self) -> None:
        from ui import FreewaySimulator
        from ui_tools.tools.road_tool import RoadTool

        root = tk.Tk()
        root.geometry("1000x700")
        try:
            app = FreewaySimulator(root)
            starting_roads=len(app.city_map.roads)
            root.update()
            app.toggle_3d_view()
            root.update()
            assert app.view3d is not None
            app.view3d.step()
            self.assertTrue(app.view3d_active)

            road_tool = next(
                tool for toolbar in app.tools for tool in toolbar.iter_canvas_tools()
                if isinstance(tool, RoadTool)
            )
            app.select_tool(road_tool)
            self.assertIsNotNone(road_tool.panel)
            assert road_tool.panel is not None
            self.assertIs(road_tool.panel.panel.master, app.sidebar)
            app.view3d.base.messenger.send("page_up")
            app._handle_3d_click(300, 250)
            app._handle_3d_click(400, 250)
            road_tool.finish()

            self.assertEqual(len(app.city_map.roads), starting_roads+1)
            self.assertEqual(app.city_map.roads[-1].elevations, [10, 10])
            self.assertGreater(app.view3d.native_scene.stats()['static_triangles'],2)
            built_road = app.city_map.roads[-1]
            endpoint = app.view3d.screen_position(
                built_road.centerline[0], built_road.elevations[0],
            )
            assert endpoint is not None
            app._handle_3d_click(round(endpoint[0]), round(endpoint[1]))
            self.assertEqual(road_tool.points, [built_road.centerline[0]])
            self.assertEqual(road_tool.elevations, [10])
            road_tool.cancel()
            camera_state = {
                "target": [2200, 1700, 0], "yaw": 100, "pitch": 35, "distance": 850,
            }
            app.restore_3d_camera(camera_state)
            self.assertEqual(app.camera_3d_state(), camera_state)
            with patch("ui.files.messagebox.askyesno", return_value=True):
                app.new_world()
            self.assertIs(app.view3d.city,app.city_map)
            self.assertEqual(len(app.city_map.roads),starting_roads)
        finally:
            if "app" in locals() and getattr(app, "view3d", None) is not None:
                app.view3d.close()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
