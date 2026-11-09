"""Lane changes must not invalidate gameplay mileage, learning, or presentation."""
import unittest

import numpy as np

from city import CityMap, Terrain
from commute_routing import BackgroundRoutes
from mobility import lane_position_at_distance
from models import polyline_length
from persistent_fleet import FleetVehicle, PersistentFleet
from route_learning import TravelLearning
import tests.test_multilane as multilane
from traffic_testbed import RoadVehicleSimulation
from transit import Bus, BusLine, BusStop, TransitSimulation
from ui.scene_presenter import ScenePresenter


class LaneSpecificRoutes(BackgroundRoutes):
    """Use the real router with exact access lanes for a reproducible pass."""

    def __init__(self, city, start_lane, end_lane):
        super().__init__(city, speed_mph=60)
        self.start_lane, self.end_lane = start_lane, end_lane

    def get_route(self, vehicle, origin, destination, origins, targets, **kwargs):
        return super().get_route(
            vehicle, origin, destination,
            [p for p in origins if p.lane is self.start_lane],
            [p for p in targets if p.lane is self.end_lane], **kwargs,
        )


class RecordingScene:
    def __init__(self):
        self.heights = {}

    def clear_metadata(self):
        self.heights.clear()

    def register_vehicle(self, handle, appearance, length, width, color, heights):
        self.heights[handle] = np.array(heights, copy=True)

    def update_native(self, engine, elapsed):
        pass

    def replace_parked(self, rows):
        pass


