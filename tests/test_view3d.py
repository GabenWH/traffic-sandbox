"""Live Tk/Panda viewport check; skipped when graphics dependencies are absent."""

import importlib.util
import os
import tkinter as tk
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("panda3d") and os.environ.get("DISPLAY"),
    "Panda3D and an X display are required",
)
class EmbeddedPandaTests(unittest.TestCase):
    def test_view_opens_child_window_and_draws_a_frame(self) -> None:
        from ui.view3d import PandaWorldView

        root = tk.Tk()
        root.geometry("640x480")
        root.update()
        try:
            view = PandaWorldView(root)
            view.frame.pack(fill="both", expand=True)
            root.update()
            view.step()

            self.assertIsNotNone(view.base.win)
            self.assertFalse(view.base.win.isClosed())
            self.assertIsNotNone(view.base.mouseWatcherNode)
            self.assertGreater(view.frame.winfo_width(), 1)
            self.assertEqual(tuple(view.base.win.getProperties().getOrigin()), (0, 0))
            self.assertEqual(
                tuple(view.base.win.getProperties().getSize()),
                (view.frame.winfo_width(), view.frame.winfo_height()),
            )
            root.geometry("800x600")
            root.update()
            view.step()
            view.step()
            self.assertEqual(tuple(view.base.win.getProperties().getOrigin()), (0, 0))
            self.assertEqual(
                tuple(view.base.win.getProperties().getSize()),
                (view.frame.winfo_width(), view.frame.winfo_height()),
            )

            from city import CityMap, Terrain
            city = CityMap(terrain=Terrain(trees=[]))
            road = city.add_road([(2400, 1750), (2600, 1750)])
            view.show_city(city)
            view.step()
            self.assertFalse(view.base.render.find("**/terrain").isEmpty())
            self.assertFalse(view.base.render.find(f"**/road:{road.id}").isEmpty())
            center = view.point_at_screen(
                view.frame.winfo_width() / 2,
                view.frame.winfo_height() / 2,
                0,
            )
            self.assertIsNotNone(center)
            assert center is not None
            self.assertAlmostEqual(center[0], 2500, delta=2)
            self.assertAlmostEqual(center[1], 1750, delta=2)
            endpoint = view.screen_position(road.centerline[0], road.elevations[0])
            self.assertIsNotNone(endpoint)
            assert endpoint is not None
            self.assertEqual(
                view.nearest_road_endpoint(*endpoint),
                (road.centerline[0], road.elevations[0]),
            )
            view.show_road_preview([(2400, 1750)], [0], (2600, 1750), 20)
            self.assertFalse(view.base.render.find("**/road-preview").isEmpty())
            view.clear_preview()
            self.assertTrue(view.base.render.find("**/road-preview").isEmpty())
            keys: list[str] = []
            view.set_callbacks(on_key=keys.append)
            view.base.messenger.send("page_up")
            self.assertEqual(keys, ["page_up"])
            previous_distance = view.orbit.distance
            view.base.messenger.send("wheel_up")
            self.assertLess(view.orbit.distance, previous_distance)
        finally:
            if "view" in locals():
                view.close()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
