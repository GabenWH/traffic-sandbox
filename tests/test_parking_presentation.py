"""Parking views draw the same world-space stalls and vehicle dimensions."""
import importlib.util
import unittest
from types import SimpleNamespace

from parking import ParkingLot, ParkingSpace


class ParkingCanvasTests(unittest.TestCase):
    def test_canvas_renders_lot_stalls_and_both_parked_cars(self):
        from ui.renderer import RendererMixin
        from tests.test_parking import fleet_with_shared_lot
        from persistent_fleet import FleetVehicle
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('one', 'car', 'a', color='#c42329'))
        fleet.add(FleetVehicle('two', 'car', 'b', color='#2364c4'))
        lot = fleet.sites['a']['parking_lot']
        lot.surface = [(85,75),(145,75),(145,125),(85,125)]
        polygons = []
        canvas = SimpleNamespace(create_polygon=lambda *p,**kw:polygons.append((p,kw)), delete=lambda *args:None)
        host = SimpleNamespace(canvas=canvas,city_map=SimpleNamespace(parking_lots=[lot]),
                               city_simulation=SimpleNamespace(fleet=fleet), camera_zoom=1,
                               world_to_screen=lambda point:point,visible_world_bounds=lambda:(0,0,1000,1000))
        self.assertTrue(hasattr(RendererMixin, '_draw_parking_lots'))
        RendererMixin._draw_parking_lots(host)
        RendererMixin._draw_parked_vehicles(host)
        cars = [p for p,kw in polygons if kw.get('tags') == 'parked_vehicles']
        colors = [kw['fill'] for p,kw in polygons if kw.get('tags') == 'parked_vehicles']
        self.assertEqual(len(cars), 2)
        self.assertEqual(colors, ['#c42329', '#2364c4'])
        self.assertTrue(all(len(p) == 8 for p in cars))
        self.assertEqual(max(cars[0][1::2])-min(cars[0][1::2]), 15)
        self.assertEqual(max(cars[0][0::2])-min(cars[0][0::2]), 6)


@unittest.skipUnless(importlib.util.find_spec('panda3d'), 'Panda3D is required')
class ParkingSceneTests(unittest.TestCase):
    def test_persistent_truck_mesh_refreshes_when_parked_cargo_changes(self):
        from panda3d.core import NodePath
        from ui.scene3d import update_road_vehicle_layer
        from tests.test_parking import fleet_with_shared_lot
        from persistent_fleet import FleetVehicle
        fleet = fleet_with_shared_lot()
        truck = FleetVehicle('truck','truck','a',length=28,width=8,capacity=100)
        fleet.add(truck)
        root = NodePath('test')
        nodes = {}
        update_road_vehicle_layer(list(fleet.parked_vehicles()),fleet.transit.city,root,nodes,0)
        self.assertTrue(nodes['truck'].find('**/cargo-stone-0').isEmpty())
        truck.cargo['stone'] = 50
        update_road_vehicle_layer(list(fleet.parked_vehicles()),fleet.transit.city,root,nodes,1)
        self.assertFalse(nodes['truck'].find('**/cargo-stone-0').isEmpty())
        truck.cargo.clear()
        update_road_vehicle_layer(list(fleet.parked_vehicles()),fleet.transit.city,root,nodes,2)
        self.assertTrue(nodes['truck'].find('**/cargo-stone-0').isEmpty())

    def test_three_dimensional_lot_draws_every_stall_and_preserves_car_poses(self):
        from panda3d.core import NodePath
        from ui.scene3d import draw_parking_lot, update_road_vehicle_layer
        from tests.test_parking import fleet_with_shared_lot
        from persistent_fleet import FleetVehicle
        fleet = fleet_with_shared_lot()
        fleet.add(FleetVehicle('one', 'car', 'a'))
        fleet.add(FleetVehicle('two', 'car', 'b'))
        lot = fleet.sites['a']['parking_lot']
        lot.surface = [(85,75),(145,75),(145,125),(85,125)]
        root = NodePath('test')
        node = draw_parking_lot(lot, root)
        self.assertFalse(node.find('**/parking-surface').isEmpty())
        self.assertEqual(node.findAllMatches('**/parking-space:*').getNumPaths(), 3)
        nodes = {}
        parked = list(fleet.parked_vehicles())
        update_road_vehicle_layer(parked, fleet.transit.city, root, nodes, 0)
        self.assertEqual(set(nodes), {'one','two'})
        for car in parked:
            self.assertAlmostEqual(nodes[car.id].getX(), car.position[0])
            self.assertAlmostEqual(nodes[car.id].getY(), car.position[1])
