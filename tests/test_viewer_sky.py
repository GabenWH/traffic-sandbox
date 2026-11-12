"""Visible sky must follow the 3D camera without changing the map view."""
import unittest

import numpy as np
from panda3d.core import PNMImage

from city import CityMap, Terrain
from ui.camera3d import OrbitCamera
from ui.view3d import PandaWorldView


class ViewerSkyTests(unittest.TestCase):
    def test_orbit_can_lower_to_the_horizon(self):
        camera = OrbitCamera((0, 0, 0), pitch=10)
        camera.rotate(0, -10)
        self.assertLessEqual(camera.pitch, 1)
        self.assertGreaterEqual(camera.pitch, 1)

    def test_sky_and_clouds_render_only_in_perspective_and_follow_pan(self):
        view = PandaWorldView(offscreen=True, width=480, height=270)
        self.addCleanup(view.close)
        city = CityMap(width=1000, height=700, terrain=Terrain(trees=[]))
        view.show_city(city)
        # A low sightline leaves the top of the image above the horizon.
        view.orbit = OrbitCamera((500, 350, 100), yaw=45, pitch=1, distance=900)
        view.set_mode('perspective')
        ground = view.point_at_screen(240, 240, 0)
        self.assertIsNotNone(ground, 'low camera cannot pick the ground')
        projected = view.screen_position(ground)
        self.assertAlmostEqual(projected[0], 240, delta=.2)
        self.assertAlmostEqual(projected[1], 240, delta=.2)

        def frame():
            view.step()
            view.step()
            image = PNMImage()
            self.assertTrue(view.base.win.getScreenshot(image))
            return np.array([[tuple(image.getXel(x, y)) for x in range(0, 480, 4)]
                             for y in range(0, 100, 4)])

        first = frame()
        red, green, blue = first[..., 0], first[..., 1], first[..., 2]
        blue_sky = (blue > red + .08) & (blue > green + .02)
        bright_cloud = (red > .78) & (green > .78) & (blue > .78) & (blue - red < .15)
        self.assertGreater(blue_sky.mean(), .10, 'no blue sky in the 3D view')
        self.assertGreater(bright_cloud.mean(), .01, 'no visible clouds in the 3D view')

        # A pan changes the world position, not the portion of the sky in view.
        view.orbit.target = (5500, 5350, 100)
        view._apply_camera()
        panned = frame()
        self.assertLess(np.mean(np.abs(first - panned)), .01)

        # Rotating should reveal another portion of the sky instead of sticking
        # the cloud picture to the screen.
        view.orbit.yaw += 90
        view._apply_camera()
        rotated = frame()
        self.assertGreater(np.mean(np.abs(panned - rotated)), .01)

        view.set_mode('map')
        overhead = frame()
        red, green, blue = overhead[..., 0], overhead[..., 1], overhead[..., 2]
        blue_sky = (blue > red + .08) & (blue > green + .02)
        self.assertLess(blue_sky.mean(), .01, 'sky leaked into the 2D map')


if __name__ == '__main__':
    unittest.main()
