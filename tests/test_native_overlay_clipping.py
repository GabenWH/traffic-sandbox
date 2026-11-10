"""Off-screen dashed previews must cost work proportional to the viewport."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from ui.native_canvas import NativeCanvas
from ui.scene_buffers import GeometryBuffer


class OverlayClippingTests(unittest.TestCase):
    def canvas(self, width=640, height=480):
        arrays = []
        scene = SimpleNamespace(replace_static=lambda *data:arrays.append(data), replace_texts=lambda texts:None)
        frame = SimpleNamespace(winfo_width=lambda:width, winfo_height=lambda:height)
        return NativeCanvas(None, SimpleNamespace(overlay_scene=scene,frame=frame)), arrays

    def test_billion_pixel_dashed_preview_is_clipped_before_tessellation(self):
        canvas, arrays = self.canvas()
        canvas.create_rectangle(-1e9,-1e9,200,240,outline='#ffffff',dash=(6,4))
        original = GeometryBuffer.quads
        def guard(buffer, faces, color):
            # Fail promptly on the old implementation, before it exhausts RAM.
            self.assertLess(len(buffer.triangles), 5000, 'tessellating off-screen dashes')
            return original(buffer,faces,color)
        with patch.object(GeometryBuffer,'quads',guard):
            canvas.flush()
        triangles = arrays[-1][0]
        self.assertGreater(len(triangles),0)
        self.assertLess(len(triangles),1000)
        self.assertTrue(np.all(triangles[:,0]>=-1))
        self.assertTrue(np.all(triangles[:,2]>=-481))

    def test_clipping_preserves_dash_phase_and_removes_invisible_segments(self):
        canvas, arrays = self.canvas(60,20)
        canvas.create_line(-95,10,100,10,fill='#ffffff',width=2,dash=(10,10))
        canvas.create_line(-100,-100,-20,-20,fill='#ff0000',dash=(2,2))
        canvas.flush()
        faces = arrays[-1][0].reshape(-1,6,7)
        intervals = [(float(f[:,0].min()),float(f[:,0].max())) for f in faces]
        self.assertEqual(intervals,[(5,15),(25,35),(45,55)])

    def test_resizing_reclips_retained_items_without_an_editor_change(self):
        canvas, arrays = self.canvas(60,20)
        canvas.create_line(-95,10,100,10,fill='#ffffff',width=2,dash=(10,10))
        canvas.flush()
        self.assertEqual(float(arrays[-1][0][:,0].max()),55)
        canvas.view.frame.winfo_width=lambda:100
        canvas.flush()
        self.assertEqual(float(arrays[-1][0][:,0].max()),95)
