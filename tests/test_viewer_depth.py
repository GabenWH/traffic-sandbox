"""Depth precision and turnaround geometry must survive distant cameras."""
import unittest
from math import radians, sin
from types import SimpleNamespace
import numpy as np

from city import CityMap, Terrain
from color_palette import Palette, panda_rgba


class ViewerDepthTests(unittest.TestCase):
    def test_cul_de_sac_asphalt_and_curb_do_not_overlap_at_the_seam(self):
        from building_footprints import contains_point
        from ui.scene_geometry import cul_de_sac_deck_quads
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(100,100),(500,100)])
        bulb=next(b for b in city.cul_de_sacs if b.position==(100,100))
        pavement,curb=cul_de_sac_deck_quads(bulb)
        point=(92.3459286571,118.4492716546)
        in_asphalt=any(contains_point([p[:2] for p in q[:3]],point) for q in pavement)
        in_curb=any(contains_point([p[:2] for p in q],point) for q in curb)
        self.assertNotEqual(in_asphalt,in_curb,'curb seam must have exactly one surface')

    def test_cul_de_sac_curb_does_not_cover_the_asphalt_or_road_entrance(self):
        from building_footprints import contains_point
        from ui.scene_buffers import compile_city
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(100, 100), (500, 100)])
        triangles, _ = compile_city(city)
        curb = triangles[np.all(np.isclose(triangles[:,3:], panda_rgba(Palette.ROAD_EDGE)), axis=1),:3].reshape(-1,3,3)
        horizontal = [face for face in curb if np.ptp(face[:,2]) < 1e-6]
        self.assertTrue(horizontal)
        for point in ((100, 100), (121, 100)):
            self.assertFalse(any(contains_point([tuple(p[:2]) for p in face], point) for face in horizontal), point)

    def test_perspective_separates_near_coplanar_surfaces_at_every_zoom(self):
        from panda3d.core import Camera, NodePath, OrthographicLens, PerspectiveLens
        from ui.camera3d import OrbitCamera
        from ui.view3d import PandaWorldView
        from ui.viewport import Viewport
        # Use actual Panda lenses/camera; the scene adapter does not participate
        # in projection precision, so no SDK or graphics context is required.
        render = NodePath('root')
        camera = render.attachNewNode(Camera('camera'))
        view = object.__new__(PandaWorldView)
        view.base = SimpleNamespace(camera=camera, cam=camera, render=render)
        view.frame = SimpleNamespace(winfo_width=lambda:1280, winfo_height=lambda:720)
        view.native_scene = SimpleNamespace(set_bounds=lambda bounds:None)
        view._orthographic = OrthographicLens()
        view._perspective = PerspectiveLens()
        view._perspective.setNearFar(1, 20000)
        view.map_view = Viewport(0,0,1)
        view.mode = 'perspective'
        view.orbit = OrbitCamera((2500,1750,0))
        for distance in (60, 1400, 10000):
            with self.subTest(distance=distance):
                view.orbit.distance = distance
                view._apply_camera()
                near, far = view.base.camLens.getNear(), view.base.camLens.getFar()
                # Analytic perspective depth at the target for two horizontal
                # surfaces .01 units apart, in a 24-bit depth buffer. Require
                # two quantization steps to tolerate rounding in rasterization.
                separation = .01*sin(radians(50))
                depth_steps = near*far/(far-near)*separation/(distance*(distance-separation))*((1<<24)-1)
                self.assertGreaterEqual(depth_steps, 2)


if __name__ == '__main__':
    unittest.main()
