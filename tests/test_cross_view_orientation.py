"""Native shared scenes preserve 2D landmarks and perspective navigation."""
import unittest
from types import SimpleNamespace
from city import CityMap,Terrain
from ui.viewport import Viewport


class CrossViewOrientationTests(unittest.TestCase):
    def make_view(self,orbit):
        from panda3d.core import Camera,NodePath,OrthographicLens
        from native_viewer import NativeScene
        from ui.view3d import PandaWorldView
        render=NodePath('render');lens=OrthographicLens();lens.setFilmSize(800,600);lens.setNearFar(1,20000)
        camera=render.attachNewNode(Camera('test-camera',lens))
        view=object.__new__(PandaWorldView)
        view.base=SimpleNamespace(win=object(),render=render,camera=camera,cam=camera,camLens=lens,
                                  setBackgroundColor=lambda *args:None)
        view.orbit=orbit;view.mode='perspective';view.city=None
        view.frame=SimpleNamespace(winfo_width=lambda:800,winfo_height=lambda:600)
        view.native_scene=NativeScene(render,camera);self.addCleanup(view.native_scene.close)
        view.presenter=SimpleNamespace(invalidate=lambda:None)
        view._orthographic=lens;view._perspective=lens;view.map_view=Viewport(0,0,1)
        view.on_motion=None
        return view,camera

    def test_head_on_3d_projection_matches_asymmetric_2d_road_layout(self):
        from ui.camera3d import OrbitCamera
        city=CityMap(width=800,height=600,terrain=Terrain(trees=[]))
        city.add_road([(200,500),(200,100)],road_id='spine')
        city.add_road([(200,100),(600,100)],road_id='top')
        city.add_road([(200,300),(430,300)],road_id='middle')
        view,_=self.make_view(OrbitCamera((400,300,0),yaw=90,pitch=90,distance=1000))
        view.show_city(city)
        view.orbit.target=(400,300,0);view._apply_camera()
        for point in [(200,500),(200,100),(600,100),(200,300),(430,300)]:
            screen=view.screen_position(point,0)
            self.assertIsNotNone(screen)
            self.assertAlmostEqual(screen[0],point[0],delta=.01)
            self.assertAlmostEqual(screen[1],point[1],delta=.01)
            world=view.point_at_screen(*point,0)
            self.assertAlmostEqual(world[0],point[0],delta=.01)
            self.assertAlmostEqual(world[1],point[1],delta=.01)

    def test_downward_orbit_drag_lowers_camera(self):
        from ui.camera3d import OrbitCamera
        view,camera=self.make_view(OrbitCamera((400,300,0),yaw=45,pitch=50,distance=1000))
        view._apply_camera();initial=camera.getZ()
        view._drag_mode='orbit';view._last_pointer=(400,300);view._pointer=lambda:(400,310)
        view._process_pointer()
        self.assertLess(camera.getZ(),initial)

    def test_oblique_orbit_keeps_camera_level(self):
        from panda3d.core import Vec3
        from ui.camera3d import OrbitCamera
        view,camera=self.make_view(OrbitCamera((400,300,0),yaw=45,pitch=50,distance=1000))
        view._apply_camera()
        right=camera.getQuat(view.base.render).xform(Vec3(1,0,0))
        self.assertAlmostEqual(right.z,0,delta=.001)

    def test_pan_moves_the_map_with_the_pointer(self):
        from ui.camera3d import OrbitCamera
        view,_=self.make_view(OrbitCamera((400,300,0),yaw=90,pitch=50,distance=1000))
        view._apply_camera();view._drag_mode='pan';view._last_pointer=(400,300);view._pointer=lambda:(410,310)
        view._process_pointer()
        self.assertLess(view.orbit.target[0],400)
        self.assertLess(view.orbit.target[1],300)
