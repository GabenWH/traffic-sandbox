"""The per-tick cache must preserve merge projections and reservation order."""

import unittest
from types import SimpleNamespace

import merge_behavior as merges


TARGET = ("lane", "target")
NEXT = ("lane", "next")


class ObservationCar:
    """A small routed actor with independently specified occupancy."""

    def __init__(self, name, distance, segments, *, occupancy=None, movements=(),
                 speed=10.0, plan=None):
        self.id = name
        self.distance = distance
        self.route_segments = segments
        self.controlled_movements = movements
        self.speed = speed
        self.length = 14.0
        self.cruise_speed_bound = speed
        self._merge_entry_speed = plan
        self.occupancy = occupancy
        self.occupancy_reads = 0

    def occupancy_position(self):
        self.occupancy_reads += 1
        return self.occupancy


def connection(target=TARGET):
    return SimpleNamespace(merge_target=target, intersection_id="junction")


def joining_car():
    return ObservationCar("joining", 70.0, (
        (100.0, 130.0, TARGET, 10.0),
        (130.0, 170.0, NEXT, 0.0),
    ))


class MergeObservationCacheTests(unittest.TestCase):
    def observe(self, car, others):
        cars = (car, *others)
        cache = merges.MergeTrafficSnapshot(cars)
        return merges.observe_merge(car, (80.0, 100.0, connection()), cars,
                                    snapshot=cache)

    def test_upstream_vehicle_uses_distance_to_target_start(self):
        other = ObservationCar("upstream", 70.0, ((100.0, 150.0, TARGET, 0.0),))
        observation = self.observe(joining_car(), (other,))
        self.assertEqual(observation, merges.MergeObservation(
            30.0, 14.0, (merges.MergeVehicle("upstream", -30.0, 10.0, 14.0, 10.0),),
            (), 10.0))

    def test_downstream_occupancy_keeps_section_offset(self):
        other = ObservationCar("ahead", 212.0, ((200.0, 260.0, NEXT, 0.0),),
                               occupancy=(NEXT, 12.0))
        observation = self.observe(joining_car(), (other,))
        self.assertEqual(observation.vehicles,
                         (merges.MergeVehicle("ahead", 42.0, 10.0, 14.0, 10.0),))

    def test_repeated_target_keeps_first_future_visit_before_current_occupancy(self):
        other = ObservationCar("loop", 50.0, (
            (0.0, 70.0, TARGET, 0.0), (90.0, 140.0, TARGET, 0.0),
            (150.0, 200.0, TARGET, 0.0),
        ), occupancy=(TARGET, 50.0))
        observation = self.observe(joining_car(), (other,))
        self.assertEqual(observation.vehicles[0].position, -40.0)

    def test_waiting_entrant_still_contributes_active_downstream_reservation(self):
        other = ObservationCar("committed", 50.0, (), plan=10.0, movements=(
            (0.0, 80.0, connection(NEXT)), (90.0, 110.0, connection()),
        ))
        observation = self.observe(joining_car(), (other,))
        self.assertEqual(observation.vehicles, ())
        self.assertEqual(observation.reservations, (merges.MergeReservation(30.0, 3.7),))

    def test_fast_unrelated_car_keeps_speed_scaled_observation_window(self):
        upstream = ObservationCar("far", 0.0, ((300.0, 350.0, TARGET, 0.0),))
        fast = ObservationCar("fast", 0.0, (), speed=50.0)
        observation = self.observe(joining_car(), (upstream, fast))
        self.assertEqual(tuple(v.id for v in observation.vehicles), ("far",))

    def test_queries_reuse_facts_but_next_tick_refreshes_occupancy(self):
        car = joining_car()
        other = ObservationCar("ahead", 212.0, ((200.0, 260.0, NEXT, 0.0),),
                               occupancy=(NEXT, 12.0))
        cars = (car, other)
        cache = merges.MergeTrafficSnapshot(cars)
        for _ in range(4):
            observed = merges.observe_merge(car, (80.0, 100.0, connection()), cars,
                                            snapshot=cache)
            self.assertEqual(observed.vehicles[0].position, 42.0)
        self.assertEqual(other.occupancy_reads, 1)
        other.distance = 215.0
        other.occupancy = (NEXT, 15.0)
        fresh = merges.observe_merge(car, (80.0, 100.0, connection()), cars,
                                     snapshot=merges.MergeTrafficSnapshot(cars))
        self.assertEqual(fresh.vehicles[0].position, 45.0)


if __name__ == "__main__":
    unittest.main()
