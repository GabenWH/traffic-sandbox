"""Only vehicles ready to enter a junction arbitrate its right of way."""

import unittest
from types import SimpleNamespace

from city import CityMap, Terrain
from intersection_controls import AllWayStopCoordinator, movements_conflict
from models import ControlDefinition, ControlType, ManeuverType
from car_brain import BehaviorState
from traffic_testbed import TestTrafficSimulation, _observe_priority_arrivals
from traffic_occupancy import TrafficOccupancyIndex


class PriorityContenderTests(unittest.TestCase):
    def make_queue(self, mode, distances=(5.0, 33.0, 61.0, 89.0), destinations=None):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        ends = {junction.position: junction for junction in city.cul_de_sacs}
        traffic = TestTrafficSimulation(spawn_interval=1000, update_mode=mode)
        queue = []
        for index, distance in enumerate(distances):
            destination = destinations[index] if destinations else (600, 300)
            car = traffic.spawn_car(city, ends[(0, 300)], ends[destination])
            self.assertIsNotNone(car)
            car.distance = car.controlled_movements[0][0] - car.length / 2 - distance
            car.speed = 0.0
            car.advance(0)
            queue.append(car)
        # A vehicle already crossing keeps the candidates waiting, so their
        # registration can be inspected without a new claim removing it.
        connection = queue[0].controlled_movements[0][2]
        self.assertTrue(traffic.stop_coordinator.claim_temporary_winner(
            "crossing-car", connection,
        ))
        return city, traffic, queue

    def test_queued_followers_do_not_join_intersection_priority(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode)
                # A previously registered follower must also be removed.
                traffic.stop_coordinator.observe_approach(
                    queue[-1].id, queue[-1].controlled_movements[0][2], 0.0,
                )
                traffic.update(city, 0)
                self.assertEqual(set(traffic.stop_coordinator.arrivals), {queue[0].id})
                self.assertTrue(traffic.stop_coordinator.has_claim(
                    "crossing-car", queue[0].controlled_movements[0][2],
                ))

    def test_distant_approach_does_not_join_intersection_priority(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode, distances=(90.0,))
                traffic.update(city, 0)
                self.assertNotIn(queue[0].id, traffic.stop_coordinator.arrivals)

    def test_follower_becomes_contender_when_it_reaches_the_front(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode)
                traffic.update(city, 0)
                leader, follower = queue[:2]
                traffic.remove_vehicle(leader.id)
                follower.distance = (follower.controlled_movements[0][0]
                                     - follower.length / 2 - 5.0)
                follower.advance(0)
                traffic.update(city, 0)
                self.assertEqual(set(traffic.stop_coordinator.arrivals), {follower.id})

    def test_entry_ready_arrival_keeps_its_waiting_time(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode)
                traffic.update(city, 0.05)
                before = traffic.stop_coordinator.arrivals[queue[0].id].stopped_at
                traffic.update(city, 0.05)
                self.assertEqual(
                    traffic.stop_coordinator.arrivals[queue[0].id].stopped_at, before,
                )

    def test_distant_car_rolls_toward_an_empty_intersection(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode, distances=(35.0,))
                traffic.stop_coordinator.forget_car("crossing-car")
                speed = queue[0].speed = traffic.speed_mph * 22 / 15
                traffic.update(city, 0)
                self.assertEqual(queue[0].brain.desired_speed, speed)
                self.assertNotIn(queue[0].id, traffic.stop_coordinator.arrivals)

    def test_distant_car_still_brakes_for_an_active_crossing(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode, distances=(35.0,))
                speed = queue[0].speed = traffic.speed_mph * 22 / 15
                traffic.update(city, 0)
                self.assertLess(queue[0].brain.desired_speed, speed)

    def test_fast_follower_cannot_replace_a_front_car_outside_its_entry_zone(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode, distances=(11.0, 31.0))
                queue[1].speed = 60.0
                traffic.update(city, 0)
                self.assertEqual(set(traffic.stop_coordinator.arrivals), set())

    def test_front_car_shields_a_follower_taking_a_different_turn(self):
        city, traffic, queue = self.make_queue(
            "cpp", distances=(0.0, 20.0),
            destinations=((300, 600), (600, 300)),
        )
        queue[1].speed = 40.0
        _observe_priority_arrivals(traffic.cars, traffic.stop_coordinator, 0.0)
        self.assertEqual(set(traffic.stop_coordinator.arrivals), {queue[0].id})

    def test_merge_leader_still_shields_a_queued_crossing_car(self):
        city, traffic, queue = self.make_queue(
            "cpp", distances=(0.0, 20.0),
            destinations=((300, 600), (600, 300)),
        )
        leader, follower = queue
        movement = leader.controlled_movements[0]
        movement[2].merge_target = next(key for start, _, key, _ in leader.route_segments
                                      if start >= movement[1] and key[0] == "lane")
        follower.speed = 40.0
        _observe_priority_arrivals(traffic.cars, traffic.stop_coordinator, 0.0)
        self.assertEqual(set(traffic.stop_coordinator.arrivals), set())

    def test_separate_incoming_lanes_keep_separate_front_cars(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)], forward_lane_count=2)
        city.add_road([(300, 0), (300, 600)])
        west = next(r for r in city.roads if r.centerline[0] == (0.0, 300.0))
        east = next(r for r in city.roads if r.centerline[-1] == (600.0, 300.0))
        traffic = TestTrafficSimulation()
        for index in (0, 1):
            source = next(lane for lane in west.lanes
                          if lane.direction == "forward" and lane.lane_index == index)
            destination = next(lane for lane in east.lanes
                               if lane.direction == "forward" and lane.lane_index == index)
            car = traffic.admit_route(
                city.find_vehicle_route(source, destination),
                vehicle_id=f"lane-{index}", source_id="west", destination_id="east",
            )
            self.assertIsNotNone(car)
            car.distance = car.controlled_movements[0][0] - car.length / 2 - 5.0
            car.advance(0)
        _observe_priority_arrivals(traffic.cars, traffic.stop_coordinator, 0.0)
        self.assertEqual(set(traffic.stop_coordinator.arrivals), {"lane-0", "lane-1"})

    def test_committed_stop_winner_can_keep_clearing_the_entry(self):
        for mode in ("cpp",):
            with self.subTest(mode=mode):
                city, traffic, queue = self.make_queue(mode, distances=(5.0,))
                car = queue[0]
                connection = car.controlled_movements[0][2]
                connection.control = ControlDefinition(ControlType.STOP)
                traffic.stop_coordinator.forget_car("crossing-car")
                self.assertTrue(traffic.stop_coordinator.claim_temporary_winner(car.id, connection))
                car._claimed_movement = connection
                car.speed = 1.0
                car.brain.state = BehaviorState.ENTERING_INTERSECTION
                traffic.deadlock_resolver.stall_seconds = 5.0
                traffic.deadlock_resolver.winner_id = car.id
                traffic.deadlock_resolver.winner_movement_id = connection.id
                before = car.distance
                traffic.update(city, 0.05)
                self.assertGreater(car.distance, before)


