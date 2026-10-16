"""Physical admission and bounded work for generated and external road users."""

import cProfile
import random
import unittest

from city import CityMap, Terrain
from mobility import MobilityLink, nearest_lane_position
from models import Lane
from pathfinding import Path
from traffic_testbed import RoadVehicleSimulation


def lane_route(name, points):
    lane = Lane(name, points, points[-1])
    return Path((name + "-start", name + "-end"), (MobilityLink("lane", lane),), 100.0)


def calls_to(profiler, function):
    return sum(entry.callcount for entry in profiler.getstats()
               if entry.code == function.__code__)


class SpawnAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.city = CityMap(terrain=Terrain(trees=[]))
        self.city.add_road([(0, 100), (400, 100)])
        self.west = min(self.city.cul_de_sacs, key=lambda item: item.position[0])
        self.east = max(self.city.cul_de_sacs, key=lambda item: item.position[0])
        self.traffic = RoadVehicleSimulation(spawn_interval=1000.0)

    def admit(self, route, name, **kwargs):
        return self.traffic.admit_route(
            route, vehicle_id=name, source_id="source", destination_id="sink", **kwargs,
        )

    def test_car_behind_mid_lane_spawn_cannot_overlap_new_vehicle(self):
        first = self.traffic.spawn_car(self.city, self.west, self.east)
        self.assertIsNotNone(first)
        first.distance = 60.0
        first.advance(0)
        lane = next(edge.value for edge in first.route.edges if edge.kind == "lane")
        position = nearest_lane_position(
            lane, (first.position[0] + 2.0, first.position[1]),
        )[0]
        route = self.city.find_vehicle_route_between(position, self.east)

        self.assertIsNone(self.admit(route, "delivery"))
        self.assertEqual(self.traffic.cars, [first])

    def test_crossing_route_is_checked_even_with_different_link_keys(self):
        first = self.admit(lane_route("vertical", [(0, -50), (0, 50)]), "existing")
        self.assertIsNotNone(first)
        first.distance = 50.0
        first.advance(0)

        self.assertIsNone(self.admit(
            lane_route("horizontal", [(0, 0), (100, 0)]), "new",
        ))

    def test_full_body_of_a_long_truck_blocks_crossing_spawn(self):
        self.assertIsNotNone(self.admit(
            lane_route("truck", [(0, 0), (100, 0)]), "truck", length=40.0, width=10.0,
        ))

        self.assertIsNone(self.admit(
            lane_route("car", [(15, 0), (15, 100)]), "car",
        ))

    def test_separate_parallel_lanes_can_admit_cars_together(self):
        self.assertIsNotNone(self.admit(
            lane_route("first", [(0, 0), (100, 0)]), "first",
        ))
        self.assertIsNotNone(self.admit(
            lane_route("second", [(0, 12), (100, 12)]), "second",
        ))

    def test_rejected_spawn_can_retry_after_the_space_clears(self):
        first = self.traffic.spawn_car(self.city, self.west, self.east)
        self.assertIsNotNone(first)
        self.assertIsNone(self.traffic.spawn_car(self.city, self.west, self.east))
        first.distance = 60.0
        first.advance(0)

        self.assertIsNotNone(self.traffic.spawn_car(self.city, self.west, self.east))

    def test_blocked_retries_reuse_route_until_network_changes(self):
        profiler = cProfile.Profile()
        with profiler:
            first = self.traffic.spawn_car(self.city, self.west, self.east)
            for _ in range(4):
                self.assertIsNone(self.traffic.spawn_car(self.city, self.west, self.east))
        self.assertIsNotNone(first)
        self.assertEqual(calls_to(profiler, CityMap.find_vehicle_route_between), 1)

        self.city.rebuild_mobility_network()
        replacement = self.traffic.spawn_car(self.city, self.west, self.east)
        self.assertIsNotNone(replacement)
        self.assertIsNot(replacement.route, first.route)
        self.assertEqual(self.traffic.cars, [replacement])

    def test_full_generator_does_not_attempt_every_destination(self):
        self.traffic.max_cars = 1
        self.traffic.spawn_interval = 0.01
        self.assertIsNotNone(self.traffic.spawn_car(self.city, self.west, self.east))
        self.traffic.toggle_junction(self.west)
        self.traffic.toggle_junction(self.east)
        profiler = cProfile.Profile()
        with profiler:
            self.traffic.update(self.city, 0.05)

        self.assertEqual(calls_to(profiler, RoadVehicleSimulation.spawn_car), 0)

    def test_full_generator_preserves_seeded_destination_schedule(self):
        self.city.add_road([(200, 0), (200, 100)])
        self.traffic.max_cars = 1
        self.traffic.spawn_interval = 0.01
        self.assertIsNotNone(self.traffic.spawn_car(self.city, self.west, self.east))
        for junction in self.city.cul_de_sacs:
            self.traffic.toggle_junction(junction)
        expected = random.Random()
        expected.setstate(self.traffic.rng.getstate())
        junctions = self.traffic.active_junctions(self.city)
        for source in junctions:
            expected.shuffle([item for item in junctions if item is not source])

        self.traffic.update(self.city, 0.05)

        self.assertTrue(self.traffic.rng.getstate() == expected.getstate(),
                        "Capped sources changed the seeded destination schedule")


if __name__ == "__main__":
    unittest.main()
