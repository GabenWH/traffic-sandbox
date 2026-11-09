"""Regression tests for passing around stationary roadside vehicles."""

import unittest

from city import CityMap, Terrain
from mobility import lane_position_at_distance
from traffic_testbed import RoadVehicleSimulation
from truck_stops import LaneObstacle
from vehicle import vehicle_footprints_overlap


class MultilaneObstacleTests(unittest.TestCase):
    def scene(self, mode):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road(
            [(0, 100), (5000, 100)], forward_lane_count=2, reverse_lane_count=2,
        )
        west, east = sorted(city.cul_de_sacs, key=lambda junction: junction.position[0])
        lanes = sorted(
            (lane for lane in road.lanes if lane.direction == 'forward'),
            key=lambda lane: lane.lane_index, reverse=True,
        )
        sim = RoadVehicleSimulation(
            spawn_interval=1000, speed_mph=60, native_output_mode=mode,
        )
        self.addCleanup(sim._discard_native)
        # Bind the real native simulation to the city before admitting routes.
        sim.update(city, 0)
        return city, sim, lanes, west, east

    def admit(self, city, sim, lane, destination, name, distance, speed):
        origin = lane_position_at_distance(lane, distance)
        route = city.find_vehicle_route_between(origin, destination)
        self.assertIsNotNone(route)
        vehicle = sim.admit_route(
            route, vehicle_id=name, source_id='source', destination_id=destination.id,
            speed_cap_mph=speed,
        )
        self.assertIsNotNone(vehicle)
        return vehicle

    def obstacle(self, sim, lane, name, distance, *, length=28, width=8):
        position = lane_position_at_distance(lane, distance)
        sim.set_lane_obstacle(name, position, length=length, width=width)
        # An independent immutable view lets the geometric assertion inspect
        # the same body that was submitted to the native simulation.
        return LaneObstacle(name, position, length, width)

    def test_stopped_vehicle_in_target_lane_blocks_passing_until_it_is_removed(self):
        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                city, sim, (outside, inside), _, east = self.scene(mode)
                slow = self.admit(city, sim, outside, east, 'slow', 700, 20)
                fast = self.admit(city, sim, outside, east, 'fast', 550, 60)
                stopped = self.obstacle(sim, inside, 'stopped-truck', 650)
                initial_x = fast.position[0]

                # The stopped truck is ahead in the would-be passing lane.
                # The faster car must stay in its lane while approaching it.
                for _ in range(15):
                    sim.update(city, .05)
                    self.assertEqual(fast.occupancy_position()[0], ('lane', outside.id))
                    self.assertFalse(vehicle_footprints_overlap(fast, stopped))
                    self.assertFalse(vehicle_footprints_overlap(fast, slow))
                self.assertGreater(fast.position[0], initial_x + 20)
                self.assertGreater(stopped.position[0] - fast.position[0], 35)

                # Removing the blocker confirms this was an actual passing
                # opportunity, not a scene where no lane change was desired.
                self.assertTrue(sim.remove_lane_obstacle(stopped.id))
                for _ in range(100):
                    sim.update(city, .05)
                    if fast.occupancy_position()[0] == ('lane', inside.id):
                        break
                self.assertEqual(fast.occupancy_position()[0], ('lane', inside.id))

    def test_source_lane_stopped_vehicle_still_blocks_during_lane_change(self):
        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                city, sim, (outside, inside), _, east = self.scene(mode)
                stopped = self.obstacle(sim, outside, 'stopped-bus', 650, length=35, width=8)
                # The moving leader alone is enough to trigger a pass.  The
                # stopped bus is closer, so the source lane must still protect
                # the changing car even after its route points to the inside.
                self.admit(city, sim, outside, east, 'slow', 700, 20)
                fast = self.admit(city, sim, outside, east, 'fast', 550, 60)
                outside_y = fast.position[1]
                lane_separation = abs(inside.points[0][1] - outside_y)
                closest_during_change = float('inf')
                changing = False
                passed = False

                for _ in range(400):
                    sim.update(city, .05)
                    self.assertFalse(
                        vehicle_footprints_overlap(fast, stopped),
                        f'car crossed the stopped bus at {fast.position}',
                    )
                    lateral = abs(fast.position[1] - outside_y)
                    if .05 < lateral < lane_separation - .05:
                        changing = True
                        gap = stopped.position[0] - fast.position[0] - (stopped.length + fast.length) / 2
                        closest_during_change = min(closest_during_change, gap)
                    if fast.position[0] > stopped.position[0] + 30:
                        passed = True
                        break

                self.assertTrue(changing, 'the car must actually move between lanes')
                self.assertLess(closest_during_change, 35, 'the transition must approach the source-lane bus')
                self.assertTrue(passed, 'the car should eventually pass the stationary bus')

    def test_stationary_vehicle_resumes_at_its_own_lane_despite_outside_first(self):
        for mode in ('copy', 'shared'):
            for vehicle_id, length, width in (('truck', 28, 8), ('bus', 35, 8)):
                with self.subTest(mode=mode, vehicle=vehicle_id):
                    city, sim, (outside, inside), west, east = self.scene(mode)
                    route = city.find_vehicle_route_between(west, east)
                    self.assertIsNotNone(route)
                    original_lane = next(edge.value for edge in route.edges if edge.kind == 'lane')
                    self.assertEqual(original_lane.id, inside.id)

                    # The identical flexible route normally chooses the other,
                    # outside lane; a returning body must not be reassigned.
                    ordinary = sim.admit_route(
                        route, vehicle_id='ordinary', source_id=west.id, destination_id=east.id,
                    )
                    self.assertIsNotNone(ordinary)
                    self.assertEqual(ordinary.occupancy_position()[0], ('lane', outside.id))
                    sim.remove_vehicle(ordinary.id)

                    stop = lane_position_at_distance(inside, 0)
                    sim.set_lane_obstacle(vehicle_id, stop, length=length, width=width)
                    resumed = sim.admit_route(
                        route, vehicle_id=vehicle_id, source_id=west.id, destination_id=east.id,
                        length=length, width=width,
                    )
                    self.assertIsNotNone(resumed)
                    self.assertEqual(resumed.occupancy_position()[0], ('lane', inside.id))
                    self.assertAlmostEqual(resumed.position[0], stop.point[0], places=7)
                    self.assertAlmostEqual(resumed.position[1], stop.point[1], places=7)
                    self.assertEqual(resumed.speed, 0)
                    sim.update(city, 3)
                    self.assertGreater(resumed.distance, 0)


if __name__ == '__main__':
    unittest.main()
