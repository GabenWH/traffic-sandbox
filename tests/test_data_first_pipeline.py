"""A data-first traffic tick reads one frame before applying any movement."""

import random
import unittest
from unittest.mock import patch

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
    traffic.update_mode = "cpp"

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
    traffic.reorder_vehicles(car.id for car in (
        [follower, leader] if reverse else [leader, follower]))
    occupancy.rebuild(traffic.cars)
    occupancy.rebuild_calls = 0
    return city, traffic, leader, follower, occupancy


class DataFirstPipelineTests(unittest.TestCase):
    def test_new_vehicle_route_supports_a_declared_composed_cache(self):
        from simulation_cache import CachedValue
        from traffic_testbed import _next_route_movement

        _city, _traffic, leader, _follower, _occupancy = single_lane_pair()
        cached = CachedValue("next movement", dependencies=leader._route_cache._facts.dependencies,
                             build=lambda: _next_route_movement(leader))
        self.assertIsNone(cached.get())

    def test_route_owner_invalidates_composed_facts_before_an_inner_read(self):
        from simulation_cache import CachedValue
        from test_spawn_admission import lane_route
        from traffic_testbed import _next_route_movement

        _city, traffic, leader, _follower, _occupancy = single_lane_pair()
        _next_route_movement(leader)

        def read_sections():
            _next_route_movement(leader)
            return leader.route_segments

        cached = CachedValue("route sections", dependencies=leader._route_cache._facts.dependencies,
                             build=read_sections)
        previous = cached.get()
        traffic.replace_vehicle_route(
            leader.id, lane_route("new-route", [(0, 200), (300, 200)]))
        self.assertIsNot(leader.route_segments, previous)
        self.assertIs(cached.get(), leader.route_segments)

    def test_route_read_phase_rejects_replacement_before_vehicle_fields_change(self):
        from simulation_cache import MutationNotAllowedError
        from test_spawn_admission import lane_route

        _city, traffic, leader, _follower, _occupancy = single_lane_pair()
        original_route, original_sections, original_brain = (
            leader.route, leader.route_segments, leader.brain)
        with leader._route_cache._revision.read_only():
            with self.assertRaises(MutationNotAllowedError):
                traffic.replace_vehicle_route(
                    leader.id, lane_route("rejected-route", [(0, 200), (300, 200)]))
        self.assertIs(leader.route, original_route)
        self.assertIs(leader.route_segments, original_sections)
        self.assertIs(leader.brain, original_brain)

    def test_update_mode_is_validated(self):
        with self.assertRaisesRegex(ValueError, "cpp"):
            TestTrafficSimulation(update_mode="unknown")

        city, traffic, *_ = single_lane_pair()
        traffic.update_mode = "typo"
        with self.assertRaisesRegex(ValueError, "cpp"):
            traffic.update(city, 0.05)

    def test_duplicate_preloaded_car_ids_are_rejected(self):
        _city, _traffic, leader, follower, _occupancy = single_lane_pair()
        import copy
        follower = copy.copy(follower)
        follower._on_native_edit = None
        follower.id = leader.id

        with self.assertRaisesRegex(ValueError, "unique IDs"):
            TestTrafficSimulation(cars=[leader, follower])

    def test_tick_publishes_movement_deltas_without_rebuilding(self):
        city, traffic, _leader, _follower, occupancy = single_lane_pair()

        with patch.object(occupancy, "_sort_lane", wraps=occupancy._sort_lane) as sort:
            traffic.update(city, 0.05)
        self.assertEqual(sort.call_count, 0, "ordinary ordered motion needs no lane sort")

        self.assertEqual(occupancy.rebuild_calls, 0)

    def test_legacy_tick_also_avoids_full_roster_rebuilds(self):
        city, traffic, _leader, _follower, occupancy = single_lane_pair()
        traffic.update_mode = "cpp"
        traffic.update(city, 0.05)
        self.assertEqual(occupancy.rebuild_calls, 0)

    def test_manual_advance_publishes_before_the_next_admission(self):
        city, traffic, leader, follower, occupancy = single_lane_pair()
        traffic.remove_vehicle(follower.id)
        leader.distance = 120
        leader.advance(0)
        source, destination = city.intersections
        new_car = traffic.spawn_car(city, source, destination)
        self.assertIsNotNone(new_car)
        self.assertEqual(occupancy.rebuild_calls, 0)

    def test_explicit_placement_and_resize_publish_without_roster_rebuild(self):
        _city, traffic, leader, follower, occupancy = single_lane_pair()
        traffic.place_vehicle(leader.id, 80)
        self.assertEqual(occupancy.lead_gap(follower, 100), 34)
        traffic.resize_vehicle(leader.id, length=40, width=8)
        self.assertEqual(occupancy.lead_gap(follower, 100), 21)
        self.assertEqual(occupancy._max_car_length, 40)
        self.assertEqual(occupancy.rebuild_calls, 0)
        with self.assertRaises(ValueError):
            traffic.resize_vehicle(leader.id, length=-1, width=8)
        self.assertEqual(leader.length, 40)

    def test_route_replacement_removes_old_lane_membership_and_route_facts(self):
        from test_spawn_admission import lane_route

        _city, traffic, leader, _follower, occupancy = single_lane_pair()
        replacement = lane_route("replacement", [(0, 200), (300, 200)])
        traffic.replace_vehicle_route(leader.id, replacement, distance=90)
        self.assertEqual(leader.position, (90, 200))
        self.assertEqual(leader.controlled_movements, ())
        own_entries = [entry for lane in occupancy._sections.values()
                       for entry in lane if entry.car is leader]
        self.assertEqual(len(own_entries), 1)
        self.assertEqual(own_entries[0].position, 90)
        self.assertTrue(occupancy.is_current(leader))
        self.assertEqual(occupancy.rebuild_calls, 0)

    def test_profiler_records_occupancy_rebuild_subphases_when_enabled(self):
        city, traffic, *_ = single_lane_pair()
        traffic.occupancy.profile_internal_timings = True

        traffic.update(city, 0.05)

        sample = traffic.profiler.samples[-1]
        for name in (
            "occupancy_position_lookup",
            "occupancy_bin_build",
            "occupancy_section_mapping",
            "occupancy_finalize",
        ):
            self.assertIn(name, sample.timings_ms)
            self.assertGreaterEqual(sample.timings_ms[name], 0.0)
        self.assertIn("native_movement", sample.timings_ms)

    def test_empty_tick_does_not_report_previous_publication_timings(self):
        city, traffic, *_ = single_lane_pair()
        traffic.occupancy.profile_internal_timings = True
        traffic.update(city, 0.05)
        traffic.clear_vehicles()
        traffic.update(city, 0.05)
        timings = traffic.profiler.samples[-1].timings_ms
        for phase in ("occupancy_position_lookup", "occupancy_bin_build",
                      "occupancy_section_mapping", "occupancy_finalize"):
            self.assertEqual(timings[phase], 0.0)

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
            "roundabout-simultaneous-entry", seconds=2.0, engine="cpp",
        )
        second = MergeLab(seed=7).run(
            "roundabout-simultaneous-entry", seconds=2.0, engine="cpp",
        )

        self.assertEqual(first.engine, "cpp")
        self.assertEqual(first.overlap_pair_ticks, 0, first.first_overlap)
        self.assertEqual(first.state_digest, second.state_digest)
        self.assertIn("intent", first.timing_summary_ms)


if __name__ == "__main__":
    unittest.main()
