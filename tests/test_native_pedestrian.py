"""Active people advance inside the same native engine as road vehicles."""
import ctypes as C
import unittest
from native_traffic import NativeTrafficEngine, _Point, _Spawn


class NativePedestrianTests(unittest.TestCase):
    def test_step_moves_active_pedestrian_and_reports_arrival(self):
        with NativeTrafficEngine() as engine:
            lane = engine.register_pedestrian_lane([(0, 0), (44, 0)], crossing_fraction=.5)
            engine.spawn_pedestrian(5, lane, 4.4)
            engine.step(1)
            state = engine.pedestrian_states()[0]
            self.assertEqual(state.id, 5)
            self.assertAlmostEqual(state.distance, 4.4)
            self.assertAlmostEqual(state.x, 4.4)
            engine.step(10)
            self.assertEqual(engine.pedestrian_states(), [])
            self.assertEqual([s.id for s in engine.completed_pedestrians()], [5])

    def test_crossing_waits_for_car_in_same_native_engine(self):
        with NativeTrafficEngine() as engine:
            points = (_Point * 2)(_Point(0,0), _Point(1000,0))
            road = engine._call('nt_route', points, 2, None, 0, None, 0)
            car = _Spawn(0, road, 0, 0, 0, 0, 10, 0, 14, 6, -1, 0, 0, -1)
            engine._call('nt_spawn', C.byref(car), b'test-car', b'', b'')
            lane = engine.register_pedestrian_lane([(0,0), (20,0)], crossing_fraction=.5)
            engine.spawn_pedestrian(5, lane, 4.4)
            engine.step(3)
            state = engine.pedestrian_states()[0]
            self.assertTrue(state.waiting)
            self.assertAlmostEqual(state.distance, 10)
            engine._call('nt_place', 0, 500)
            engine.step(3)
            self.assertEqual([s.id for s in engine.completed_pedestrians()], [5])

    def test_duplicate_ids_and_degenerate_paths_are_rejected(self):
        with NativeTrafficEngine() as engine:
            with self.assertRaises(ValueError):
                engine.register_pedestrian_lane([(1,1),(1,1)])
            lane = engine.register_pedestrian_lane([(0,0),(10,0)])
            engine.spawn_pedestrian(1, lane, 4.4)
            with self.assertRaises(ValueError):
                engine.spawn_pedestrian(1, lane, 4.4)

    def test_city_traffic_update_also_advances_pedestrians(self):
        from city import CityMap, Terrain
        from traffic_testbed import RoadVehicleSimulation
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,0),(300,0)])
        traffic = RoadVehicleSimulation(update_mode='cpp', spawn_interval=1000)
        engine = traffic._native_backend(city).engine
        lane = engine.register_pedestrian_lane([(0, 20), (44, 20)])
        engine.spawn_pedestrian(7, lane, 4.4)
        traffic.update(city, 1)
        self.assertAlmostEqual(engine.pedestrian_states()[0].distance, 4.4)


if __name__ == '__main__':
    unittest.main()
