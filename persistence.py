"""Versioned JSON persistence for generic city-builder worlds."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from city import Building, CityMap, Parcel, Terrain, ZoneType
from models import (
    Buildable,
    BuildablePhase,
    ControlDefinition,
    ControlType,
    Intersection,
    IntersectionKind,
    ManeuverDefinition,
    ManeuverType,
    ResourceInventory,
    Road,
    RoadEnd,
    WorkOrder,
    WorkType,
)
from units import validate_unit_system


WORLD_FORMAT = "lanesimulator.world"
WORLD_VERSION = 4


class WorldFormatError(ValueError):
    """Raised when a file is not a supported, well-formed world save."""


@dataclass(frozen=True)
class LoadedWorld:
    city_map: CityMap
    unit_system: str
    camera_x: float
    camera_y: float
    camera_zoom: float


def world_to_dict(
    city_map: CityMap,
    *,
    unit_system: str,
    camera_x: float,
    camera_y: float,
    camera_zoom: float,
) -> dict[str, Any]:
    """Return a JSON-compatible snapshot without any Tkinter state."""
    return {
        "format": WORLD_FORMAT,
        "version": WORLD_VERSION,
        "world": {
            "width": city_map.width,
            "height": city_map.height,
            "terrain": {
                "grass_color": city_map.terrain.grass_color,
                "trees": [[x, y] for x, y in city_map.terrain.trees],
            },
            "roads": [
                {
                    "id": road.id,
                    "name": road.name,
                    "centerline": [[x, y] for x, y in road.centerline],
                    "lane_width": road.lane_width,
                    "forward_lane_count": road.forward_lane_count,
                    "reverse_lane_count": road.reverse_lane_count,
                    "buildable_id": road.buildable_id,
                    "buildable_state": _buildable_state_to_dict(road),
                    "lanes": [
                        {
                            "name": lane.name,
                            "direction": lane.direction,
                            "index": lane.lane_index,
                            "following_gap": lane.following_gap,
                        }
                        for lane in road.lanes
                    ],
                }
                for road in city_map.roads
            ],
            "intersections": [
                {
                    "id": intersection.id,
                    "kind": intersection.kind.value,
                    "position": [*intersection.position],
                    "road_ids": [road.id for road in intersection.connected_roads],
                    "lane_connections": [
                        {
                            "source_output": {
                                "road_id": connection.source_output.road.id,
                                "end": connection.source_output.end.value,
                            },
                            "destination_input": {
                                "road_id": connection.destination_input.road.id,
                                "end": connection.destination_input.end.value,
                            },
                            "maneuver": {
                                "kind": connection.maneuver.kind.value,
                                "angle": connection.maneuver.angle,
                            },
                            "control": {
                                "kind": connection.control.kind.value,
                                "controller_id": connection.control.controller_id,
                            },
                        }
                        for connection in intersection.lane_connections
                    ],
                }
                for intersection in city_map.intersections
            ],
            "parcels": [
                {
                    "id": parcel.id,
                    "x": parcel.x,
                    "y": parcel.y,
                    "width": parcel.width,
                    "height": parcel.height,
                    "zone": parcel.zone.value if parcel.zone is not None else None,
                }
                for parcel in city_map.parcels
            ],
            "buildings": [
                {
                    "id": building.id,
                    "name": building.name,
                    "parcel_id": building.parcel.id,
                    "residents": building.residents,
                    "jobs": building.jobs,
                    "buildable_id": building.buildable_id,
                    "color": building.color,
                    "buildable_state": _buildable_state_to_dict(building),
                }
                for building in city_map.buildings
            ],
        },
        "view": {
            "unit_system": validate_unit_system(unit_system),
            "camera": {"x": camera_x, "y": camera_y, "zoom": camera_zoom},
        },
    }


def world_from_dict(data: object) -> LoadedWorld:
    """Validate and reconstruct a generic world save."""
    root = _mapping(data, "save")
    if root.get("format") != WORLD_FORMAT:
        raise WorldFormatError("This is not a city-builder world save.")
    if root.get("version") != WORLD_VERSION:
        raise WorldFormatError(f"Unsupported world-save version: {root.get('version')!r}.")

    world = _mapping(root.get("world"), "world")
    terrain_data = _mapping(world.get("terrain"), "world.terrain")
    terrain = Terrain(
        grass_color=_string(terrain_data.get("grass_color"), "world.terrain.grass_color"),
        trees=_points(terrain_data.get("trees"), "world.terrain.trees"),
    )
    city_map = CityMap(
        width=_positive_number(world.get("width"), "world.width"),
        height=_positive_number(world.get("height"), "world.height"),
        terrain=terrain,
    )

    road_ids: set[str] = set()
    road_by_id: dict[str, Road] = {}
    for road_index, raw_road in enumerate(_list(world.get("roads"), "world.roads")):
        path = f"world.roads[{road_index}]"
        road_data = _mapping(raw_road, path)
        road_id = _string(road_data.get("id"), f"{path}.id")
        if road_id in road_ids:
            raise WorldFormatError(f"Duplicate road id: {road_id!r}.")
        road_ids.add(road_id)
        forward_lane_count = _nonnegative_int(
            road_data.get("forward_lane_count"), f"{path}.forward_lane_count"
        )
        reverse_lane_count = _nonnegative_int(
            road_data.get("reverse_lane_count"), f"{path}.reverse_lane_count"
        )
        expected_lane_keys = {
            ("forward", index) for index in range(forward_lane_count)
        } | {
            ("reverse", index) for index in range(reverse_lane_count)
        }
        lane_metadata: list[dict[str, object]] = []
        saved_lane_keys: set[tuple[str, int]] = set()
        for lane_index, raw_lane in enumerate(_list(road_data.get("lanes"), f"{path}.lanes")):
            lane_path = f"{path}.lanes[{lane_index}]"
            lane_data = _mapping(raw_lane, lane_path)
            direction = _string(lane_data.get("direction"), f"{lane_path}.direction")
            index = _nonnegative_int(lane_data.get("index"), f"{lane_path}.index")
            lane_key = (direction, index)
            if lane_key not in expected_lane_keys:
                raise WorldFormatError(f"{lane_path} does not match its parent road's lane configuration.")
            if lane_key in saved_lane_keys:
                raise WorldFormatError(f"Duplicate lane position in {path}: {lane_key!r}.")
            saved_lane_keys.add(lane_key)
            lane_metadata.append({
                "name": _string(lane_data.get("name"), f"{lane_path}.name"),
                "direction": direction,
                "index": index,
                "following_gap": _positive_number(
                    lane_data.get("following_gap"), f"{lane_path}.following_gap"
                ),
            })
        if saved_lane_keys != expected_lane_keys:
            raise WorldFormatError(f"{path}.lanes must describe every configured lane exactly once.")
        try:
            road = city_map.add_road(
                _points(road_data.get("centerline"), f"{path}.centerline"),
                road_id=road_id,
                name=_string(road_data.get("name"), f"{path}.name"),
                lane_width=_positive_number(road_data.get("lane_width"), f"{path}.lane_width"),
                forward_lane_count=forward_lane_count,
                reverse_lane_count=reverse_lane_count,
                buildable_id=(
                    None
                    if road_data.get("buildable_id") is None
                    else _string(road_data.get("buildable_id"), f"{path}.buildable_id")
                ),
                lane_metadata=lane_metadata,
                create_intersections=False,
            )
            road_by_id[road.id] = road
            _apply_buildable_state(
                road,
                _buildable_state_from_dict(
                    road_data.get("buildable_state"), f"{path}.buildable_state"
                ),
            )
        except (TypeError, ValueError) as error:
            raise WorldFormatError(f"Invalid {path}: {error}") from error

    # Roads derive temporary endpoint junctions while loading in isolation.
    # Saved intersection records are authoritative.
    city_map.intersections.clear()
    intersection_ids: set[str] = set()
    saved_intersections: list[tuple[Intersection, dict[str, Any], str]] = []
    for intersection_index, raw_intersection in enumerate(
        _list(world.get("intersections", []), "world.intersections")
    ):
        path = f"world.intersections[{intersection_index}]"
        intersection_data = _mapping(raw_intersection, path)
        intersection_id = _string(intersection_data.get("id"), f"{path}.id")
        if intersection_id in intersection_ids:
            raise WorldFormatError(f"Duplicate intersection id: {intersection_id!r}.")
        intersection_ids.add(intersection_id)
        position_data = _points([intersection_data.get("position")], f"{path}.position")
        connected_roads: list[Road] = []
        seen_road_ids: set[str] = set()
        for road_index, raw_road_id in enumerate(
            _list(intersection_data.get("road_ids"), f"{path}.road_ids")
        ):
            road_id = _string(raw_road_id, f"{path}.road_ids[{road_index}]")
            if road_id in seen_road_ids:
                raise WorldFormatError(f"Duplicate road reference in {path}: {road_id!r}.")
            seen_road_ids.add(road_id)
            try:
                connected_roads.append(road_by_id[road_id])
            except KeyError as error:
                raise WorldFormatError(
                    f"{path} refers to unknown road {road_id!r}."
                ) from error
        try:
            intersection_kind = IntersectionKind(
                _string(intersection_data.get("kind"), f"{path}.kind")
            )
        except ValueError as error:
            raise WorldFormatError(f"Unknown intersection kind in {path}.") from error
        intersection = Intersection(
            id=intersection_id,
            position=position_data[0],
            connected_roads=connected_roads,
            kind=intersection_kind,
        )
        city_map.intersections.append(intersection)
        saved_intersections.append((intersection, intersection_data, path))

    # Lane connections are derived from road inputs and outputs.
    city_map.rebuild_mobility_network()
    for intersection, intersection_data, path in saved_intersections:
        raw_connections = intersection_data.get("lane_connections")
        expected = {
            (
                (connection.source_output.road.id, connection.source_output.end.value),
                (
                    connection.destination_input.road.id,
                    connection.destination_input.end.value,
                ),
            ): connection
            for connection in intersection.lane_connections
        }
        restored_keys: set[tuple[tuple[str, str], tuple[str, str]]] = set()
        for connection_index, raw_connection in enumerate(
            _list(raw_connections, f"{path}.lane_connections")
        ):
            connection_path = f"{path}.lane_connections[{connection_index}]"
            connection_data = _mapping(raw_connection, connection_path)
            source = _port_reference(
                connection_data.get("source_output"),
                f"{connection_path}.source_output",
                road_by_id,
            )
            destination = _port_reference(
                connection_data.get("destination_input"),
                f"{connection_path}.destination_input",
                road_by_id,
            )
            key = (source, destination)
            if key in restored_keys:
                raise WorldFormatError(f"Duplicate road-port movement in {path}: {key!r}.")
            restored_keys.add(key)
            try:
                connection = expected[key]
            except KeyError as error:
                raise WorldFormatError(
                    f"{connection_path} is not a legal movement at this intersection."
                ) from error

            maneuver_data = _mapping(connection_data.get("maneuver"), f"{connection_path}.maneuver")
            control_data = _mapping(connection_data.get("control"), f"{connection_path}.control")
            raw_controller_id = control_data.get("controller_id")
            try:
                connection.maneuver = ManeuverDefinition(
                    ManeuverType(_string(maneuver_data.get("kind"), f"{connection_path}.maneuver.kind")),
                    _number(maneuver_data.get("angle"), f"{connection_path}.maneuver.angle"),
                )
                connection.control = ControlDefinition(
                    ControlType(_string(control_data.get("kind"), f"{connection_path}.control.kind")),
                    None if raw_controller_id is None else _string(
                        raw_controller_id, f"{connection_path}.control.controller_id"
                    ),
                )
            except ValueError as error:
                raise WorldFormatError(f"Invalid {connection_path}: {error}") from error
        if restored_keys != set(expected):
            raise WorldFormatError(
                f"{path}.lane_connections must describe every generated movement exactly once."
            )

    parcel_by_id: dict[str, Parcel] = {}
    for parcel_index, raw_parcel in enumerate(_list(world.get("parcels"), "world.parcels")):
        path = f"world.parcels[{parcel_index}]"
        parcel_data = _mapping(raw_parcel, path)
        parcel_id = _string(parcel_data.get("id"), f"{path}.id")
        if parcel_id in parcel_by_id:
            raise WorldFormatError(f"Duplicate parcel id: {parcel_id!r}.")
        raw_zone = parcel_data.get("zone")
        try:
            zone = None if raw_zone is None else ZoneType(_string(raw_zone, f"{path}.zone"))
        except ValueError as error:
            raise WorldFormatError(f"Unknown zone in {path}: {raw_zone!r}.") from error
        parcel = Parcel(
            x=_number(parcel_data.get("x"), f"{path}.x"),
            y=_number(parcel_data.get("y"), f"{path}.y"),
            width=_positive_number(parcel_data.get("width"), f"{path}.width"),
            height=_positive_number(parcel_data.get("height"), f"{path}.height"),
            zone=zone,
            id=parcel_id,
        )
        city_map.parcels.append(parcel)
        parcel_by_id[parcel_id] = parcel

    building_ids: set[str] = set()
    for building_index, raw_building in enumerate(_list(world.get("buildings"), "world.buildings")):
        path = f"world.buildings[{building_index}]"
        building_data = _mapping(raw_building, path)
        building_id = _string(building_data.get("id"), f"{path}.id")
        if building_id in building_ids:
            raise WorldFormatError(f"Duplicate building id: {building_id!r}.")
        building_ids.add(building_id)
        parcel_id = _string(building_data.get("parcel_id"), f"{path}.parcel_id")
        try:
            parcel = parcel_by_id[parcel_id]
        except KeyError as error:
            raise WorldFormatError(f"{path} refers to unknown parcel {parcel_id!r}.") from error
        city_map.buildings.append(Building(
            name=_string(building_data.get("name"), f"{path}.name"),
            parcel=parcel,
            residents=_nonnegative_int(building_data.get("residents"), f"{path}.residents"),
            jobs=_nonnegative_int(building_data.get("jobs"), f"{path}.jobs"),
            buildable_id=(
                None
                if building_data.get("buildable_id") is None
                else _string(building_data.get("buildable_id"), f"{path}.buildable_id")
            ),
            color=_string(building_data.get("color", "#8b8580"), f"{path}.color"),
            id=building_id,
            **_buildable_state_from_dict(
                building_data.get("buildable_state"), f"{path}.buildable_state"
            ),
        ))

    view = _mapping(root.get("view", {}), "view")
    camera = _mapping(view.get("camera", {}), "view.camera")
    return LoadedWorld(
        city_map=city_map,
        unit_system=validate_unit_system(str(view.get("unit_system", "imperial"))),
        camera_x=_number(camera.get("x", 0.0), "view.camera.x"),
        camera_y=_number(camera.get("y", 0.0), "view.camera.y"),
        camera_zoom=_positive_number(camera.get("zoom", 1.0), "view.camera.zoom"),
    )


def _buildable_state_to_dict(buildable: Buildable) -> dict[str, Any]:
    work = buildable.active_work
    return {
        "phase": buildable.phase.value,
        "condition": buildable.condition,
        "inventory": dict(buildable.inventory.amounts),
        "active_work": None if work is None else {
            "kind": work.kind.value,
            "required_work": work.required_work,
            "completed_work": work.completed_work,
            "stage_index": work.stage_index,
        },
    }


def _buildable_state_from_dict(value: object, path: str) -> dict[str, Any]:
    state = _mapping(value, path)
    try:
        phase = BuildablePhase(_string(state.get("phase"), f"{path}.phase"))
    except ValueError as error:
        raise WorldFormatError(f"Unknown buildable phase in {path}.") from error
    condition = _number(state.get("condition"), f"{path}.condition")
    if not 0 <= condition <= 1:
        raise WorldFormatError(f"{path}.condition must be between 0 and 1.")
    raw_inventory = _mapping(state.get("inventory"), f"{path}.inventory")
    inventory: dict[str, float] = {}
    for raw_resource, raw_amount in raw_inventory.items():
        resource = _string(raw_resource, f"{path}.inventory resource")
        amount = _number(raw_amount, f"{path}.inventory.{resource}")
        if amount < 0:
            raise WorldFormatError(f"{path}.inventory.{resource} cannot be negative.")
        if amount > 0:
            inventory[resource] = amount

    raw_work = state.get("active_work")
    work: WorkOrder | None = None
    if raw_work is not None:
        work_data = _mapping(raw_work, f"{path}.active_work")
        try:
            kind = WorkType(_string(work_data.get("kind"), f"{path}.active_work.kind"))
        except ValueError as error:
            raise WorldFormatError(f"Unknown work type in {path}.active_work.") from error
        required_work = _positive_number(
            work_data.get("required_work"), f"{path}.active_work.required_work"
        )
        completed_work = _number(
            work_data.get("completed_work"), f"{path}.active_work.completed_work"
        )
        if not 0 <= completed_work <= required_work:
            raise WorldFormatError(
                f"{path}.active_work.completed_work must be between 0 and required_work."
            )
        work = WorkOrder(
            kind=kind,
            required_work=required_work,
            completed_work=completed_work,
            stage_index=_nonnegative_int(
                work_data.get("stage_index"), f"{path}.active_work.stage_index"
            ),
        )
    return {
        "phase": phase,
        "condition": condition,
        "inventory": ResourceInventory(inventory),
        "active_work": work,
    }


def _apply_buildable_state(buildable: Buildable, state: dict[str, Any]) -> None:
    buildable.phase = state["phase"]
    buildable.condition = state["condition"]
    buildable.inventory = state["inventory"]
    buildable.active_work = state["active_work"]


def _port_reference(
    value: object,
    path: str,
    road_by_id: dict[str, Road],
) -> tuple[str, str]:
    data = _mapping(value, path)
    road_id = _string(data.get("road_id"), f"{path}.road_id")
    if road_id not in road_by_id:
        raise WorldFormatError(f"{path} refers to unknown road {road_id!r}.")
    try:
        end = RoadEnd(_string(data.get("end"), f"{path}.end"))
    except ValueError as error:
        raise WorldFormatError(f"Unknown road end in {path}.") from error
    return road_id, end.value


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorldFormatError(f"{path} must be an object.")
    return value


def _list(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise WorldFormatError(f"{path} must be an array.")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorldFormatError(f"{path} must be a non-empty string.")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorldFormatError(f"{path} must be a number.")
    number = float(value)
    if not isfinite(number):
        raise WorldFormatError(f"{path} must be finite.")
    return number


def _positive_number(value: object, path: str) -> float:
    number = _number(value, path)
    if number <= 0:
        raise WorldFormatError(f"{path} must be positive.")
    return number


def _nonnegative_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorldFormatError(f"{path} must be a non-negative integer.")
    return value


def _points(value: object, path: str) -> list[tuple[float, float]]:
    points = _list(value, path)
    result: list[tuple[float, float]] = []
    for index, raw_point in enumerate(points):
        point = _list(raw_point, f"{path}[{index}]")
        if len(point) != 2:
            raise WorldFormatError(f"{path}[{index}] must contain exactly two numbers.")
        result.append((_number(point[0], f"{path}[{index}][0]"), _number(point[1], f"{path}[{index}][1]")))
    return result
