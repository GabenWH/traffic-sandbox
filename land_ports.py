"""Regional land-port connections between the map and outside road network."""

from math import isclose
from uuid import uuid4

from city import CityMap
from construction import provider_access_points
from mobility import LanePosition
from models import Point, polyline_length


LAND_PORT_CONNECTOR_NAME = "Regional land port connector"
LAND_PORT_CONNECTOR_ID = "regional-land-port-connector"
LAND_PORT_MINIMUM_LENGTH = 100.0
LAND_PORT_DEFAULT_STUB_LENGTH = 500.0
WEST_MAP_EDGE_X = 0.0
WEST_MAP_EDGE_TOLERANCE = 1e-6


def ensure_western_land_port(city_map: CityMap) -> bool:
    """Connect the local road network to a west-edge regional land port.

    Existing routable west-edge roads already provide the regional connection.
    Otherwise, add a two-way connector from the boundary to the westernmost
    local road endpoint. An empty world receives a short entry road to build from.
    """
    if _has_routable_west_access(city_map):
        return False
    if any(road.name == LAND_PORT_CONNECTOR_NAME for road in city_map.roads):
        return False

    if city_map.roads:
        target, elevation = _westernmost_road_endpoint(city_map)
        start_x = min(WEST_MAP_EDGE_X, target[0] - LAND_PORT_MINIMUM_LENGTH)
        start = (start_x, target[1])
        end = target
        elevations = [elevation, elevation]
    else:
        stub_length = min(
            LAND_PORT_DEFAULT_STUB_LENGTH,
            max(LAND_PORT_MINIMUM_LENGTH, city_map.width * 0.2),
        )
        end_x = min(city_map.width, stub_length)
        start = (WEST_MAP_EDGE_X, city_map.height / 2)
        end = (end_x, city_map.height / 2)
        elevations = [0.0, 0.0]

    road_id = (
        LAND_PORT_CONNECTOR_ID
        if all(road.id != LAND_PORT_CONNECTOR_ID for road in city_map.roads)
        else str(uuid4())
    )
    city_map.add_road(
        [start, end],
        elevations=elevations,
        name=LAND_PORT_CONNECTOR_NAME,
        road_id=road_id,
        lane_width=12.0,
        forward_lane_count=1,
        reverse_lane_count=1,
    )
    return True


def land_port_positions(city_map: CityMap) -> tuple[Point, ...]:
    """Return visible boundary positions where roads enter from the region."""
    positions: set[Point] = set()
    for road in city_map.roads:
        for start, end in zip(road.centerline, road.centerline[1:]):
            start_x, start_y = start
            end_x, end_y = end
            if isclose(start_x, end_x, abs_tol=WEST_MAP_EDGE_TOLERANCE):
                if isclose(start_x, WEST_MAP_EDGE_X, abs_tol=WEST_MAP_EDGE_TOLERANCE):
                    positions.add((WEST_MAP_EDGE_X, start_y))
                    positions.add((WEST_MAP_EDGE_X, end_y))
                continue
            if min(start_x, end_x) - WEST_MAP_EDGE_TOLERANCE <= WEST_MAP_EDGE_X <= (
                max(start_x, end_x) + WEST_MAP_EDGE_TOLERANCE
            ):
                fraction = (WEST_MAP_EDGE_X - start_x) / (end_x - start_x)
                y = start_y + (end_y - start_y) * fraction
                positions.add((WEST_MAP_EDGE_X, y))
    return tuple(sorted(positions, key=lambda point: point[1]))


def land_port_focus_point(city_map: CityMap) -> Point:
    """Return a useful camera target near this map's regional connection."""
    connector_points = [
        point
        for road in city_map.roads
        if road.name == LAND_PORT_CONNECTOR_NAME
        for point in road.centerline
    ]
    if connector_points:
        western = min(connector_points, key=lambda point: point[0])
        local = max(connector_points, key=lambda point: point[0])
        return (
            (western[0] + local[0]) / 2,
            (western[1] + local[1]) / 2,
        )

    positions = land_port_positions(city_map)
    if positions:
        return (min(250.0, city_map.width / 2), positions[0][1])
    return (city_map.width / 2, city_map.height / 2)


def _has_routable_west_access(city_map: CityMap) -> bool:
    starts = provider_access_points(city_map)
    if not starts:
        return False
    for start in starts:
        for road in city_map.roads:
            for lane in road.lanes:
                destination = LanePosition(
                    lane,
                    polyline_length(lane.points),
                    lane.points[-1],
                )
                if city_map.find_vehicle_route_between(start, destination) is not None:
                    return True
    return False


def _westernmost_road_endpoint(city_map: CityMap) -> tuple[Point, float]:
    endpoints = [
        (point, elevation)
        for road in city_map.roads
        for point, elevation in zip(
            (road.centerline[0], road.centerline[-1]),
            (road.elevations[0], road.elevations[-1]),
        )
    ]
    return min(endpoints, key=lambda item: (item[0][0], item[0][1]))
