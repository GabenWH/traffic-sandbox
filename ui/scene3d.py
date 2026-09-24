"""Panda3D scene adapters for current city objects and future extensions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import atan2, degrees, dist, sqrt
from typing import Any

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LineSegs,
    NodePath,
)

from city import Building
from mobility import nearest_lane_position
from models import BuildablePhase, Intersection, IntersectionKind, Road, WorkType
from vehicle import Vehicle
from color_palette import Palette, panda_rgba
from .scene_geometry import (
    DeckQuad, road_deck_quads, road_divider_runs, roundabout_deck_quads,
)
from .tree_primitives import TreeFeature, draw_tree
from .car_primitives import (
    CarFeature, TruckFeature, draw_car, draw_truck, update_car_lights,
)


SceneAdapter = Callable[[Any, NodePath], NodePath]


@dataclass(frozen=True)
class TerrainFeature:
    width: float
    height: float
    color: str


@dataclass(frozen=True)
class RegionalLandPortFeature:
    """A visible marker where this map joins the outside road network."""

    index: int
    x: float
    y: float


def attach_map_root(parent: NodePath, name: str) -> NodePath:
    """Create a Y-reflected root for geometry authored in map coordinates."""
    root = parent.attachNewNode(name)
    root.setScale(1, -1, 1)
    # The reflection reverses triangle winding, so keep both sides visible.
    root.setTwoSided(True)
    return root


class SceneRegistry:
    """Attach model-specific geometry without teaching the camera model types."""

    def __init__(self, root: NodePath) -> None:
        self.root = root
        self._adapters: dict[type, SceneAdapter] = {}

    def register(self, model_type: type, adapter: SceneAdapter) -> None:
        self._adapters[model_type] = adapter

    def replace(self, objects: Iterable[object]) -> None:
        for child in self.root.getChildren():
            child.removeNode()
        for item in objects:
            adapter = next(
                (self._adapters[kind] for kind in type(item).__mro__
                 if kind in self._adapters),
                None,
            )
            if adapter is not None:
                adapter(item, self.root)


def quad_geom(quads: Iterable[DeckQuad], name: str) -> GeomNode:
    """Make a two-triangle surface for each quad."""
    data = GeomVertexData(name, GeomVertexFormat.getV3(), Geom.UHStatic)
    writer = GeomVertexWriter(data, "vertex")
    triangles = GeomTriangles(Geom.UHStatic)
    count = 0
    for quad in quads:
        for vertex in quad:
            writer.addData3(*vertex)
        triangles.addVertices(count, count + 1, count + 2)
        triangles.addVertices(count, count + 2, count + 3)
        count += 4
    geometry = Geom(data)
    geometry.addPrimitive(triangles)
    node = GeomNode(name)
    node.addGeom(geometry)
    return node


def draw_road(road: Road, parent: NodePath) -> NodePath:
    """Draw the authored road deck at its stored vertex elevations."""
    root = parent.attachNewNode(f"road:{road.id}")
    deck = root.attachNewNode(quad_geom(road_deck_quads(road), "deck"))
    deck.setColor(*panda_rgba(Palette.ROAD_SURFACE))
    deck.setTwoSided(True)
    edges: list[DeckQuad] = []
    for first, second, third, fourth in road_deck_quads(road):
        edges.extend((
            (first, fourth, (fourth[0], fourth[1], fourth[2] - 2),
             (first[0], first[1], first[2] - 2)),
            (second, third, (third[0], third[1], third[2] - 2),
             (second[0], second[1], second[2] - 2)),
        ))
    side_node = root.attachNewNode(quad_geom(edges, "road-edges"))
    side_node.setColor(*panda_rgba(Palette.ROAD_EDGE))
    side_node.setTwoSided(True)

    for index, (start, end) in enumerate(zip(road.centerline, road.centerline[1:])):
        segment_length = dist(start, end)
        fractions = (0.25, 0.75) if segment_length >= 40 else (0.5,)
        for position_index, fraction in enumerate(fractions):
            height = road.elevations[index] + fraction * (
                road.elevations[index + 1] - road.elevations[index]
            )
            if height < 6:
                continue
            x = start[0] + fraction * (end[0] - start[0])
            y = start[1] + fraction * (end[1] - start[1])
            support = root.attachNewNode(f"support-{index}-{position_index}")
            pillar = support.attachNewNode(quad_geom(_support_quads(x, y, height), "pillar"))
            pillar.setColor(*panda_rgba(Palette.ROAD_EDGE))
            pillar.setTwoSided(True)
    return root


def draw_road_dividers(
    roads: Iterable[Road], intersections: Iterable[Intersection], parent: NodePath,
) -> NodePath:
    """Draw center dividers with their connected intersection areas removed."""
    junctions = list(intersections)
    lines = LineSegs("road-center-dividers")
    lines.setColor(*panda_rgba(Palette.ROAD_DIVIDER))
    lines.setThickness(2)
    drew_line = False
    for road in roads:
        if not (road.forward_lane_count and road.reverse_lane_count):
            continue
        for run in road_divider_runs(road, junctions):
            if len(run) < 2:
                continue
            lines.moveTo(run[0][0], run[0][1], run[0][2] + 0.2)
            for x, y, height in run[1:]:
                lines.drawTo(x, y, height + 0.2)
            drew_line = True
    root = parent.attachNewNode("road-dividers")
    if drew_line:
        root.attachNewNode(lines.create())
    return root


def draw_intersection(junction: Intersection, parent: NodePath) -> NodePath:
    """Draw a roundabout's drivable ring and raised landscaped center."""
    root = parent.attachNewNode(f"intersection:{junction.id}")
    if junction.kind is not IntersectionKind.ROUNDABOUT:
        return root
    road_quads, outer_band_quads, island_quads = roundabout_deck_quads(junction)
    deck = root.attachNewNode(quad_geom(road_quads, "roundabout-road"))
    deck.setColor(*panda_rgba(Palette.ROAD_SURFACE))
    deck.setTwoSided(True)
    band = root.attachNewNode(quad_geom(outer_band_quads, "roundabout-outer-band"))
    band.setColor(*panda_rgba(Palette.ROUNDABOUT_APRON))
    band.setTwoSided(True)
    center = root.attachNewNode(quad_geom(island_quads, "roundabout-island"))
    center.setColor(*panda_rgba(Palette.ROUNDABOUT_ISLAND))
    center.setTwoSided(True)
    return root


