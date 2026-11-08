"""Production consumers and lifetime boundaries for live native vehicle views."""
import importlib.util
import json
import unittest
from unittest.mock import patch

from car_brain import CarBrain
from city import CityMap, Terrain
from gameplay_persistence import dump_transport, restore_transport
from native_shared import SharedRoadVehicle
from persistence import world_from_dict, world_to_dict
from traffic_testbed import RoadVehicleSimulation, RoutedRoadVehicle
from transit import TransitSimulation


class SharedLifecycleTests(unittest.TestCase):
    def scenario(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (1200, 100)])
        traffic = RoadVehicleSimulation(spawn_interval=10000)
        self.addCleanup(traffic._discard_native)
        car = traffic.spawn_car(city, *city.cul_de_sacs)
        self.assertIsInstance(car, SharedRoadVehicle)
        return city, traffic, car

    def test_retained_completed_brain_and_vehicle_survive_later_steps_and_close(self):
        city, traffic, car = self.scenario()
        brain = car.brain
        done = traffic.update(city, 60)
        self.assertEqual(done, [car])
        state = (car.distance, car.position, car.speed, brain.state, brain.wait_reason)
        self.assertIs(type(car), RoutedRoadVehicle)
        self.assertIs(type(brain), CarBrain)
        traffic.update(city, .05)
        traffic._discard_native()
        self.assertEqual((car.distance, car.position, car.speed, brain.state, brain.wait_reason), state)

    def test_replacing_brain_materializes_old_brain_before_native_storage_is_freed(self):
        city, traffic, car = self.scenario()
        traffic.update(city, .05)
        old = car.brain
        expected = (old.state, old.desired_speed, old.stopped_elapsed, old.wait_reason)
        car.brain = CarBrain(merge_style='cautious')
        self.assertIs(type(old), CarBrain)
        traffic.update(city, .05)
        old.desired_speed = 2
        self.assertEqual((old.state, old.stopped_elapsed, old.wait_reason),
                         (expected[0], expected[2], expected[3]))
        self.assertEqual(car.brain.merge_style, 'cautious')
        self.assertNotEqual(car.brain.desired_speed, 2)

    def test_road_rebuild_materializes_retained_objects_and_accepts_new_native_views(self):
        city, traffic, car = self.scenario()
        traffic.update(city, .05)
        expected = (car.distance, car.position, car.brain.wait_reason)
        city.rebuild_mobility_network()
        changed, removed = traffic.sync_network(city)
        self.assertTrue(changed)
        self.assertEqual(removed, [car])
        self.assertIs(type(car), RoutedRoadVehicle)
        self.assertEqual((car.distance, car.position, car.brain.wait_reason), expected)
        replacement = traffic.spawn_car(city, *city.cul_de_sacs)
        self.assertIsInstance(replacement, SharedRoadVehicle)
        traffic.update(city, .05)
        self.assertEqual((car.distance, car.position, car.brain.wait_reason), expected)

    def test_save_reads_live_state_and_restores_equivalent_transport(self):
        city, traffic, car = self.scenario()
        transit = TransitSimulation(city, traffic)
        transit.update(.25)
        before_engine = traffic._native_controller.engine
        saved = json.loads(json.dumps(dump_transport(transit)))
        self.assertIs(traffic._native_controller.engine, before_engine)
        self.assertIsInstance(car, SharedRoadVehicle)
        restored_traffic = RoadVehicleSimulation()
        self.addCleanup(restored_traffic._discard_native)
        world = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        restored_city = world_from_dict(json.loads(json.dumps(world))).city_map
        restored = TransitSimulation(restored_city, restored_traffic)
        actors = restore_transport(restored, saved)
        self.assertEqual(actors[car.id].distance, car.distance)
        self.assertEqual(actors[car.id].position, car.position)
        self.assertIsInstance(actors[car.id], SharedRoadVehicle)
        for _ in range(20):
            transit.update(.05)
            restored.update(.05)
        self.assertEqual(dump_transport(restored), dump_transport(transit))

        # Restored actors must accept edits through the same ownership callbacks
        # as newly admitted actors, including fields without shared descriptors.
        loaded_car = actors[car.id]
        old_brain = loaded_car.brain
        loaded_car.brain = CarBrain(merge_style='cautious')
        self.assertIsNone(restored_traffic._native_controller)
        self.assertIs(type(old_brain), CarBrain)
        restored_traffic.update(restored_city, .05)
        self.assertIsInstance(loaded_car, SharedRoadVehicle)
        self.assertEqual(loaded_car.brain.merge_style, 'cautious')
        loaded_car.length = 18
        self.assertIsNone(restored_traffic._native_controller)
        restored_traffic.update(restored_city, .05)
        self.assertEqual(loaded_car.length, 18)

    @unittest.skipUnless(importlib.util.find_spec('panda3d'), 'Panda3D is required')
    def test_scene_reads_live_native_position_without_exporting_the_fleet(self):
        from panda3d.core import NodePath
        from ui.scene3d import update_road_vehicle_layer
        city, traffic, car = self.scenario()
        engine = traffic._native_controller.engine
        root, nodes = NodePath('shared-test'), {}
        self.addCleanup(root.removeNode)
        with patch.object(engine, 'vehicle_views', side_effect=AssertionError('eager export')):
            update_road_vehicle_layer(traffic.cars, city, root, nodes, .05)
            before = tuple(nodes[car.id].getPos())
            engine.step(.2)
            update_road_vehicle_layer(traffic.cars, city, root, nodes, .05)
            after = tuple(nodes[car.id].getPos())
            self.assertNotEqual(before, after)
            self.assertAlmostEqual(after[0], car.position[0], places=4)
            self.assertAlmostEqual(after[1], car.position[1], places=4)
