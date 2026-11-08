"""Loading trucks retain a physical lane body without becoming moving actors."""
import unittest

from city import CityMap, Terrain
from mobility import lane_position_at_distance
from models import Lane, polyline_length
from traffic_testbed import RoadVehicleSimulation
from transit import TransitSimulation
from truck_stops import loading_position
from vehicle import vehicle_footprints_overlap


class LoadingPositionTests(unittest.TestCase):
    def position(self, points, distance):
        lane = Lane('loading lane', points, points[-1])
        return lane_position_at_distance(lane, distance)

    def test_loading_body_clears_interior_bends_and_lane_ends(self):
        points = [(0, 0), (100, 0), (100, 100)]
        for requested, expected in ((5, 18), (80, 80), (90, 82), (111, 118), (195, 182)):
            with self.subTest(requested=requested):
                position = self.position(points, requested)
                selected = loading_position(position, 28)
                self.assertIsNotNone(selected)
                self.assertIs(selected.lane, position.lane)
                self.assertEqual(selected.distance, expected)

    def test_collinear_vertices_and_duplicate_points_do_not_split_a_straight_run(self):
        position = self.position([(0, 0), (10, 0), (10, 0), (20, 0), (30, 0), (100, 0)], 25)
        self.assertEqual(loading_position(position, 28).distance, 25)

    def test_tightly_bent_lane_without_a_fitting_straight_run_has_no_loading_stop(self):
        position = self.position([(0, 0), (20, 0), (20, 20), (40, 20)], 30)
        self.assertIsNone(loading_position(position, 28))

    def test_relocation_is_limited_to_one_truck_length_plus_eight_feet(self):
        points = [(0, 0), (100, 0), (100, 20), (120, 20),
                  (120, 40), (140, 40), (140, 60), (240, 60)]
        self.assertIsNone(loading_position(self.position(points, 150), 28))
        self.assertIsNone(loading_position(self.position(points, 181), 28))
        self.assertEqual(loading_position(self.position(points, 182), 28).distance, 218)


