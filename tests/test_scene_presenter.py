"""Model/native boundary regressions; expected elevations are hand-derived."""
import unittest
from types import SimpleNamespace
import numpy as np
from models import Road,Lane
from mobility import MobilityLink
from pathfinding import Path


class SceneCompilationTests(unittest.TestCase):
    def test_height_ruler_uses_route_road_at_a_stacked_crossing(self):
        from ui.scene_buffers import route_heights
        ground=Road('ground','ground',[(0,0),(100,0)],elevations=[0,0])
        ramp=Road('ramp','ramp',[(0,0),(100,0)],elevations=[10,30])
        lane=Lane('ramp lane',[(0,0),(50,0),(100,0)],(100,0),road_id='ramp')
        car=SimpleNamespace(route=Path((),(MobilityLink('lane',lane),),100))
        heights=route_heights(SimpleNamespace(roads=[ground,ramp]),car)
        np.testing.assert_allclose(heights,[(0,10),(50,20),(100,30)])

    def test_static_buffers_include_road_height_and_are_contiguous(self):
        from ui.scene_buffers import compile_city
        from city import CityMap,Terrain
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(100,100),(500,100)],elevations=[20,40])
        triangles,lines=compile_city(city)
        self.assertEqual(triangles.shape[1],7)
        self.assertTrue(triangles.flags.c_contiguous)
        self.assertEqual(triangles.dtype,np.float32)
        self.assertGreaterEqual(float(triangles[:,2].max()),40)

    def test_unchanged_roster_does_not_read_python_vehicle_poses(self):
        from ui.scene_presenter import ScenePresenter
        from native_viewer import NativeScene
        from panda3d.core import NodePath
        from tools.benchmark_native_spawning import make_city
        from tools.benchmark_native_shared import setup
        from unittest.mock import PropertyMock,patch
        city,controls=make_city('signalized-crossing',42,2400)
        sim=setup(city,controls,'shared',10,42)
        scene=NativeScene(NodePath('test'))
        try:
            presenter=ScenePresenter(scene)
            presenter.update(city,sim)
            from native_shared import SharedRoadVehicle
            # Native presentation must not consult the Python position property.
            with patch.object(SharedRoadVehicle,'position',new_callable=PropertyMock,
                              side_effect=AssertionError('Python pose read')):
                presenter.update(city,sim)
            self.assertEqual(scene.stats()['active_vehicles'],10)
        finally:scene.close();sim._discard_native()


if __name__=='__main__':unittest.main()
