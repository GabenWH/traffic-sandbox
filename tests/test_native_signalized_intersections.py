"""Signal control behavior through the persistent native traffic engine."""

import unittest

from city import CityMap, Terrain
from intersection_controls import (
    FixedTimeSignalController, SignalPhase, SignalPlan, SignalPlanChange,
    movements_conflict,
)
from models import ControlDefinition, ControlType
from traffic_testbed import RoadVehicleSimulation


def make_scenario(*, plan=None, controller=True, speed=0.0):
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0, 300), (600, 300)])
    city.add_road([(300, 0), (300, 600)])
    traffic = RoadVehicleSimulation(spawn_interval=1000, update_mode="native")
    ends = {junction.position: junction for junction in city.cul_de_sacs}
    car = traffic.spawn_car(city, ends[(0.0, 300.0)], ends[(600.0, 300.0)])
    movement = next(item for item in car.controlled_movements if item[2].maneuver.angle == 0)
    movement[2].control = ControlDefinition(ControlType.SIGNAL, "main")
    if controller and plan is not None:
        traffic.signal_controllers["main"] = FixedTimeSignalController(plan)
    car.distance = movement[0] - car.length / 2
    car.speed = speed
    car.advance(0.0)
    return city, traffic, car, movement


class NativeSignalTests(unittest.TestCase):
    def test_red_blocks_and_green_admits_without_a_vehicle_claim(self):
        city, red_traffic, red_car, (start, _, movement) = make_scenario(controller=False)
        red_traffic.signal_controllers["main"] = FixedTimeSignalController(SignalPlan((
            SignalPhase(60.0, {"other"}, 0.0, 0.0),
        )))
        red_traffic.update(city, 0.05)
        self.assertLessEqual(red_car.distance + red_car.length / 2, start + 1e-7)
        self.assertEqual(red_car.brain.wait_reason, "red signal")
        self.assertIsNone(red_car.claimed_movement)

        city, green_traffic, green_car, (start, _, movement) = make_scenario(controller=False)
        green_traffic.signal_controllers["main"] = FixedTimeSignalController(SignalPlan((
            SignalPhase(60.0, {movement.id}, 0.0, 0.0),
        )))
        green_traffic.update(city, 0.05)
        self.assertGreater(green_car.distance + green_car.length / 2, start)
        self.assertIsNone(green_car.claimed_movement)

    def test_missing_controller_fails_closed(self):
        city, traffic, car, (start, _, _) = make_scenario(controller=False)
        traffic.update(city, 0.05)
        self.assertLessEqual(car.distance + car.length / 2, start + 1e-7)
        self.assertEqual(car.brain.wait_reason, "red signal")

    def test_signal_body_continues_through_yellow_and_all_red(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        traffic = RoadVehicleSimulation(spawn_interval=1000, update_mode="native")
        ends = {junction.position: junction for junction in city.cul_de_sacs}
        car = traffic.spawn_car(city, ends[(0.0, 300.0)], ends[(600.0, 300.0)])
        start, end, movement = next(
            item for item in car.controlled_movements if item[2].maneuver.angle == 0
        )
        movement.control = ControlDefinition(ControlType.SIGNAL, "main")
        traffic.signal_controllers["main"] = FixedTimeSignalController(SignalPlan((
            SignalPhase(0.05, {movement.id}, 0.05, 0.1),
        )))
        car.distance, car.speed = start - car.length / 2, 10.0
        car.advance(0.0)

        traffic.update(city, 0.05)
        self.assertIn((car.id, movement.id), traffic.stop_coordinator.signal_occupants)
        before_clearance = car.distance
        traffic.update(city, 0.1)
        self.assertGreater(car.distance, before_clearance)
        self.assertIsNone(car.claimed_movement)
        self.assertIn((car.id, movement.id), traffic.stop_coordinator.signal_occupants)
        self.assertLess(car.distance - car.length / 2, end)
        aspect_index = traffic._native_controller.engine._connection_ids[id(movement)]
        self.assertEqual(traffic._native_controller.engine._signal_aspects[aspect_index], 0)

    def test_scheduled_plan_change_updates_native_aspect_after_clearance(self):
        city, traffic, car, (start, _, movement) = make_scenario(controller=False)
        initial = SignalPlan((SignalPhase(0.05, {movement.id}, 0.05, 0.05),))
        changed = SignalPlan((SignalPhase(60.0, {"other"}, 0.0, 0.0),))
        traffic.signal_controllers["main"] = FixedTimeSignalController(
            initial, (SignalPlanChange(0.05, changed),),
        )
        for _ in range(3):
            traffic.update(city, 0.05)
        self.assertAlmostEqual(traffic.elapsed_time, 0.15)
        self.assertGreater(car.distance + car.length / 2, start)
        aspect_index = traffic._native_controller.engine._connection_ids[id(movement)]
        self.assertEqual(traffic._native_controller.engine._signal_aspects[aspect_index], 0)
        self.assertIsNone(car.claimed_movement)

    def test_conflicting_green_waits_for_physical_signal_body_to_clear(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        traffic = RoadVehicleSimulation(spawn_interval=1000, update_mode="native")
        ends = {junction.position: junction for junction in city.cul_de_sacs}
        horizontal = traffic.spawn_car(city, ends[(0.0, 300.0)], ends[(600.0, 300.0)])
        vertical = traffic.spawn_car(city, ends[(300.0, 0.0)], ends[(300.0, 600.0)])
        horizontal_movement = next(item for item in horizontal.controlled_movements
                                   if item[2].maneuver.angle == 0)
        vertical_movement = next(item for item in vertical.controlled_movements
                                 if item[2].maneuver.angle == 0)
        h_start, _, h_connection = horizontal_movement
        v_start, _, v_connection = vertical_movement
        self.assertTrue(movements_conflict(h_connection, v_connection))
        h_connection.control = ControlDefinition(ControlType.SIGNAL, "main")
        v_connection.control = ControlDefinition(ControlType.SIGNAL, "main")
        horizontal.distance, horizontal.speed = h_start - horizontal.length / 2, 10.0
        vertical.distance, vertical.speed = v_start - vertical.length / 2, 0.0
        horizontal.advance(0.0)
        vertical.advance(0.0)
        traffic.signal_controllers["main"] = FixedTimeSignalController(SignalPlan((
            SignalPhase(0.05, {h_connection.id}, 0.05, 0.05),
            SignalPhase(60.0, {v_connection.id}, 0.0, 0.0),
        )))

        traffic.update(city, 0.05)
        self.assertIn((horizontal.id, h_connection.id), traffic.stop_coordinator.signal_occupants)
        traffic.update(city, 0.1)
        held_distance = vertical.distance
        traffic.update(city, 0.05)
        self.assertAlmostEqual(vertical.distance, held_distance)
        self.assertEqual(vertical.brain.wait_reason, "waiting for conflicting traffic")
        self.assertIsNone(vertical.claimed_movement)

    def test_native_abi_rejects_conflicting_protected_aspects(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        traffic = RoadVehicleSimulation(spawn_interval=1000, update_mode="native")
        ends = {junction.position: junction for junction in city.cul_de_sacs}
        horizontal = traffic.spawn_car(city, ends[(0.0, 300.0)], ends[(600.0, 300.0)])
        vertical = traffic.spawn_car(city, ends[(300.0, 0.0)], ends[(300.0, 600.0)])
        h = next(item[2] for item in horizontal.controlled_movements if item[2].maneuver.angle == 0)
        v = next(item[2] for item in vertical.controlled_movements if item[2].maneuver.angle == 0)
        h.control = ControlDefinition(ControlType.SIGNAL, "main")
        v.control = ControlDefinition(ControlType.SIGNAL, "main")
        horizontal.advance(0.0)
        vertical.advance(0.0)
        traffic.signal_controllers["main"] = FixedTimeSignalController(SignalPlan((
            SignalPhase(60.0, {h.id}, 0.0, 0.0),
        )))
        traffic.update(city, 0.0)
        engine = traffic._native_controller.engine
        aspects = list(engine._signal_aspects)
        aspects[engine._connection_ids[id(h)]] = 1
        aspects[engine._connection_ids[id(v)]] = 1
        with self.assertRaisesRegex(ValueError, "conflicting protected signal permissions"):
            engine.set_signal_aspects(aspects)

    def test_deadlock_recovery_does_not_override_red(self):
        plan = SignalPlan((SignalPhase(60.0, {"other"}, 0.0, 0.0),))
        city, traffic, car, (start, _, _) = make_scenario(plan=plan)
        for _ in range(140):
            traffic.update(city, 0.05)
        self.assertLessEqual(car.distance + car.length / 2, start + 1e-7)
        self.assertEqual(car.brain.wait_reason, "red signal")
        self.assertIsNone(car.claimed_movement)


if __name__ == "__main__":
    unittest.main()