class TruckStopTests(unittest.TestCase):
    def setUp(self):
        self.city = CityMap(terrain=Terrain(trees=[]))
        self.road = self.city.add_road([(0, 100), (1200, 100)])
        self.lane = self.road.lanes[0]
        self.traffic = RoadVehicleSimulation(spawn_interval=10000)
        self.transit = TransitSimulation(self.city, self.traffic)
        self.addCleanup(lambda: self.traffic._discard_native())

    def position(self, distance, lane=None):
        return lane_position_at_distance(lane or self.lane, distance)

    def admit(self, name, start, end, *, lane=None, length=14, width=6):
        route = self.city.find_vehicle_route_between(
            self.position(start, lane), self.position(end, lane))
        self.assertIsNotNone(route)
        return self.traffic.admit_route(route, vehicle_id=name,
            source_id='source', destination_id='destination',
            length=length, width=width)

    def stop_on_arrival(self, vehicle_id):
        operation = getattr(self.traffic, 'stop_vehicle_at_route_end', None)
        self.assertIsNotNone(operation, 'Traffic must retain the truck body at route completion')
        operation(vehicle_id)

    def obstacle(self, name, distance, *, lane=None, length=28, width=8):
        operation = getattr(self.traffic, 'set_lane_obstacle', None)
        self.assertIsNotNone(operation, 'Traffic must restore stationary loading bodies')
        operation(name, self.position(distance, lane), length=length, width=width)

    def test_arriving_truck_blocks_follower_before_outer_arrival_observation(self):
        self.traffic.clear_vehicles()
        truck = self.admit('truck', 100, 400, length=28, width=8)
        self.assertIsNotNone(truck)
        self.stop_on_arrival(truck.id)
        follower = self.admit('follower', 40, 1000)
        self.assertIsNotNone(follower)
        # No fleet observer runs during this call. The native stop must
        # exist before the following driver advances another substep.
        completed = self.traffic.update(self.city, 40)
        self.assertEqual([car.id for car in completed], ['truck'])
        self.assertEqual([car.id for car in self.traffic.cars], ['follower'])
        self.assertAlmostEqual(truck.position[0], self.position(400).point[0], places=7)
        self.assertAlmostEqual(truck.position[1], self.position(400).point[1], places=7)
        self.assertLessEqual(follower.distance, 335.000001)
        self.assertEqual(follower.speed, 0)
        self.assertGreaterEqual(400 - (40 + follower.distance) - 21, 4 - 1e-7)
        # The optional Python occupancy view agrees with native traffic.
        self.traffic._ensure_occupancy()
        leader, gap = self.traffic.occupancy.lead_car_gap(follower, 128)
        self.assertEqual(leader.id, 'truck')
        self.assertGreaterEqual(gap, 4 - 1e-7)
        self.traffic.clear_vehicles()
    def test_native_substeps_retain_loading_body_without_python_callbacks(self):
        truck = self.admit('truck', 100, 400, length=28, width=8)
        self.stop_on_arrival(truck.id)
        self.assertIsNotNone(self.admit('follower', 40, 1000))
        engine = self.traffic._native_backend(self.city).engine
        engine.step(40)
        states = engine.snapshot(include_completed=True)
        self.assertEqual(states['truck'].alive, 0)
        self.assertEqual(states['follower'].alive, 1)
        self.assertLessEqual(states['follower'].distance, 335.000001)
        self.assertEqual(states['follower'].speed, 0)

    def test_rejected_departure_keeps_blocker_until_same_pose_admission_succeeds(self):
        self.obstacle('truck', 400)
        self.obstacle('ahead', 440)
        self.assertIsNone(self.admit('truck', 400, 1000, length=28, width=8))
        self.assertIsNone(self.admit('interloper', 400, 1000))
        self.traffic.remove_lane_obstacle('ahead')
        self.assertIsNone(self.admit('truck', 500, 1000, length=28, width=8),
                          'A parked truck cannot teleport to a different access point')
        self.assertIsNone(self.admit('interloper', 400, 1000))
        truck = self.admit('truck', 400, 1000, length=28, width=8)
        self.assertIsNotNone(truck)
        self.assertEqual(truck.position, self.position(400).point)
        self.assertEqual(truck.speed, 0)
        self.traffic.update(self.city, 3)
        self.assertGreater(truck.distance, 0)
        self.traffic.remove_vehicle('truck')
        self.assertIsNotNone(self.admit('replacement', 400, 1000),
                             'Successful departure must consume the old stationary body')

    def test_failed_obstacle_update_preserves_previous_physical_body(self):
        self.obstacle('truck', 400)
        moving = self.admit('moving', 700, 1000)
        self.assertIsNotNone(moving)
        with self.assertRaises(ValueError):
            self.obstacle('truck', 700)
        self.assertIsNone(self.admit('overlap', 400, 1000))
        self.traffic.remove_vehicle('moving')
        self.assertIsNotNone(self.admit('free', 700, 1000))

    def test_stationary_truck_does_not_block_parallel_lane_or_use_driver_visits(self):
        self.obstacle('truck', 400)
        other_lane = self.road.lanes[1]
        car = self.admit('passing', 100, 900, lane=other_lane)
        self.assertIsNotNone(car)
        completed = self.traffic.update(self.city, 40)
        self.assertEqual([v.id for v in completed], ['passing'])
        engine = self.traffic._native_backend(self.city).engine
        before = engine.profile_snapshot()
        self.traffic.update(self.city, 2)
        after = engine.profile_snapshot()
        self.assertEqual(after['vehicle_visits'], before['vehicle_visits'])
        self.assertEqual(len(self.traffic.cars), 0)
        self.assertIsNone(self.admit('still_blocked', 400, 1000))

    def test_obstacle_survives_native_view_rebuild(self):
        self.obstacle('truck', 400)
        self.traffic.native_output_mode = 'shared'
        self.assertIsNone(self.admit('overlap', 400, 1000))
        self.assertIsNotNone(self.admit('truck', 400, 1000, length=28, width=8))

    def test_stop_at_lane_corner_can_resume_along_the_same_lane(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 100), (600, 100), (600, 700)])
        lane = road.lanes[0]
        traffic = RoadVehicleSimulation(spawn_interval=10000)
        traffic.sync_network(city)
        self.addCleanup(traffic._discard_native)
        corner_distance = polyline_length(lane.points[:2])
        corner = lane_position_at_distance(lane, corner_distance)
        route = city.find_vehicle_route_between(lane_position_at_distance(lane, 100), corner)
        truck = traffic.admit_route(route, vehicle_id='truck', source_id='a',
                                    destination_id='b', length=28, width=8)
        traffic.stop_vehicle_at_route_end('truck')
        traffic.update(city, 40)
        traffic.set_lane_obstacle('truck', corner, length=28, width=8, heading=truck.heading)
        route = city.find_vehicle_route_between(corner,
            lane_position_at_distance(lane, corner_distance + 200))
        departing = traffic.admit_route(route, vehicle_id='truck', source_id='b',
                                        destination_id='c', length=28, width=8)
        self.assertIsNotNone(departing, 'The next segment heading is a valid continuation at a corner')
        self.assertEqual(departing.position, truck.position)
        self.assertEqual(departing.speed, 0)
        self.assertGreater(departing.heading[1], .99)

    def test_reordering_active_cars_keeps_stationary_occupancy_queryable(self):
        self.obstacle('truck', 400)
        follower = self.admit('follower', 350, 1000)
        self.assertIsNotNone(follower)
        self.assertIsNotNone(self.admit('other', 100, 900, lane=self.road.lanes[1]))
        self.traffic._ensure_occupancy()
        self.traffic.reorder_vehicles(['other', 'follower'])
        leader = self.traffic.occupancy.lead_car_gap(follower, 128)
        self.assertIsNotNone(leader)
        self.assertEqual(leader[0].id, 'truck')

    def test_invalid_restored_heading_keeps_existing_lane_body(self):
        self.obstacle('truck', 400)
        with self.assertRaises(ValueError):
            self.traffic.set_lane_obstacle('truck', self.position(400),
                length=28, width=8, heading=(0, 1))
        self.assertIsNone(self.admit('overlap', 400, 1000))

    def test_truck_downstream_holds_crossing_traffic_before_the_junction(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        traffic = RoadVehicleSimulation(spawn_interval=10000)
        self.addCleanup(traffic._discard_native)
        ends = {junction.position: junction for junction in city.cul_de_sacs}
        car = traffic.spawn_car(city, ends[(0., 300.)], ends[(600., 300.)])
        start, _, movement = next(item for item in car.controlled_movements
                                   if item[2].maneuver.angle == 0)
        destination_lane = next(edge.value for edge in car.route.edges
            if edge.kind == 'lane' and edge.value.points[0][0] > 300)
        traffic.set_lane_obstacle('truck', lane_position_at_distance(destination_lane, 18),
                                  length=28, width=8)
        cross = traffic.spawn_car(city, ends[(300., 0.)], ends[(300., 600.)])
        completed = traffic.update(city, 40)
        self.assertIn(cross.id, {v.id for v in completed})
        self.assertLessEqual(car.distance + car.length / 2, start + 1e-7)
        self.assertFalse(traffic.stop_coordinator.has_claim(car.id, movement))
        traffic.remove_lane_obstacle('truck')
        completed = traffic.update(city, 40)
        self.assertIn(car.id, {v.id for v in completed})

    def test_fleet_loading_stop_near_bend_does_not_overlap_opposite_lane_traffic(self):
        from parking import ParkingLot, ParkingSpace
        from persistent_fleet import FleetVehicle, PersistentFleet
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(100, 100), (600, 100), (600, 700)])
        lane, opposite_lane = road.lanes
        corner = polyline_length(lane.points[:2])
        origin = ParkingLot('origin', [ParkingSpace('truck-bay', (200, 180), length=32, width=12)])
        destination = ParkingLot('destination', [ParkingSpace('small-bay', (650, 180))])
        sites = {name: dict(parking_lot=lot, parking_capacity=1,
                           road_position=lane_position_at_distance(lane, distance))
                 for name, lot, distance in (('origin', origin, 100), ('destination', destination, corner))}
        fleet = PersistentFleet(TransitSimulation(city), sites)
        self.addCleanup(fleet.transit.traffic._discard_native)
        truck = FleetVehicle('truck', 'truck', 'origin', length=28, width=8)
        fleet.add(truck)
        self.assertTrue(fleet.dispatch('truck', 'destination'))
        fleet.transit.update(40)
        fleet.observe()
        self.assertEqual(truck.phase, 'parked')
        self.assertEqual(truck.road_stop_lane_id, lane.id)
        stopped = next(fleet.parked_vehicles())
        route = city.find_vehicle_route_between(lane_position_at_distance(opposite_lane, 100),
                                               lane_position_at_distance(opposite_lane, 1000))
        car = fleet.transit.traffic.admit_route(route, vehicle_id='opposite', source_id='east',
            destination_id='west', length=14, width=6)
        self.assertIsNotNone(car)
        completed = False
        for _ in range(1600):
            fleet.transit.update(.025)
            self.assertFalse(vehicle_footprints_overlap(stopped, car),
                f'Opposite-lane car intersected loading truck at {fleet.transit.time:.3f}s')
            if car not in fleet.transit.traffic.cars:
                completed = True
                break
        self.assertTrue(completed, 'Moving the loading stop must leave the opposite lane passable')
        self.assertGreaterEqual(abs(truck.road_stop_distance-corner), 18-1e-7)


if __name__ == '__main__':
    unittest.main()
