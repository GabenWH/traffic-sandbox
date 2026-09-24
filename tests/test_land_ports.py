"""Regional land-port road connections and provider access."""

import unittest

from city import Building, CityMap, Parcel, Terrain
from construction import building_access_points, provider_access_points
from land_ports import LAND_PORT_CONNECTOR_NAME, ensure_western_land_port, land_port_positions


class LandPortTests(unittest.TestCase):
    def city(self) -> CityMap:
        return CityMap(width=600, height=300, terrain=Terrain(trees=[]))

    def test_internal_road_network_gets_a_routed_west_edge_connector(self) -> None:
        city = self.city()
        city.add_road([(250, 100), (450, 100)])
        building = Building("Project", Parcel(300, 112, 40, 30))
        city.buildings.append(building)

        self.assertTrue(ensure_western_land_port(city))

        connector = next(road for road in city.roads if road.name == LAND_PORT_CONNECTOR_NAME)
        self.assertEqual(connector.centerline, [(0.0, 100.0), (250.0, 100.0)])
        self.assertIn((0.0, 100.0), land_port_positions(city))
        self.assertTrue(provider_access_points(city))
        self.assertTrue(any(
            city.find_vehicle_route_between(source, destination) is not None
            for source in provider_access_points(city)
            for destination in building_access_points(city, building)
        ))

    def test_empty_world_gets_a_two_way_entry_road_and_visible_port_position(self) -> None:
        city = self.city()

        self.assertTrue(ensure_western_land_port(city))

        connector = next(road for road in city.roads if road.name == LAND_PORT_CONNECTOR_NAME)
        self.assertEqual(connector.centerline[0][0], 0.0)
        self.assertGreater(connector.centerline[-1][0], 0.0)
        self.assertEqual((connector.forward_lane_count, connector.reverse_lane_count), (1, 1))
        self.assertEqual(len(land_port_positions(city)), 1)

    def test_existing_west_edge_connection_is_reused_without_duplicate_road(self) -> None:
        city = self.city()
        city.add_road([(0, 120), (300, 120)])
        road_count = len(city.roads)

        self.assertFalse(ensure_western_land_port(city))

        self.assertEqual(len(city.roads), road_count)
        self.assertEqual(land_port_positions(city), ((0.0, 120.0),))

    def test_land_port_connector_survives_save_load_and_is_idempotent(self) -> None:
        from persistence import world_from_dict, world_to_dict

        city = self.city()
        city.add_road([(250, 100), (450, 100)])
        ensure_western_land_port(city)
        saved = world_to_dict(
            city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
        )

        loaded = world_from_dict(saved).city_map

        self.assertIn((0.0, 100.0), land_port_positions(loaded))
        self.assertFalse(ensure_western_land_port(loaded))
        self.assertEqual(
            sum(road.name == LAND_PORT_CONNECTOR_NAME for road in loaded.roads),
            1,
        )


if __name__ == "__main__":
    unittest.main()