def draw_building(building: Building, parent: NodePath) -> NodePath:
    """Draw a building mass, or a foundation and scaffold while it is built."""
    parcel = building.parcel
    root = parent.attachNewNode(f"building:{building.id}")
    root.setPos(parcel.x + parcel.width / 2, parcel.y + parcel.height / 2, 0)
    width = max(1.0, parcel.width * 0.88)
    depth = max(1.0, parcel.height * 0.88)
    foundation_height = 2.0
    foundation = root.attachNewNode(quad_geom(_box_quads(
        -parcel.width / 2, -parcel.height / 2, 0,
        parcel.width / 2, parcel.height / 2, foundation_height,
    ), "building-foundation"))
    foundation.setColor(*panda_rgba("#777c80"))
    foundation.setTwoSided(True)

    target_height = _building_height(building)
    under_construction = building.phase in (
        BuildablePhase.PLANNING, BuildablePhase.UNDER_CONSTRUCTION,
    )
    progress = 0.0
    if (
        building.active_work is not None
        and building.active_work.kind is WorkType.CONSTRUCTION
    ):
        progress = building.active_work.progress
    wall_height = target_height * (progress if under_construction else 1.0)
    if wall_height > 0:
        body = root.attachNewNode(quad_geom(_box_quads(
            -width / 2, -depth / 2, foundation_height,
            width / 2, depth / 2, foundation_height + wall_height,
        ), "building-body"))
        body.setColor(*panda_rgba(building.color))
        body.setTwoSided(True)

    if under_construction:
        _draw_building_scaffold(root, width, depth, target_height, foundation_height)
    else:
        roof = root.attachNewNode(quad_geom(_box_quads(
            -width / 2, -depth / 2, foundation_height + target_height,
            width / 2, depth / 2, foundation_height + target_height + 2.0,
        ), "building-roof"))
        roof.setColor(*panda_rgba("#454b52"))
        roof.setTwoSided(True)
        _draw_building_facade(root, width, depth, foundation_height, target_height)
    return root