class MultilaneGameplayIntegrationTests(unittest.TestCase):
    def passing_scene(self, mode):
        city = CityMap(terrain=Terrain(trees=[]))
        roads = [city.add_road([(a, 100), (b, 100)],
                               elevations=elevations,
                               forward_lane_count=count, reverse_lane_count=count)
                 for a, b, count, elevations in (
                     (0, 3000, 2, [0, 30]),
                     (3000, 3500, 1, [30, 30]),
                     (3500, 7000, 2, [30, 30]))]
        traffic = RoadVehicleSimulation(spawn_interval=1000, speed_mph=60,
                                        native_output_mode=mode)
        traffic._native_backend(city)
        self.addCleanup(traffic._discard_native)
        outer = next(l for l in roads[0].lanes if l.direction == 'forward' and l.lane_index == 1)
        inner = next(l for l in roads[0].lanes if l.direction == 'forward' and l.lane_index == 0)
        last = next(l for l in roads[2].lanes if l.direction == 'forward' and l.lane_index == 0)
        start = lane_position_at_distance(outer, 550)
        destination = lane_position_at_distance(last, 2500)
        east = max(city.cul_de_sacs, key=lambda j: j.position[0])
        slow_x = lane_position_at_distance(outer, 700).point[0]
        slow = multilane.PassingTests().admit(city, traffic, outer, east, 'slow', slow_x, 20)
        return city, traffic, roads[0], outer, inner, start, destination, slow

    def fleet_scene(self, mode):
        city, traffic, road, outer, inner, start, destination, slow = self.passing_scene(mode)
        transit = TransitSimulation(city, traffic)
        sites = {'home': {'road_position': start, 'parking_capacity': 2},
                 'work': {'road_position': destination, 'parking_capacity': 2}}
        fleet = PersistentFleet(transit, sites)
        fleet.routing = LaneSpecificRoutes(city, outer, destination.lane)
        self.addCleanup(fleet.routing.close)
        vehicle = FleetVehicle('fast', 'car', 'home')
        fleet.add(vehicle)
        self.assertTrue(fleet.dispatch(vehicle.id, 'work'))
        self.assertAlmostEqual(vehicle._actor.position[0], start.point[0])
        return transit, fleet, vehicle, inner, start, slow

    def bus_scene(self, mode):
        city, traffic, road, outer, inner, start, destination, slow = self.passing_scene(mode)
        transit = TransitSimulation(city, traffic)
        transit.add_stop(BusStop('A', start, start.point))
        transit.add_stop(BusStop('B', destination, destination.point))
        transit.add_line(BusLine('L', ('A', 'B'), dwell_seconds=0))
        bus = Bus('fast', 'L', fuel_liters=100)
        transit.add_bus(bus)
        return transit, bus, start, slow

    def drive_until_return(self, transit, vehicle, actor, start, slow, fleet=None):
        went_left = False
        for _ in range(800):
            transit.update(.05)
            if fleet is not None:
                fleet.observe()
            went_left |= actor.position[1] < start.point[1] - 9
            if (went_left and actor.position[0] > slow.position[0] + 30
                    and abs(actor.position[1] - start.point[1]) < .1):
                return actor.position[0] - start.point[0]
        self.fail('vehicle did not pass and return to the original lane')

    def test_fleet_odometer_and_fuel_measure_only_travel_through_pass(self):
        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                transit, fleet, vehicle, _, start, slow = self.fleet_scene(mode)
                traveled = self.drive_until_return(transit, vehicle, vehicle._actor, start, slow, fleet)
                with self.subTest(measure='odometer'):
                    self.assertAlmostEqual(vehicle.distance_feet, traveled, delta=.1)
                with self.subTest(measure='fuel'):
                    self.assertAlmostEqual(vehicle.fuel_liters,
                                           50 - traveled / 5280 * vehicle.liters_per_mile,
                                           delta=1e-7)

    def test_bus_odometer_and_fuel_measure_only_travel_through_pass(self):
        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                transit, bus, start, slow = self.bus_scene(mode)
                transit.update(.05)
                self.assertEqual(bus.phase, 'driving')
                traveled = self.drive_until_return(transit, bus, bus._car, start, slow)
                with self.subTest(measure='odometer'):
                    self.assertAlmostEqual(bus.distance_feet, traveled, delta=.1)
                with self.subTest(measure='fuel'):
                    self.assertAlmostEqual(bus.fuel_liters,
                                           100 - traveled / 5280 * bus.liters_per_mile,
                                           delta=1e-7)

    def test_fleet_learning_tracks_new_lane_after_native_route_change(self):
        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                transit, fleet, vehicle, inner, _, _ = self.fleet_scene(mode)
                actor, original_route = vehicle._actor, vehicle._actor.route
                for _ in range(100):
                    transit.update(.05)
                    fleet.observe()
                    if actor.route is not original_route:
                        break
                else:
                    self.fail('vehicle did not change lanes')
                self.assertEqual(actor.occupancy_position()[0], ('lane', inner.id))
                self.assertEqual(fleet.routing.learning.affected_vehicles('lane:' + inner.id),
                                 {vehicle.id})

    def test_lane_changes_learn_full_lane_costs_from_partial_traversals(self):
        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                city = CityMap(terrain=Terrain(trees=[]))
                roads = [city.add_road([(a, 100), (b, 100)],
                                       forward_lane_count=count, reverse_lane_count=count)
                         for a, b, count in ((0, 5000, 2), (5000, 5500, 1),
                                             (5500, 9000, 2))]
                outer = next(l for l in roads[0].lanes
                             if l.direction == 'forward' and l.lane_index == 1)
                inner = next(l for l in roads[0].lanes
                             if l.direction == 'forward' and l.lane_index == 0)
                last = next(l for l in roads[2].lanes
                            if l.direction == 'forward' and l.lane_index == 0)
                start = lane_position_at_distance(outer, 0)
                destination = lane_position_at_distance(last, 1500)
                traffic = RoadVehicleSimulation(spawn_interval=1000, speed_mph=60,
                                                native_output_mode=mode)
                transit = TransitSimulation(city, traffic)
                self.addCleanup(traffic._discard_native)
                fleet = PersistentFleet(transit, {
                    'home': {'road_position': start, 'parking_capacity': 2},
                    'work': {'road_position': destination, 'parking_capacity': 2}})
                fleet.routing = LaneSpecificRoutes(city, outer, last)
                self.addCleanup(fleet.routing.close)
                vehicle = FleetVehicle('fast', 'car', 'home')
                fleet.add(vehicle)
                self.assertTrue(fleet.dispatch(vehicle.id, 'work'))
                actor = vehicle._actor

                # Observe substantial uninterrupted travel before introducing
                # the slower car; the first lane change must not be at spawn.
                for _ in range(400):
                    transit.update(.05)
                    fleet.observe()
                self.assertGreater(actor.position[0] - start.point[0], 1600)
                self.assertEqual(actor.occupancy_position()[0], ('lane', outer.id))
                east = max(city.cul_de_sacs, key=lambda j: j.position[0])
                multilane.PassingTests().admit(city, traffic, outer, east, 'slow',
                                              actor.position[0] + 150, 20)

                went_left = returned = False
                for _ in range(1000):
                    transit.update(.05)
                    fleet.observe()
                    lane = actor.occupancy_position()[0]
                    went_left |= lane == ('lane', inner.id)
                    returned |= went_left and lane == ('lane', outer.id)
                    if actor.position[0] > 5000:
                        break
                else:
                    self.fail('vehicle did not clear the first road')
                self.assertTrue(went_left and returned, 'scenario must pass and return')

                costs = fleet.routing.learning.costs_for(1)
                with self.subTest(lane='outer'):
                    cost = costs['lane:' + outer.id]
                    # At a 60 mph cap, traversing the complete lane cannot
                    # take less than its length / 88 ft per second.
                    fastest = polyline_length(outer.points) / 88
                    self.assertGreaterEqual(cost, fastest - .5)
                    self.assertLess(cost, 150)
                with self.subTest(lane='inner'):
                    self.assertIn('lane:' + inner.id, costs)

    def test_fleet_learning_tracks_the_lane_selected_at_flexible_admission(self):
        class JunctionRoute:
            def __init__(self, route):
                self.route = route
                self.learning = TravelLearning()

            def get_route(self, *args, **kwargs):
                return self.route

        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                city, road, west, east = multilane.straight_city(lanes=2, reverse=2, length=5000)
                traffic = RoadVehicleSimulation(spawn_interval=1000, speed_mph=60,
                                                native_output_mode=mode)
                transit = TransitSimulation(city, traffic)
                self.addCleanup(traffic._discard_native)
                requested = city.find_vehicle_route_between(west, east)
                requested_lane = next(e.value for e in requested.edges if e.kind == 'lane')
                requested_lane = getattr(requested_lane, 'lane', requested_lane)
                origin = lane_position_at_distance(requested_lane, 0)
                destination = lane_position_at_distance(requested_lane, 2000)
                fleet = PersistentFleet(transit, {
                    'home': {'road_position': origin, 'parking_capacity': 1},
                    'work': {'road_position': destination, 'parking_capacity': 1}})
                fleet.routing = JunctionRoute(requested)
                vehicle = FleetVehicle('fast', 'car', 'home')
                fleet.add(vehicle)
                self.assertTrue(fleet.dispatch(vehicle.id, 'work'))
                actual_lane = multilane.first_lane(vehicle._actor)
                actual_lane = getattr(actual_lane, 'lane', actual_lane)
                self.assertNotEqual(actual_lane.id, requested_lane.id)
                self.assertEqual(fleet.routing.learning.affected_vehicles('lane:' + actual_lane.id),
                                 {vehicle.id})
                self.assertNotIn(vehicle.id, fleet.routing.learning.affected_vehicles(
                    'lane:' + requested_lane.id))

    def test_presenter_refreshes_route_heights_without_roster_change(self):
        city, traffic, road, outer, inner, start, destination, _ = self.passing_scene('shared')
        route = city.find_vehicle_route_between(start, destination)
        actor = traffic.admit_route(route, vehicle_id='fast', source_id='A',
                                    destination_id='B', speed_cap_mph=60)
        self.assertIsNotNone(actor)
        scene = RecordingScene()
        presenter = ScenePresenter(scene)
        presenter.update(city, traffic)
        handle = traffic._native_backend(city).engine._handles[actor.id]
        before_heights = scene.heights[handle].copy()
        roster = traffic._roster_revision.stamp()
        original_route = actor.route
        for _ in range(100):
            traffic.update(city, .05)
            if actor.route is not original_route:
                break
        else:
            self.fail('vehicle did not change lanes')
        self.assertEqual(traffic._roster_revision.stamp(), roster)
        self.assertEqual(actor.occupancy_position()[0], ('lane', inner.id))
        presenter.update(city, traffic)
        new_heights = scene.heights[handle]
        self.assertAlmostEqual(new_heights[0, 1], road.elevation_at(actor.points[0]), delta=1e-7)
        self.assertFalse(np.array_equal(new_heights, before_heights))


if __name__ == '__main__':
    unittest.main()
