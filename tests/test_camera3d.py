"""Orbit camera math stays independent of the graphics window."""

import unittest

from ui.camera3d import OrbitCamera, ray_to_height


class OrbitCameraTests(unittest.TestCase):
    def test_camera_position_uses_yaw_and_pitch(self) -> None:
        camera = OrbitCamera((10, 20, 0), yaw=0, pitch=0, distance=100)

        self.assertEqual(camera.position, (110, 20, 0))
        camera.rotate(90, 45)
        x, y, z = camera.position
        self.assertAlmostEqual(x, 10)
        self.assertAlmostEqual(y, 20 + 100 / 2 ** 0.5)
        self.assertAlmostEqual(z, 100 / 2 ** 0.5)

    def test_camera_pitch_and_distance_remain_usable(self) -> None:
        camera = OrbitCamera((0, 0, 0), yaw=0, pitch=45, distance=100)

        camera.rotate(0, 200)
        camera.zoom(0.001)

        self.assertEqual(camera.pitch, 90)
        self.assertGreater(camera.distance, 0)

    def test_screen_ray_intersects_selected_road_height(self) -> None:
        point = ray_to_height((10, 20, 100), (1, 0, -1), 20)

        self.assertEqual(point, (90, 20))

    def test_parallel_screen_ray_has_no_placement_point(self) -> None:
        self.assertIsNone(ray_to_height((0, 0, 10), (1, 0, 0), 0))


if __name__ == "__main__":
    unittest.main()
