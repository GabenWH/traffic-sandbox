"""Tests for layered mobility graphs and vehicle-network compilation."""

import unittest
from math import nextafter

from city import CityMap, Terrain
from mobility import (
    LanePosition,
    LaneTraversal,
    MobilityLayer,
    MobilityLink,
    MobilityNetwork,
    lane_position_at_distance,
)
from models import Lane, LaneConnection, ManeuverType, polyline_length


class MobilityNetworkTests(unittest.TestCase):
    def test_lane_position_normalizes_floating_point_endpoint_drift(self) -> None:
        lane = Lane("Test lane", [(0.0, 0.0), (10.0, 0.0)], (10.0, 0.0))
        length = polyline_length(lane.points)

        position = LanePosition(
            lane,
            nextafter(length, float("inf")),
            lane.points[-1],
        )

        self.assertEqual(position.distance, length)

    def test_combines_unrelated_layers_and_transfer_edges(self) -> None:
        walking = MobilityLayer()
        walking.graph.add_edge("home", "stop", 5, MobilityLink("walk", "sidewalk"))
        transit = MobilityLayer()
        transit.graph.add_edge("on_bus", "work", 3, MobilityLink("ride", "route 1"))
        transfers = MobilityLayer()
        transfers.graph.add_edge("stop", "on_bus", 2, MobilityLink("board", "stop A"))
        network = MobilityNetwork({
            "walking": walking,
            "transit": transit,
            "transfers": transfers,
        })

        path = network.find_path("home", "work")

        assert path is not None
        self.assertEqual(path.nodes, ("home", "stop", "on_bus", "work"))
        self.assertEqual([edge.kind for edge in path.edges], ["walk", "board", "ride"])
        self.assertEqual(path.cost, 10)

    def test_vehicle_layer_routes_through_generated_lane_connection(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 50), (100, 50)], name="East West")
        city.add_road([(50, 0), (50, 100)], name="North South")
        west_segment = next(road for road in city.roads if road.centerline[0] == (0.0, 50.0))
        east_segment = next(road for road in city.roads if road.centerline[-1] == (100.0, 50.0))
        start_lane = next(lane for lane in west_segment.lanes if lane.direction == "forward")
        destination_lane = next(lane for lane in east_segment.lanes if lane.direction == "forward")

        path = city.find_vehicle_route(start_lane, destination_lane)

        assert path is not None
        self.assertEqual([edge.kind for edge in path.edges], [
            "lane", "road_port", "lane_connection", "road_port", "lane",
        ])
        connection = path.edges[2].value
        self.assertIsInstance(connection, LaneConnection)
        self.assertIn(start_lane, connection.source_output.lanes)
        self.assertIn(destination_lane, connection.destination_input.lanes)

    def test_cul_de_sac_connects_opposing_lanes_with_a_u_turn(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (100, 0)])
        forward = next(lane for lane in road.lanes if lane.direction == "forward")
        reverse = next(lane for lane in road.lanes if lane.direction == "reverse")

        self.assertIsNotNone(city.find_vehicle_route(forward, forward))
        route = city.find_vehicle_route(forward, reverse)
        assert route is not None
        turn = next(edge.value for edge in route.edges if edge.kind == "lane_connection")
        self.assertEqual(turn.maneuver.kind, ManeuverType.U_TURN)

    def test_routes_between_arbitrary_distances_on_one_lane(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (300, 0)])
        lane = next(lane for lane in road.lanes if lane.direction == "forward")
        start = lane_position_at_distance(lane, 30)
        destination = lane_position_at_distance(lane, 130)

        route = city.find_vehicle_route_between(start, destination)

        assert route is not None
        self.assertEqual(route.cost, 100)
        self.assertEqual(len(route.edges), 1)
        traversal = route.edges[0].value
        self.assertIsInstance(traversal, LaneTraversal)
        self.assertEqual(traversal.points, (start.point, destination.point))

    def test_selected_junctions_use_all_valid_incoming_and_outgoing_ports(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)], name="East West")
        city.add_road([(100, 0), (100, 200)], name="North South")
        intersection = city.standard_intersections[0]
        west_cul_de_sac = next(
            cul_de_sac for cul_de_sac in city.cul_de_sacs
            if cul_de_sac.position == (0.0, 100.0)
        )
        east_cul_de_sac = next(
            cul_de_sac for cul_de_sac in city.cul_de_sacs
            if cul_de_sac.position == (200.0, 100.0)
        )

        arriving = city.find_vehicle_route_between(west_cul_de_sac, intersection)
        departing = city.find_vehicle_route_between(intersection, east_cul_de_sac)

        assert arriving is not None and departing is not None
        self.assertEqual(
            [edge.kind for edge in arriving.edges],
            ["route_endpoint", "road_port", "lane", "road_port", "route_endpoint"],
        )
        self.assertEqual(
            [edge.kind for edge in departing.edges],
            ["route_endpoint", "road_port", "lane", "road_port", "route_endpoint"],
        )


if __name__ == "__main__":
    unittest.main()