def draw_regional_land_port(
    port: RegionalLandPortFeature, parent: NodePath,
) -> NodePath:
    """Draw an entry gate and an inward arrow at the regional boundary."""
    root = parent.attachNewNode(f"regional-land-port:{port.index}")
    root.setPos(port.x, port.y, 0)
    lines = LineSegs("regional-land-port-gate")
    lines.setColor(*panda_rgba("#ffd166"))
    lines.setThickness(4)
    gate_x = 12.0
    for y in (-14.0, 14.0):
        lines.moveTo(gate_x, y, 0.5)
        lines.drawTo(gate_x, y, 34.0)
    lines.moveTo(gate_x, -14.0, 34.0)
    lines.drawTo(gate_x, 14.0, 34.0)
    # Point into the local map, matching the west-to-east connector direction.
    lines.moveTo(-18.0, 0, 1.0)
    lines.drawTo(5.0, 0, 1.0)
    lines.moveTo(-3.0, -8.0, 1.0)
    lines.drawTo(5.0, 0, 1.0)
    lines.drawTo(-3.0, 8.0, 1.0)
    root.attachNewNode(lines.create())
    return root


def _building_height(building: Building) -> float:
    occupancy = max(1, building.residents + building.jobs)
    return min(48.0, 12.0 + 4.0 * sqrt(occupancy / 4.0))


def _draw_building_scaffold(
    root: NodePath, width: float, depth: float,
    target_height: float, foundation_height: float,
) -> None:
    scaffold = LineSegs("construction-scaffold")
    scaffold.setColor(*panda_rgba("#ffb000"))
    scaffold.setThickness(2)
    half_width, half_depth = width / 2, depth / 2
    corners = (
        (-half_width, -half_depth), (half_width, -half_depth),
        (half_width, half_depth), (-half_width, half_depth),
    )
    top = foundation_height + target_height
    for x, y in corners:
        scaffold.moveTo(x, y, foundation_height)
        scaffold.drawTo(x, y, top)
    scaffold.moveTo(-half_width, -half_depth, top)
    scaffold.drawTo(half_width, -half_depth, top)
    scaffold.drawTo(half_width, half_depth, top)
    scaffold.drawTo(-half_width, half_depth, top)
    scaffold.drawTo(-half_width, -half_depth, top)
    level = foundation_height + 8.0
    while level < top:
        scaffold.moveTo(-half_width, -half_depth, level)
        scaffold.drawTo(half_width, -half_depth, level)
        scaffold.drawTo(half_width, half_depth, level)
        scaffold.drawTo(-half_width, half_depth, level)
        scaffold.drawTo(-half_width, -half_depth, level)
        level += 8.0
    root.attachNewNode(scaffold.create()).setName("construction-scaffold")