class CompatibleStopMovementTests(unittest.TestCase):
    def setUp(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 300), (600, 300)])
        city.add_road([(300, 0), (300, 600)])
        connections = city.standard_intersections[0].lane_connections
        self.first = next(m for m in connections if m.maneuver.kind is ManeuverType.THROUGH)
        self.opposite = next(m for m in connections
                             if m.maneuver.kind is ManeuverType.THROUGH
                             and m.source_output.road is self.first.destination_input.road)
        self.crossing = next(m for m in connections
                            if m.source_output != self.first.source_output
                            and movements_conflict(self.first, m))
        for movement in connections:
            movement.control = ControlDefinition(ControlType.STOP)

    def test_compatible_waiting_stop_movement_does_not_block_priority(self):
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("earlier", self.first, 0.0)
        coordinator.observe_stop("compatible", self.opposite, 1.0)
        self.assertTrue(coordinator.can_claim("compatible", self.opposite))

    def test_active_stop_claim_only_blocks_conflicting_movements(self):
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("first", self.first, 0.0)
        self.assertTrue(coordinator.claim("first", self.first))
        coordinator.observe_stop("compatible", self.opposite, 1.0)
        coordinator.observe_stop("conflicting", self.crossing, 2.0)
        self.assertTrue(coordinator.claim("compatible", self.opposite))
        self.assertFalse(coordinator.can_claim("conflicting", self.crossing))


class CommittedEntryOccupancyTests(unittest.TestCase):
    def cars(self, *, committed, distance=90.0):
        target = ("lane", "ring")
        connection = SimpleNamespace(merge_target=target)
        entrant = SimpleNamespace(
            id="entrant", length=14.0, distance=distance,
            route_segments=((0.0, 100.0, ("lane_connection", "entry"), 0.0),
                            (100.0, 200.0, target, 0.0)),
            controlled_movements=((80.0, 100.0, connection),),
            claimed_movement=connection if committed else None,
            occupancy_position=lambda: (("lane_connection", "entry"), distance),
        )
        circulating = SimpleNamespace(
            id="circulating", length=14.0, distance=70.0,
            route_segments=((0.0, 100.0, ("lane", "previous-ring"), 0.0),
                            (100.0, 200.0, target, 0.0)),
            occupancy_position=lambda: (("lane", "previous-ring"), 70.0),
        )
        return entrant, circulating

    def test_circulating_car_sees_committed_body_before_canonical_join(self):
        entrant, circulating = self.cars(committed=True)
        occupancy = TrafficOccupancyIndex()
        occupancy.rebuild([entrant, circulating])
        self.assertEqual(occupancy.lead_gap(circulating, 60.0), 6.0)

    def test_waiting_entrant_does_not_create_a_phantom_ring_obstacle(self):
        entrant, circulating = self.cars(committed=False)
        occupancy = TrafficOccupancyIndex()
        occupancy.rebuild([entrant, circulating])
        self.assertIsNone(occupancy.lead_gap(circulating, 60.0))

    def test_reservation_before_yield_line_does_not_block_ring(self):
        entrant, circulating = self.cars(committed=True, distance=72.0)
        occupancy = TrafficOccupancyIndex()
        occupancy.rebuild([entrant, circulating])
        self.assertIsNone(occupancy.lead_gap(circulating, 60.0))


if __name__ == "__main__":
    unittest.main()
