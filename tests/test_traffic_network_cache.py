"""Topology lookups may persist only while their owning map is unchanged."""

import unittest

from city import CityMap, Terrain
from traffic_testbed import RoadVehicleSimulation


def small_city():
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0, 100), (400, 100)])
    return city


class CountedJunctions(list):
    iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


class TrafficNetworkCacheTests(unittest.TestCase):
    def test_roster_and_source_views_reject_unowned_mutation(self):
        traffic = RoadVehicleSimulation()
        with self.assertRaises(AttributeError):
            traffic.cars.append(None)
        with self.assertRaises(AttributeError):
            traffic.cars = []
        with self.assertRaises(AttributeError):
            traffic.active_junction_ids.append("unowned")
        with self.assertRaises(AttributeError):
            traffic.active_junction_ids = []

    def test_explicit_roster_reordering_invalidates_view_and_occupancy_ties(self):
        from test_data_first_pipeline import single_lane_pair

        _city, traffic, leader, follower, _index = single_lane_pair()
        old_view = traffic._cars_snapshot()
        traffic.place_vehicle(leader.id, 50)
        traffic.place_vehicle(follower.id, 50)
        traffic.reorder_vehicles([follower.id, leader.id])
        self.assertEqual(list(traffic.cars), [follower, leader])
        self.assertIsNot(traffic._cars_snapshot(), old_view)
        lane = next(iter(traffic.occupancy._sections.values()))
        self.assertEqual([entry.car.id for entry in lane], [follower.id, leader.id])
        with self.assertRaises(ValueError):
            traffic.reorder_vehicles([leader.id, leader.id])

    def test_unchanged_ticks_scan_junctions_only_once_in_each_mode(self):
        for mode in ("legacy", "data_first"):
            with self.subTest(mode=mode):
                city = small_city()
                traffic = RoadVehicleSimulation(update_mode=mode, spawn_interval=1000)
                for junction in city.intersections:
                    traffic.toggle_junction(junction)
                counted = CountedJunctions(city.intersections)
                city.intersections = counted
                for _ in range(20):
                    traffic.update(city, 0.05)
                self.assertEqual(counted.iterations, 1,
                                 "unchanged topology must not be rescanned per tick")

    def test_lookup_reuses_a_read_only_mapping(self):
        from traffic_network_cache import JunctionLookup

        city = small_city()
        lookup = JunctionLookup()
        first = lookup.get(city)
        self.assertIs(lookup.get(city), first)
        with self.assertRaises(TypeError):
            first["new junction"] = city.intersections[0]

    def test_topology_revision_replaces_the_mapping(self):
        from traffic_network_cache import JunctionLookup

        city = small_city()
        lookup = JunctionLookup()
        first = lookup.get(city)
        previous_keys = tuple(first)
        city.add_road([(0, 200), (400, 200)])
        current = lookup.get(city)
        self.assertIsNot(current, first)
        self.assertEqual(dict(current), {item.id: item for item in city.intersections})
        self.assertEqual(tuple(first), previous_keys)

    def test_replacement_map_with_same_revision_does_not_reuse_old_lookup(self):
        from traffic_network_cache import JunctionLookup

        city, replacement = small_city(), small_city()
        self.assertEqual(city.mobility_revision, replacement.mobility_revision)
        lookup = JunctionLookup()
        old = lookup.get(city)
        current = lookup.get(replacement)
        self.assertIsNot(current, old)
        for junction in replacement.intersections:
            self.assertIs(current[junction.id], junction)
        self.assertEqual(set(current), {item.id for item in replacement.intersections})

    def test_source_toggles_reuse_lookup_and_keep_selection_order(self):
        city = small_city()
        first, second = city.intersections
        city.intersections = CountedJunctions(city.intersections)
        traffic = RoadVehicleSimulation()
        traffic.toggle_junction(second)
        self.assertEqual(traffic.active_junctions(city), [second])
        traffic.toggle_junction(first)
        self.assertEqual(traffic.active_junctions(city), [second, first])
        traffic.toggle_junction(second)
        self.assertEqual(traffic.active_junctions(city), [first])
        self.assertEqual(city.intersections.iterations, 1)

    def test_update_prunes_old_source_ids_when_map_is_replaced(self):
        city = small_city()
        traffic = RoadVehicleSimulation(update_mode="data_first", spawn_interval=1000)
        traffic.toggle_junction(city.intersections[0])
        traffic.update(city, 0.05)
        empty = CityMap(terrain=Terrain(trees=[]))
        traffic.update(empty, 0.05)
        self.assertEqual(traffic.active_junction_ids, [])
        self.assertEqual(traffic._spawn_elapsed, {})
        self.assertEqual(traffic.active_junctions(empty), [])

    def test_stale_source_selected_after_lookup_warms_is_pruned(self):
        from types import SimpleNamespace

        for mode in ("legacy", "data_first"):
            with self.subTest(mode=mode):
                city = small_city()
                traffic = RoadVehicleSimulation(update_mode=mode)
                valid = city.intersections[0]
                traffic.toggle_junction(valid)
                traffic.active_junctions(city)
                traffic.toggle_junction(SimpleNamespace(id="removed-junction"))

                self.assertEqual(traffic.active_junctions(city), [valid])
                traffic.update(city, 0.05)
                self.assertEqual(list(traffic.active_junction_ids), [valid.id])
                self.assertNotIn("removed-junction", traffic._spawn_elapsed)

    def test_source_view_and_spawn_timers_persist_between_unchanged_ticks(self):
        city = small_city()
        traffic = RoadVehicleSimulation(update_mode="data_first", spawn_interval=1000)
        first, second = city.intersections
        traffic.toggle_junction(first)
        traffic.toggle_junction(second)
        traffic.update(city, 0.05)
        timers = traffic._spawn_elapsed
        view = traffic._active_junctions_snapshot(city)
        for _ in range(10):
            traffic.update(city, 0.05)
            self.assertIs(traffic._spawn_elapsed, timers)
            self.assertIs(traffic._active_junctions_snapshot(city), view)
        traffic.toggle_junction(first)
        self.assertEqual(traffic._active_junctions_snapshot(city), (second,))
        self.assertNotIn(first.id, timers)

    def test_roster_snapshot_changes_on_admission_and_removal_not_motion(self):
        city = small_city()
        traffic = RoadVehicleSimulation(update_mode="data_first", spawn_interval=1000)
        first, second = city.intersections
        empty = traffic._cars_snapshot()
        car = traffic.spawn_car(city, first, second)
        self.assertIsNotNone(car)
        view = traffic._cars_snapshot()
        self.assertIsNot(view, empty)
        traffic.update(city, 0.05)
        self.assertIs(traffic._cars_snapshot(), view)
        traffic.remove_vehicle(car.id)
        self.assertEqual(traffic._cars_snapshot(), ())


if __name__ == "__main__":
    unittest.main()