def _draw_building_facade(
    root: NodePath, width: float, depth: float,
    foundation_height: float, body_height: float,
) -> None:
    window_quads: list[DeckQuad] = []
    rows = (foundation_height + body_height * 0.38,
            foundation_height + body_height * 0.72)
    columns = max(1, min(5, int(width // 24)))
    window_width = min(5.0, width / (columns * 2.5))
    window_height = min(5.0, body_height / 6)
    for z in rows:
        for column in range(columns):
            x = (column - (columns - 1) / 2) * width / (columns + 1)
            for y in (-depth / 2 - 0.15, depth / 2 + 0.15):
                window_quads.extend(_box_quads(
                    x - window_width / 2, y - 0.25, z - window_height / 2,
                    x + window_width / 2, y + 0.25, z + window_height / 2,
                ))
    windows = root.attachNewNode(quad_geom(window_quads, "building-windows"))
    windows.setColor(*panda_rgba("#8ecae6"))
    windows.setTwoSided(True)


def _box_quads(
    x_min: float, y_min: float, z_min: float,
    x_max: float, y_max: float, z_max: float,
) -> list[DeckQuad]:
    """Return the six faces of a box, each as one quad."""
    return [
        ((x_min, y_min, z_min), (x_max, y_min, z_min),
         (x_max, y_max, z_min), (x_min, y_max, z_min)),
        ((x_min, y_min, z_max), (x_max, y_min, z_max),
         (x_max, y_max, z_max), (x_min, y_max, z_max)),
        ((x_min, y_min, z_min), (x_max, y_min, z_min),
         (x_max, y_min, z_max), (x_min, y_min, z_max)),
        ((x_max, y_min, z_min), (x_max, y_max, z_min),
         (x_max, y_max, z_max), (x_max, y_min, z_max)),
        ((x_max, y_max, z_min), (x_min, y_max, z_min),
         (x_min, y_max, z_max), (x_max, y_max, z_max)),
        ((x_min, y_max, z_min), (x_min, y_min, z_min),
         (x_min, y_min, z_max), (x_min, y_max, z_max)),
    ]


def _support_quads(x: float, y: float, top: float) -> list[DeckQuad]:
    half = 2.5
    a, b = x - half, x + half
    c, d = y - half, y + half
    return [
        ((a, c, 0), (b, c, 0), (b, c, top), (a, c, top)),
        ((b, c, 0), (b, d, 0), (b, d, top), (b, c, top)),
        ((b, d, 0), (a, d, 0), (a, d, top), (b, d, top)),
        ((a, d, 0), (a, c, 0), (a, c, top), (a, d, top)),
    ]


def draw_terrain(terrain: TerrainFeature, parent: NodePath) -> NodePath:
    """Draw the currently flat city terrain behind road decks."""
    root = parent.attachNewNode("terrain")
    surface = root.attachNewNode(quad_geom([(
        (0, 0, -0.5), (terrain.width, 0, -0.5),
        (terrain.width, terrain.height, -0.5), (0, terrain.height, -0.5),
    )], "grass"))
    surface.setColor(*panda_rgba(terrain.color))
    surface.setTwoSided(True)
    return root


def update_road_vehicle_layer(
    vehicles: Iterable[Vehicle], city,
    parent: NodePath, nodes: dict[str, NodePath], elapsed_seconds: float,
) -> None:
    """Refresh cars and trucks from one collection of vehicle actors."""
    visible = {vehicle.id: vehicle for vehicle in vehicles}
    for vehicle_id in tuple(nodes):
        if vehicle_id not in visible:
            nodes.pop(vehicle_id).removeNode()
    for vehicle_id, vehicle in visible.items():
        appearance = vehicle.appearance
        node = nodes.get(vehicle_id)
        if node is None or node.isEmpty():
            if appearance.shape == "car":
                node = draw_car(CarFeature(
                    length=vehicle.length,
                    width=vehicle.width,
                    color=vehicle.color,
                ), parent)
            else:
                node = draw_truck(TruckFeature(
                    vehicle.length,
                    vehicle.width,
                    "crew" if appearance.shape == "crew_truck" else "material",
                    cargo_key=appearance.cargo_key,
                    load_fraction=appearance.load_fraction,
                    workers=appearance.workers,
                ), parent)
            node.setName(f"road-vehicle:{vehicle_id}")
            nodes[vehicle_id] = node
        elevation = 0.0
        best_distance = float("inf")
        for road in city.roads:
            for lane in road.lanes:
                lane_position, distance = nearest_lane_position(lane, vehicle.position)
                if distance < best_distance:
                    best_distance = distance
                    elevation = road.elevation_at(lane_position.point)
        node.setPos(vehicle.position[0], vehicle.position[1], elevation)
        node.setH(-degrees(atan2(vehicle.heading[0], vehicle.heading[1])))
        if appearance.shape == "car":
            update_car_lights(
                node, elapsed_seconds,
                headlights=True,
                turn_signal=getattr(vehicle, "turn_signal", "off"),
            )
