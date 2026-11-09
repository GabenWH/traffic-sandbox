"""Persistent fleet colors are shared by traffic and parking views."""
import unittest
from types import SimpleNamespace

from persistent_fleet import FleetVehicle
from tests.test_parking import fleet_with_shared_lot
from tests.test_parking_layout import block_city
from tests.test_parking_persistence import encode
from city_simulation import CitySimulation
from persistence import world_from_dict


class FleetColorTests(unittest.TestCase):
    def test_assigned_color_follows_a_car_through_two_trips(self):
        fleet = fleet_with_shared_lot()
        self.addCleanup(fleet.transit.traffic._discard_native)
        car = FleetVehicle('red-car', 'car', 'a', color='#c42329')
        fleet.add(car)
        self.assertEqual(next(fleet.parked_vehicles()).color, '#c42329')
        for destination in ('dest', 'a'):
            self.assertTrue(fleet.dispatch(car.id, destination))
            self.assertEqual(car._actor.color, '#c42329')
            fleet.transit.update(100)
            fleet.observe()
            self.assertEqual(car.phase, 'parked')
            self.assertEqual(next(fleet.parked_vehicles()).color, '#c42329')

    def test_reassigning_a_driving_car_updates_its_active_actor(self):
        fleet = fleet_with_shared_lot()
        self.addCleanup(fleet.transit.traffic._discard_native)
        car = FleetVehicle('car', 'car', 'a', color='#c42329')
        fleet.add(car)
        self.assertTrue(fleet.dispatch(car.id, 'dest'))
        car.color = '#2364c4'
        self.assertEqual(car._actor.color, '#2364c4')
        fleet.transit.update(100)
        fleet.observe()
        self.assertEqual(next(fleet.parked_vehicles()).color, '#2364c4')

    def test_default_car_colors_are_varied_and_stable(self):
        colors = [getattr(FleetVehicle(f'car-{i}', 'car', 'a'), 'color', None)
                  for i in range(30)]
        recreated = [getattr(FleetVehicle(f'car-{i}', 'car', 'a'), 'color', None)
                     for i in range(30)]
        self.assertGreater(len(set(colors)), 1)
        self.assertEqual(colors, recreated)

    def test_parked_and_driving_colors_survive_save_and_load(self):
        runtime = CitySimulation(block_city())
        self.addCleanup(runtime.transit.traffic._discard_native)
        car = FleetVehicle('car', 'car', 'a')
        car.color = '#b53870'
        runtime.fleet.add(car)
        restored = CitySimulation(world_from_dict(encode(runtime.city)).city_map)
        self.addCleanup(restored.transit.traffic._discard_native)
        self.assertEqual(getattr(restored.fleet.vehicles['car'], 'color', None), '#b53870')
        self.assertEqual(next(restored.fleet.parked_vehicles()).color, '#b53870')
        self.assertTrue(restored.fleet.dispatch('car', 'c'))
        driving = CitySimulation(world_from_dict(encode(restored.city)).city_map)
        self.addCleanup(driving.transit.traffic._discard_native)
        saved_car = driving.fleet.vehicles['car']
        self.assertEqual(getattr(saved_car, 'color', None), '#b53870')
        self.assertEqual(saved_car._actor.color, '#b53870')

    def test_legacy_inflight_save_adopts_the_active_car_color(self):
        runtime = CitySimulation(block_city())
        self.addCleanup(runtime.transit.traffic._discard_native)
        car = FleetVehicle('legacy-car', 'car', 'a')
        runtime.fleet.add(car)
        self.assertTrue(runtime.fleet.dispatch(car.id, 'c'))
        car._actor.color = '#3159ad'
        saved = encode(runtime.city)
        saved['gameplay']['fleet'][0].pop('color', None)
        restored = CitySimulation(world_from_dict(saved).city_map)
        self.addCleanup(restored.transit.traffic._discard_native)
        legacy = restored.fleet.vehicles[car.id]
        self.assertEqual(getattr(legacy, 'color', None), '#3159ad')
        self.assertEqual(legacy._actor.color, '#3159ad')
        # This fixture has no driver; observe arrival at the fleet boundary.
        restored.transit.arrivals_listener = None
        restored.transit.update(100)
        restored.fleet.observe()
        self.assertEqual(legacy.phase, 'parked')
        self.assertEqual(next(restored.fleet.parked_vehicles()).color, '#3159ad')

    def test_legacy_parked_saves_get_stable_varied_colors(self):
        runtime = CitySimulation(block_city())
        self.addCleanup(runtime.transit.traffic._discard_native)
        for i in range(3):
            runtime.fleet.add(FleetVehicle(f'legacy-{i}', 'car', 'a'))
        saved = encode(runtime.city)
        for car in saved['gameplay']['fleet']:
            car.pop('color', None)
        first = CitySimulation(world_from_dict(saved).city_map)
        second = CitySimulation(world_from_dict(saved).city_map)
        self.addCleanup(first.transit.traffic._discard_native)
        self.addCleanup(second.transit.traffic._discard_native)
        colors = [car.color for car in first.fleet.parked_vehicles()]
        self.assertGreater(len(set(colors)), 1)
        self.assertEqual(colors, [car.color for car in second.fleet.parked_vehicles()])

    def test_native_scene_uploads_and_refreshes_distinct_parked_colors(self):
        from panda3d.core import NodePath, GeomVertexReader
        from color_palette import panda_rgba
        from native_viewer import NativeScene
        from ui.scene_presenter import ScenePresenter

        fleet = fleet_with_shared_lot()
        self.addCleanup(fleet.transit.traffic._discard_native)
        red = FleetVehicle('red', 'car', 'a')
        blue = FleetVehicle('blue', 'car', 'b')
        red.color, blue.color = '#cc2200', '#0033dd'
        fleet.add(red)
        fleet.add(blue)
        city = fleet.transit.city
        city.gameplay = SimpleNamespace(fleet=fleet)
        root = NodePath('root')
        scene = NativeScene(root)
        self.addCleanup(scene.close)
        presenter = ScenePresenter(scene)

        def instance_colors():
            node = root.find('**/parked/**/+GeomNode').node()
            data = node.getGeom(0).getVertexData()
            reader = GeomVertexReader(data, 'instance_color')
            return [tuple(reader.getData4()) for _ in range(data.getArray(1).getNumRows())]

        presenter.update(city, fleet.transit.traffic)
        colors = instance_colors()
        self.assertEqual(len(colors), 2)
        for got, expected in zip(colors, ('#cc2200', '#0033dd')):
            for actual, wanted in zip(got, panda_rgba(expected)):
                self.assertAlmostEqual(actual, wanted, places=5)
        red.color = '#11bb44'
        presenter.update(city, fleet.transit.traffic)
        colors = instance_colors()
        self.assertEqual(len(colors), 2)
        for got, expected in zip(colors, ('#11bb44', '#0033dd')):
            for actual, wanted in zip(got, panda_rgba(expected)):
                self.assertAlmostEqual(actual, wanted, places=5)


if __name__ == '__main__':
    unittest.main()
