"""Delta publication must retain snapshot and nearest-bumper semantics."""

import random
import unittest

from test_persistent_occupancy import A, B, actor
from traffic_occupancy import TrafficOccupancyIndex


class OccupancyDeltaTests(unittest.TestCase):
    def test_unpublished_resize_does_not_change_snapshot_bumper_gaps(self):
        back, front = actor("back", 10), actor("front", 50)
        index = TrafficOccupancyIndex()
        index.rebuild([back, front])
        self.assertEqual(index.lead_gap(back, 100), 26)
        front.length = 40
        back.length = 20
        self.assertEqual(index.lead_gap(back, 100), 26)
        index.publish_changes([front])
        self.assertEqual(index.lead_gap(back, 100), 13)
        index.publish_changes([back])
        self.assertEqual(index.lead_gap(back, 100), 10)

    def test_one_car_delta_does_not_read_unchanged_cars(self):
        cars = [actor(str(i), i * 30, segments=((0, 10000, A, 0),)) for i in range(100)]
        index = TrafficOccupancyIndex()
        index.rebuild(cars)
        entries = index._sections[A]
        saved = entries[50]
        calls = []
        for car in cars:
            original = car.occupancy_position
            car.occupancy_position = lambda car=car, original=original: (
                calls.append(car.id), original())[1]
        cars[50].distance += 1
        index.publish_changes([cars[50]])
        self.assertEqual(calls, ["50"])
        self.assertIs(index._sections[A], entries)
        self.assertIs(entries[50], saved)
        self.assertEqual(saved.position, 1501)
        self.assertEqual(index.lead_gap(cars[49], 100), 17)

    def test_batch_reorders_existing_entries_before_inserting_new_members(self):
        cars = [actor(str(i), x) for i, x in enumerate((20, 40, 60, 80))]
        index = TrafficOccupancyIndex()
        index.rebuild(cars)
        for car, position in zip(cars, (75, 55, 35, 15)):
            car.distance = position
        newcomer = actor("new", 45)
        index.publish_changes([newcomer, *cars])
        self.assertEqual([e.car.id for e in index._sections[A]], ["3", "2", "new", "1", "0"])
        self.assertEqual([e.lane_index for e in index._sections[A]], list(range(5)))
        index.publish_changes([], removed=[cars[2], newcomer])
        self.assertEqual([e.car.id for e in index._sections[A]], ["3", "1", "0"])

    def test_delta_queries_match_full_sync_through_motion_rewind_claims_and_resize(self):
        rng = random.Random(879)
        cars = [actor(str(i), rng.uniform(0, 290), length=rng.choice((10, 14, 40)))
                for i in range(24)]
        delta, full = TrafficOccupancyIndex(), TrafficOccupancyIndex()
        delta.rebuild(cars)
        for step in range(100):
            changed = rng.sample(cars, 8)
            for car in changed:
                car.distance = rng.uniform(0, 295) if step % 9 == 0 else min(299, car.distance + 2)
            changed[0].length = rng.choice((10, 14, 60))
            delta.publish_changes(changed)
            full.rebuild(cars)
            self.assertEqual(set(delta._sections), set(full._sections))
            for key in full._sections:
                self.assertEqual([(e.car.id, e.position) for e in delta._sections[key]],
                                 [(e.car.id, e.position) for e in full._sections[key]])
            for car in cars:
                expected = full.lead_car_gap(car, 128)
                actual = delta.lead_car_gap(car, 128)
                self.assertEqual(None if actual is None else (actual[0].id, actual[1]),
                                 None if expected is None else (expected[0].id, expected[1]))

    def test_claim_route_replacement_and_removal_are_explicit_deltas(self):
        from types import SimpleNamespace

        car = actor("entrant", 75)
        claim = SimpleNamespace(merge_target=B)
        car.controlled_movements = ((60, 100, claim),)
        index = TrafficOccupancyIndex()
        index.rebuild([car])
        self.assertTrue(index.is_current(car))
        car.claimed_movement = claim
        self.assertFalse(index.is_current(car))
        index.publish_changes([car])
        self.assertEqual(index._sections[B][0].position, -25)
        car.claimed_movement = None
        index.publish_changes([car])
        self.assertNotIn(B, index._sections)
        car.route_segments = ((0, 300, B, 40),)
        index.publish_changes([car])
        self.assertEqual(set(index._sections), {B})
        index.publish_changes([], removed=[car])
        self.assertEqual(index._sections, {})
        self.assertEqual(index._bins, {})
        self.assertEqual(index._max_car_length, 0)

    def test_queries_reject_partial_or_failed_publication_and_rebuild_recovers(self):
        car = actor("car", 30)
        index = TrafficOccupancyIndex()
        index.rebuild([car])
        original = car.occupancy_position
        def broken_position():
            with self.assertRaisesRegex(RuntimeError, "snapshot"):
                index.lead_gap(car, 100)
            raise ValueError("failed position")
        car.occupancy_position = broken_position
        with self.assertRaisesRegex(ValueError, "failed position"):
            index.publish_changes([car])
        with self.assertRaisesRegex(RuntimeError, "snapshot"):
            index.lead_gap(car, 100)
        car.occupancy_position = original
        index.rebuild([car])
        self.assertIsNone(index.lead_gap(car, 100))


if __name__ == "__main__":
    unittest.main()
