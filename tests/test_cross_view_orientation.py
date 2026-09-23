"""A head-on 3D camera preserves the 2D road layout's landmarks."""

import importlib.util
import unittest
from types import SimpleNamespace

from city import CityMap, Terrain
from ui.viewport import Viewport


@unittest.skipUnless(importlib.util.find_spec("panda3d"), "Panda3D is required")
class CrossViewOrientationTests(unittest.TestCase):
    def test_head_on_3d_projection_matches_asymmetric_2d_road_layout(self) -> None:
        from panda3d.core import Camera, NodePath, OrthographicLens, Point3
        from ui.camera3d import OrbitCamera
        from models import Road
        from ui.scene3d import SceneRegistry, attach_map_root, draw_road
        from ui.view3d import PandaWorldView

        width, height = 800, 600
        city = CityMap(width=width, height=height, terrain=Terrain(trees=[]))
        city.add_road([(200, 500), (200, 100)], road_id="spine")
        city.add_road([(200, 100), (600, 100)], road_id="long-top-arm")
        city.add_road([(200, 300), (430, 300)], road_id="short-middle-arm")

        # The unequal arms make rotations and mirrors visible in the projection.
        expected = {
            (200.0, 500.0): (200.0, 500.0),
            (200.0, 100.0): (200.0, 100.0),
            (600.0, 100.0): (600.0, 100.0),
            (200.0, 300.0): (200.0, 300.0),
            (430.0, 300.0): (430.0, 300.0),
        }
        landmarks = {point for road in city.roads for point in road.centerline}
        self.assertEqual(landmarks, set(expected))

        viewport = Viewport(0, 0, 1.0)
        render = NodePath("render")
        scene = SceneRegistry(attach_map_root(render, "city"))
        scene.register(Road, draw_road)
        lens = OrthographicLens()
        lens.setFilmSize(width, height)
        lens.setNearFar(1, 2000)
        camera = render.attachNewNode(Camera("head-on-camera", lens))

        # A non-None window sentinel lets screen_position use the real camera
        # and lens without opening a graphics window.
        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(
            win=object(), render=render, camera=camera, camLens=lens,
        )
        view.orbit = OrbitCamera(
            (width / 2, height / 2, 0), yaw=90, pitch=90, distance=1000,
        )
        view.city = None
        view.scene = scene
        view.frame = SimpleNamespace(
            winfo_width=lambda: width,
            winfo_height=lambda: height,
        )
        view.show_city(city)
        self.assertEqual(render.findAllMatches("**/road:*").getNumPaths(), len(city.roads))
        panda_point = render.getRelativePoint(scene.root, Point3(200, 500, 0))
        self.assertAlmostEqual(panda_point.y, -500, delta=0.01)

        for point, expected_screen in expected.items():
            screen_2d = viewport.world_to_screen(point)
            self.assertEqual(screen_2d, expected_screen)

            screen_3d = view.screen_position(point, 0)
            self.assertIsNotNone(screen_3d)
            assert screen_3d is not None
            self.assertAlmostEqual(screen_3d[0], expected_screen[0], delta=0.01)
            self.assertAlmostEqual(screen_3d[1], expected_screen[1], delta=0.01)

            world_point = view.point_at_screen(*expected_screen, 0)
            self.assertIsNotNone(world_point)
            assert world_point is not None
            self.assertAlmostEqual(world_point[0], point[0], delta=0.01)
            self.assertAlmostEqual(world_point[1], point[1], delta=0.01)

    def test_downward_orbit_drag_lowers_camera(self) -> None:
        from panda3d.core import Camera, NodePath, OrthographicLens
        from ui.camera3d import OrbitCamera
        from ui.view3d import PandaWorldView

        render = NodePath("render")
        lens = OrthographicLens()
        camera = render.attachNewNode(Camera("orbit-camera", lens))
        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(
            win=object(), render=render, camera=camera, camLens=lens,
        )
        view.orbit = OrbitCamera((400, 300, 0), yaw=45, pitch=50, distance=1000)
        view._drag_mode = "orbit"
        view._last_pointer = (400, 300)
        view._pointer = lambda: (400, 310)
        view.on_motion = None
        view._apply_camera()
        initial_camera_z = camera.getZ()

        view._process_pointer()

        self.assertLess(camera.getZ(), initial_camera_z)

    def test_oblique_orbit_keeps_camera_level(self) -> None:
        from panda3d.core import Camera, NodePath, OrthographicLens, Vec3
        from ui.camera3d import OrbitCamera
        from ui.view3d import PandaWorldView

        render = NodePath("render")
        camera = render.attachNewNode(Camera("level-camera", OrthographicLens()))
        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(camera=camera, render=render)
        view.orbit = OrbitCamera((400, 300, 0), yaw=45, pitch=50, distance=1000)

        view._apply_camera()

        camera_right = camera.getQuat(render).xform(Vec3(1, 0, 0))
        self.assertAlmostEqual(camera_right.z, 0, delta=0.001)

    def test_pan_moves_the_map_with_the_pointer(self) -> None:
        from panda3d.core import Camera, NodePath, OrthographicLens
        from ui.camera3d import OrbitCamera
        from ui.view3d import PandaWorldView

        render = NodePath("render")
        lens = OrthographicLens()
        camera = render.attachNewNode(Camera("pan-camera", lens))
        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(
            win=object(), render=render, camera=camera, camLens=lens,
        )
        view.orbit = OrbitCamera((400, 300, 0), yaw=90, pitch=50, distance=1000)
        view.frame = SimpleNamespace(winfo_height=lambda: 600)
        view._drag_mode = "pan"
        view._last_pointer = (400, 300)
        view._pointer = lambda: (410, 310)
        view.on_motion = None
        view._apply_camera()

        view._process_pointer()

        self.assertLess(view.orbit.target[0], 400)
        self.assertLess(view.orbit.target[1], 300)


if __name__ == "__main__":
    unittest.main()
