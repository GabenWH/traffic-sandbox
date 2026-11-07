"""Delivery accounting and saved stationary occupancy use one truck identity."""
import unittest
from math import dist

from city_simulation import CitySimulation
from mobility import lane_position_at_distance
from persistence import world_from_dict
from test_background_city import saved_world
from test_city_gameplay import neighborhood


class TruckStopGameplayTests(unittest.TestCase):
    def make_delivery(self):
        runtime, home, other, cafe, bakery, market = neighborhood()
        self.addCleanup(runtime.close)
        truck = runtime.commission_truck(bakery.id)
        lot = runtime.sites[home.id]['parking_lot']
        lot.spaces[:] = [space for space in lot.spaces if not space.fits(truck.length,truck.width)]
        runtime.sites[home.id]['parking_capacity'] = lot.capacity
        runtime.fleet.notify_parking_changed(home.id)
        truck.cargo['food'] = 10.
        runtime.initial_resources += 10.
        runtime.jobs[truck.id] = dict(source=bakery.id, destination=home.id,
            resource='food', amount=10., reserved=0., stage='outbound')
        self.assertTrue(runtime.fleet.dispatch(truck.id, home.id))
        for _ in range(6000):
            runtime.update(.05)
            if truck.road_stop_lane_id is not None:
                break
        self.assertIsNotNone(truck.road_stop_lane_id)
        self.assertIn(truck.phase, ('queued_handling','handling'))
        return runtime, home, bakery, truck

    def test_delivery_stop_survives_save_and_unloads_once_before_returning(self):
        runtime, home, source, truck = self.make_delivery()
        restored = CitySimulation(world_from_dict(saved_world(runtime)).city_map)
        self.addCleanup(restored.close)
        saved_truck = restored.fleet.vehicles[truck.id]
        self.assertEqual(saved_truck.road_stop_position, truck.road_stop_position)
        position = restored.fleet._road_stop_position(saved_truck)
        end = lane_position_at_distance(position.lane, position.distance+20)
        route = restored.city.find_vehicle_route_between(position, end)
        self.assertIsNotNone(route)
        self.assertIsNone(restored.transit.traffic.admit_route(route, vehicle_id='overlap',
            source_id=home.id, destination_id=source.id, length=15, width=6))
        restored.update(400)
        self.assertEqual(restored.deliveries, 1)
        self.assertEqual(restored.sites[home.id]['building'].inventory.amounts.get('food'), 10.)
        self.assertEqual(saved_truck.site, source.id)
        self.assertEqual(saved_truck.phase, 'parked')
        self.assertIsNone(saved_truck.road_stop_lane_id)
        self.assertEqual(saved_truck.trips, 2)
        self.assertAlmostEqual(restored.report()['resource_balance_error'], 0)

    def test_removed_stop_road_preserves_physical_pose_and_saved_cargo(self):
        runtime, home, source, truck = self.make_delivery()
        point = truck.road_stop_position
        runtime.city.roads.clear()
        runtime.city.rebuild_mobility_network()
        runtime.sync_network()
        self.assertEqual(truck.road_stop_position, point)
        rendered = next(v for v in runtime.fleet.parked_vehicles() if v.id==truck.id)
        self.assertLess(dist(rendered.position, point), 1e-8)
        restored = CitySimulation(world_from_dict(saved_world(runtime)).city_map)
        self.addCleanup(restored.close)
        saved_truck = restored.fleet.vehicles[truck.id]
        self.assertEqual(saved_truck.road_stop_position, point)
        self.assertEqual(saved_truck.cargo, {'food':10.})
        saved_truck.phase = 'parked'
        self.assertFalse(restored.fleet.dispatch(truck.id, source.id))
        self.assertEqual(restored.fleet.last_dispatch_status, 'inaccessible')
        self.assertEqual(saved_truck.road_stop_position, point)


if __name__ == '__main__':
    unittest.main()
