"""Behavior tests for runtime all-way-stop arbitration."""

import unittest

from city import CityMap, Terrain
from intersection_controls import AllWayStopCoordinator
from models import ControlDefinition, ControlType


class AllWayStopCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (400, 100)])
        city.add_road([(200, 0), (200, 200)])
        self.junction = city.standard_intersections[0]
        for connection in self.junction.lane_connections:
            connection.control = ControlDefinition(ControlType.STOP)
        self.connections = self.junction.lane_connections

    def test_first_fully_stopped_car_gets_priority(self) -> None:
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("later", self.connections[1], 2.0)
        coordinator.observe_stop("first", self.connections[0], 1.0)

        self.assertTrue(coordinator.can_claim("first", self.connections[0]))
        self.assertFalse(coordinator.can_claim("later", self.connections[1]))

    def test_tied_arrivals_are_deterministic(self) -> None:
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("z-car", self.connections[0], 1.0)
        coordinator.observe_stop("a-car", self.connections[0], 1.0)

        self.assertTrue(coordinator.can_claim("a-car", self.connections[0]))
        self.assertFalse(coordinator.can_claim("z-car", self.connections[0]))

    def test_claim_blocks_others_until_released(self) -> None:
        coordinator = AllWayStopCoordinator()
        coordinator.observe_stop("first", self.connections[0], 1.0)
        self.assertTrue(coordinator.claim("first", self.connections[0]))
        coordinator.observe_stop("second", self.connections[1], 2.0)

        self.assertFalse(coordinator.can_claim("second", self.connections[1]))
        coordinator.release("first")
        self.assertTrue(coordinator.can_claim("second", self.connections[1]))


if __name__ == "__main__":
    unittest.main()

