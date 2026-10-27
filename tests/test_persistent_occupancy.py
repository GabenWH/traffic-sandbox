"""Incremental lane membership preserves physical occupancy and snapshots."""

import unittest
from types import SimpleNamespace

from traffic_occupancy import TrafficOccupancyIndex


A, B, C = ("lane", "a"), ("lane", "b"), ("lane", "c")
SEGMENTS = ((0.0, 100.0, A, 0.0), (100.0, 200.0, B, 0.0),
            (200.0, 300.0, C, 0.0))


def actor(name, distance, *, length=14.0, segments=SEGMENTS):
    car = SimpleNamespace(id=name, distance=distance, length=length,
                          route_segments=segments, claimed_movement=None,
                          controlled_movements=())

    def position():
        for start, end, key, offset in car.route_segments:
            if car.distance < end or end == 300.0:
                return key, offset + max(0.0, min(end - start, car.distance - start))
        return None

    car.occupancy_position = position
    return car


class PersistentOccupancyTests(unittest.TestCase):
    def test_production_vehicle_cursor_advances_and_resets_without_route_rescans(self):
        from mobility import MobilityLink, vehicle_route_points
        from models import Lane
        from pathfinding import Path
        from traffic_testbed import RoutedRoadVehicle

        class CountedSegments(tuple):
            reads = 0

            def __iter__(self):
                for value in super().__iter__():
                    self.reads += 1
                    yield value

            def __getitem__(self, index):
                self.reads += 1
                return super().__getitem__(index)

        lanes = [Lane(str(i), [(i * 100, 0), ((i + 1) * 100, 0)],
                      ((i + 1) * 100, 0)) for i in range(1000)]
        route = Path((), tuple(MobilityLink("lane", lane) for lane in lanes), 100000)
        car = RoutedRoadVehicle("s", "d", route, vehicle_route_points(route), 10, "red")
        segments = CountedSegments(car.route_segments)
        car.route_segments = segments
        car.distance = 50010
        self.assertEqual(car.occupancy_position(), (("lane", "500:forward:0"), 10))
        segments.reads = 0
        for position in (50011, 50012, 50013):
            car.distance = position
            car.occupancy_position()
        self.assertLess(segments.reads, 20)
        car.distance = 50100
        self.assertEqual(car.occupancy_position(), (("lane", "501:forward:0"), 0))
        car.distance = 0
        self.assertEqual(car.occupancy_position(), (("lane", "0:forward:0"), 0))
        car.route_segments = ((0, 100000, B, 25),)
        car.distance = 20
        self.assertEqual(car.occupancy_position(), (B, 45))
        car.distance = 100000
        self.assertEqual(car.occupancy_position(), (B, 100025))

    def test_lane_entries_persist_in_distance_order_as_cars_move(self):
        front, back = actor("front", 70), actor("back", 30)
        index = TrafficOccupancyIndex()
        index.rebuild([front, back])
        lane = index._sections[A]
        self.assertEqual([e.car.id for e in lane], ["back", "front"])
        back_entry = lane[0]
        front.distance, back.distance = 75, 35
        index.rebuild([front, back])
        self.assertIs(index._sections[A], lane)
        self.assertIs(lane[0], back_entry)
        self.assertEqual([e.position for e in lane], [35, 75])
        self.assertEqual(index.lead_gap(back, 100), 26)

    def test_rear_clearance_boundary_and_despawn_remove_membership(self):
        car = actor("car", 93)
        index = TrafficOccupancyIndex()
        index.rebuild([car])
        self.assertEqual(set(index._sections), {A, B})
        car.distance = 129
        index.rebuild([car])
        self.assertIn(A, index._sections)
        car.distance = 129.01
        index.rebuild([car])
        self.assertEqual(set(index._sections), {B})
        index.rebuild([])
        self.assertEqual(dict(index._sections), {})
        self.assertEqual(index._bins, {})

    def test_committed_merge_shadow_transfers_to_real_occupancy_once(self):
        car = actor("entrant", 70)
        claim = SimpleNamespace(id="merge", merge_target=B)
        car.controlled_movements = ((60.0, 100.0, claim),)
        car.claimed_movement = claim
        index = TrafficOccupancyIndex()
        index.rebuild([car])
        self.assertNotIn(B, index._sections)
        car.distance = 75
        index.rebuild([car])
        self.assertEqual([e.position for e in index._sections[B]], [-25])
        car.claimed_movement = None
        index.rebuild([car])
        self.assertNotIn(B, index._sections)
        car.claimed_movement = claim
        index.rebuild([car])
        car.distance = 93
        index.rebuild([car])
        self.assertEqual([e.position for e in index._sections[B]], [-7])
        car.distance = 229.01
        index.rebuild([car])
        self.assertNotIn(B, index._sections)

    def test_rewind_and_route_replacement_do_not_leave_stale_entries(self):
        car = actor("car", 240)
        index = TrafficOccupancyIndex()
        index.rebuild([car])
        car.distance = 10
        index.rebuild([car])
        self.assertEqual(set(index._sections), {A})
        car.route_segments = ((0.0, 300.0, B, 40.0),)
        index.rebuild([car])
        self.assertEqual(set(index._sections), {B})
        self.assertEqual(index._sections[B][0].position, 50)
        replacement = actor("car", 20)
        index.rebuild([replacement])
        self.assertEqual(set(index._sections), {A})
        self.assertIs(index._sections[A][0].car, replacement)

    def test_leader_is_nearest_bumper_with_different_vehicle_lengths(self):
        follower = actor("follower", 10, length=10)
        small = actor("small", 50, length=10)
        truck = actor("truck", 55, length=40)
        index = TrafficOccupancyIndex()
        index.rebuild([small, truck, follower])
        lead, gap = index.lead_car_gap(follower, 100)
        self.assertIs(lead, truck)
        self.assertEqual(gap, 20)

    def test_snapshot_positions_change_only_when_index_is_updated(self):
        follower, leader = actor("follower", 10), actor("leader", 50)
        index = TrafficOccupancyIndex()
        index.rebuild([follower, leader])
        leader.distance = 80
        self.assertEqual(index.lead_gap(follower, 100), 26)
        index.rebuild([follower, leader])
        self.assertEqual(index.lead_gap(follower, 100), 56)

    def test_ordered_leader_query_does_not_scan_distant_cars(self):
        class CountedEntries(list):
            reads = 0

            def __getitem__(self, item):
                self.reads += 1
                return super().__getitem__(item)

        segments = ((0.0, 10000.0, A, 0.0),)
        cars = [actor(str(i), i * 30, segments=segments) for i in range(300)]
        index = TrafficOccupancyIndex()
        index.rebuild(cars)
        entries = CountedEntries(index._sections[A])
        index._sections[A] = entries
        lead, gap = index.lead_car_gap(cars[100], 128)
        self.assertIs(lead, cars[101])
        self.assertEqual(gap, 16)
        self.assertLess(entries.reads, 10,
                        "a local leader query must not visit the rest of the lane")

    def test_steady_motion_does_not_rescan_distant_route_segments(self):
        class CountedSegments(tuple):
            reads = 0

            def __iter__(self):
                for value in super().__iter__():
                    self.reads += 1
                    yield value

            def __getitem__(self, index):
                self.reads += 1
                return super().__getitem__(index)

        segments = CountedSegments((i * 100.0, (i + 1) * 100.0,
                                    ("lane", str(i)), 0.0) for i in range(1000))
        car = actor("car", 50010, segments=segments)
        car.occupancy_position = lambda: (("lane", "500"), car.distance - 50000)
        index = TrafficOccupancyIndex()
        index.rebuild([car])
        segments.reads = 0
        for _ in range(5):
            car.distance += 1
            index.rebuild([car])
            self.assertIsNone(index.lead_gap(car, 30))
        self.assertLess(segments.reads, 100,
                        "steady motion must visit local sections, not the full route")


if __name__ == "__main__":
    unittest.main()
