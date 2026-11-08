"""Shared camera/editor controls: 2D behavior is authoritative."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


class NativeControlTests(unittest.TestCase):
    def test_map_zoom_keeps_the_pointer_world_point_fixed(self):
        from ui.view3d import PandaWorldView
        from ui.viewport import Viewport
        view=object.__new__(PandaWorldView)
        view.mode='map';view.map_view=Viewport(20,40,1)
        view._pointer=lambda:(200,100);view._apply_camera=lambda:None
        before=view.map_view.screen_to_world((200,100))
        view._wheel(.82)
        self.assertEqual(view.map_view.screen_to_world((200,100)),before)

    def test_right_click_dispatches_the_context_menu(self):
        from ui.view3d import PandaWorldView
        view=object.__new__(PandaWorldView)
        calls=[];view.on_right_click=lambda x,y:calls.append((x,y))
        view._pointer=lambda:(80,90)
        view._right_click()
        self.assertEqual(calls,[(80,90)])

    def test_native_mode_does_not_draw_hidden_tk_vehicles_or_people(self):
        from ui.app import FreewaySimulator
        runtime=SimpleNamespace(scene_revision=0,update=lambda dt:None)
        host=SimpleNamespace(city_simulation=runtime,running=True,simulation_speed=1,
            native_view_active=True,draw_road_vehicles=Mock(side_effect=AssertionError('hidden vehicles')),
            draw_city_activity=Mock(side_effect=AssertionError('hidden pedestrians')),
            redraw_world=lambda:None)
        FreewaySimulator._update_construction(host,.05)

    def test_projection_toggle_keeps_the_existing_scene(self):
        from ui.view3d import PandaWorldView
        view=object.__new__(PandaWorldView)
        view.mode='map';view._apply_camera=lambda:None
        scene=object();view.native_scene=scene
        view.set_mode('perspective');self.assertEqual(view.mode,'perspective')
        view.set_mode('map');self.assertEqual(view.mode,'map')
        self.assertIs(view.native_scene,scene)

    def test_retained_overlay_tag_operations_preserve_other_items(self):
        from ui.native_canvas import NativeCanvas
        canvas=NativeCanvas(None,None)
        first=canvas.create_line(0,0,10,10,fill='#ffffff',tags='route')
        second=canvas.create_rectangle(20,20,30,30,fill='#ff0000',tags='preview')
        canvas.coords(first,0,0,50,50)
        canvas.delete('preview')
        self.assertEqual(canvas.find_withtag('route'),(first,))
        self.assertEqual(canvas.coords(first),[0,0,50,50])
        self.assertEqual(canvas.find_overlapping(40,40,60,60),(first,))
        self.assertEqual(canvas.find_withtag('preview'),())


if __name__=='__main__':unittest.main()
