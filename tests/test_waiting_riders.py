import unittest
import importlib.util
from types import SimpleNamespace
from tests.test_transit import TransitTests
from gameplay_persistence import dump_transport, restore_transport

class WaitingRiderTests(unittest.TestCase):
    def test_individual_queue_poses_survive_save_and_clear_only_for_boarded_riders(self):
        sim=TransitTests().system(capacity=1)
        self.addCleanup(sim.traffic._discard_native)
        for pid in (1,2):sim.request_trip(pid,(100,15),(5740,15))
        sim.update(20)
        poses=list(sim.waiting_people())
        self.assertEqual({p.id for p in poses},{1,2})
        self.assertEqual(len({p.position for p in poses}),2)
        restore_transport(sim,dump_transport(sim))
        self.assertEqual([(p.id,p.position) for p in sim.waiting_people()],[(p.id,p.position) for p in poses])
        sim.update(40)
        self.assertEqual([p.id for p in sim.waiting_people()],[2])
        sim.update(1200)
        self.assertEqual(list(sim.waiting_people()),[])

    def test_crossing_waiting_area_uses_same_layout_without_transit(self):
        from waiting_people import WaitingArea, waiting_person_poses
        people=list(waiting_person_poses([WaitingArea(tuple(range(12)),(10,20),(0,1),(-1,0),8)]))
        self.assertEqual({p.id for p in people},set(range(12)))
        self.assertEqual(len({p.position for p in people}),12)
        self.assertTrue(all(p.position[0]<=10 and p.elevation==8 for p in people))
        self.assertEqual(people[4].position,(7,20))

    @unittest.skipUnless(importlib.util.find_spec('panda3d'), 'Panda3D is required')
    def test_native_view_shows_each_waiter_and_removes_boarded_person(self):
        from native_viewer import NativeScene
        from panda3d.core import NodePath
        from persistent_fleet import PersistentFleet
        from ui.scene_presenter import ScenePresenter
        sim=TransitTests().system(capacity=1)
        self.addCleanup(sim.traffic._discard_native)
        fleet=PersistentFleet(sim,{})
        sim.city.gameplay=SimpleNamespace(fleet=fleet)
        scene=NativeScene(NodePath('root'));self.addCleanup(scene.close)
        presenter=ScenePresenter(scene)
        for pid in (1,2):sim.request_trip(pid,(100,15),(5740,15))
        sim.update(20);presenter.update(sim.city,sim.traffic)
        self.assertEqual(scene.stats()['parked_vehicles'],2)
        sim.update(40);presenter.update(sim.city,sim.traffic)
        self.assertEqual(scene.stats()['parked_vehicles'],1)
