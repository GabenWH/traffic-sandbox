"""A data-first traffic tick reads one frame before applying any movement."""

import random
import unittest

from city import CityMap, Terrain
from traffic_occupancy import TrafficOccupancyIndex
from traffic_testbed import TestTrafficSimulation


class CountingOccupancy(TrafficOccupancyIndex):
    def __init__(self) -> None:
        super().__init__()
        self.rebuild_calls = 0

    def rebuild(self, cars) -> None:
        self.rebuild_calls += 1
        super().rebuild(cars)


def single_lane_pair(*, reverse: bool = False):
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0, 100), (400, 100)], name="East West")
    west = next(item for item in city.cul_de_sacs if item.position == (0.0, 100.0))
    east = next(item for item in city.cul_de_sacs if item.position == (400.0, 100.0))
    occupancy = CountingOccupancy()
    traffic = TestTrafficSimulation(
        spawn_interval=1000.0,
        rng=random.Random(1),
        occupancy=occupancy,
    )
    traffic.update_mode = "data_first"

    leader = traffic.spawn_car(city, west, east)
    assert leader is not None
    leader.distance = 100.0
    leader.advance(0)
    follower = traffic.spawn_car(city, west, east)
    assert follower is not None

    # Four feet of bumper clearance: the frozen frame must keep the follower
    # still even if the leader's accepted motion creates space this same tick.
    leader.distance = 50.0
    follower.distance = 32.0
    leader.speed = follower.speed = 10.0
    leader.advance(0)
    follower.advance(0)
    traffic.cars[:] = ([follower, leader] if reverse else [leader, follower])
    occupancy.rebuild(traffic.cars)
    occupancy.rebuild_calls = 0
    return city, traffic, leader, follower, occupancy


class DataFirstPipelineTests(unittest.TestCase):
    def test_update_mode_is_validated(self):
        with self.assertRaisesRegex(ValueError, "legacy or data_first"):
            TestTrafficSimulation(update_mode="unknown")

        city, traffic, *_ = single_lane_pair()
        traffic.update_mode = "typo"
        with self.assertRaisesRegex(ValueError, "legacy or data_first"):
            traffic.update(city, 0.05)

    def test_duplicate_preloaded_car_ids_are_rejected(self):
        _city, _traffic, leader, follower, _occupancy = single_lane_pair()
        follower.id = leader.id

        with self.assertRaisesRegex(ValueError, "unique IDs"):
            TestTrafficSimulation(cars=[leader, follower])

    def test_tick_rebuilds_occupancy_only_before_and_after_batch(self):
        city, traffic, _leader, _follower, occupancy = single_lane_pair()

        traffic.update(city, 0.05)

        self.assertEqual(occupancy.rebuild_calls, 2)

    def test_motion_does_not_depend_on_car_list_order(self):
        first = single_lane_pair(reverse=False)
        second = single_lane_pair(reverse=True)

        first[1].update(first[0], 0.05)
        second[1].update(second[0], 0.05)

        self.assertAlmostEqual(first[2].distance, second[2].distance)
        self.assertAlmostEqual(first[3].distance, second[3].distance)
        self.assertGreater(first[3].distance, 32.0)
        self.assertGreaterEqual(
            first[2].distance - first[3].distance - first[2].length,
            4.0,
        )

    def test_merge_lab_can_run_data_first_deterministically(self):
        from merge_lab import MergeLab

        first = MergeLab(seed=7).run(
            "roundabout-simultaneous-entry", seconds=2.0, engine="data_first",
        )
        second = MergeLab(seed=7).run(
            "roundabout-simultaneous-entry", seconds=2.0, engine="data_first",
        )

        self.assertEqual(first.engine, "data_first")
        self.assertEqual(first.overlap_pair_ticks, 0, first.first_overlap)
        self.assertEqual(first.state_digest, second.state_digest)
        self.assertIn("intent", first.timing_summary_ms)


if __name__ == "__main__":
    unittest.main()
