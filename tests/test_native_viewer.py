"""Real native presentation: catches stale buffers, wrong heights and batching regressions."""
import unittest
import numpy as np
from panda3d.core import NodePath


class NativeViewerTests(unittest.TestCase):
    def setUp(self):
        from native_viewer import NativeScene
        self.root=NodePath('test-world')
        self.scene=NativeScene(self.root)

    def tearDown(self):
        if hasattr(self,'scene'):self.scene.close()

    def test_static_replacement_batches_local_triangles_and_clears_old_world(self):
        # Two triangles in one cell must not become six separate drawables.
        vertices=np.array([(0,0,0,1,0,0,1),(10,0,0,1,0,0,1),(0,10,0,1,0,0,1),
                           (20,0,0,0,1,0,1),(30,0,0,0,1,0,1),(20,10,0,0,1,0,1)],dtype='float32')
        self.scene.replace_static(vertices,np.empty((0,7),dtype='float32'))
        stats=self.scene.stats()
        self.assertEqual(stats['static_triangles'],2)
        self.assertEqual(stats['static_geoms'],1)
        self.scene.replace_static(np.empty((0,7),dtype='float32'),np.empty((0,7),dtype='float32'))
        self.assertEqual(self.scene.stats()['static_triangles'],0)

    def test_bad_upload_preserves_the_previous_scene(self):
        valid=np.array([(0,0,0,1,0,0,1),(10,0,0,1,0,0,1),(0,10,0,1,0,0,1)],dtype='float32')
        self.scene.replace_static(valid,np.empty((0,7),dtype='float32'))
        invalid=valid.copy();invalid[0,0]=float('nan')
        with self.assertRaises(ValueError):
            self.scene.replace_static(invalid,np.empty((0,7),dtype='float32'))
        self.assertEqual(self.scene.stats()['static_triangles'],1)

    def test_native_poses_interpolate_route_height_and_empty_snapshot_removes_actors(self):
        from native_traffic import NativeTrafficEngine,NativeVehicleView
        from vehicle import VehicleAppearance
        self.scene.register_vehicle(7,VehicleAppearance(),14,6,'#ff0000',
                                    np.array([(0,0),(100,20)],dtype='float64'))
        rows=(NativeVehicleView*1)()
        rows[0].handle=7;rows[0].alive=1;rows[0].distance=25
        rows[0].x=10;rows[0].y=30;rows[0].hx=1
        self.scene.update_states(rows,1,0.)
        pose=self.scene.snapshot()[0]
        self.assertEqual(pose['handle'],7)
        self.assertAlmostEqual(pose['z'],5.)
        self.assertEqual(self.scene.stats()['active_vehicles'],1)
        self.scene.update_states(rows,0,0.)
        self.assertEqual(self.scene.stats()['active_vehicles'],0)
        self.assertEqual(self.scene.snapshot(),[])

    def test_parked_cars_have_local_batches_with_finite_culling_bounds(self):
        from native_viewer import Parked,visual
        from vehicle import VehicleAppearance
        rows=[Parked(visual(i,VehicleAppearance(),14,6,'#ff0000'),x,20,0,0,1)
              for i,x in enumerate((100,200,900))]
        self.scene.replace_parked(rows)
        self.assertEqual(self.scene.stats()['parked_vehicles'],3)
        self.assertEqual(self.scene.stats()['actor_geoms'],2)
        for node in self.root.findAllMatches('**/parked/**/+GeomNode'):
            self.assertFalse(node.node().getBounds().isInfinite())


if __name__=='__main__':unittest.main()
