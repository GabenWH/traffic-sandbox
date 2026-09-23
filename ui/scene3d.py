"""Panda3D scene adapters for current city objects and future extensions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import atan2, degrees, dist
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

from models import Road
from .scene_geometry import DeckQuad, road_deck_quads
from .tree_primitives import TreeFeature, draw_tree
from .car_primitives import CarFeature, draw_car, update_car_lights


SceneAdapter = Callable[[Any, NodePath], NodePath]


@dataclass(frozen=True)
class TerrainFeature:
    width: float
    height: float
    color: str


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
    deck.setColor(0.28, 0.32, 0.36, 1)
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
    side_node.setColor(0.62, 0.65, 0.68, 1)
    side_node.setTwoSided(True)

    if road.forward_lane_count and road.reverse_lane_count:
        divider = LineSegs("center-divider")
        divider.setColor(0.95, 0.72, 0.13, 1)
        divider.setThickness(2)
        divider.moveTo(*road.centerline[0], road.elevations[0] + 0.2)
        for point, height in zip(road.centerline[1:], road.elevations[1:]):
            divider.drawTo(*point, height + 0.2)
        root.attachNewNode(divider.create())

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
            pillar.setColor(0.7, 0.72, 0.73, 1)
            pillar.setTwoSided(True)
    return root


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
    red, green, blue = (
        int(terrain.color[index:index + 2], 16) / 255
        for index in (1, 3, 5)
    )
    surface.setColor(red, green, blue, 1)
    surface.setTwoSided(True)
    return root


def update_car_layer(
    cars: Iterable[Any], parent: NodePath, nodes: dict[str, NodePath],
    elapsed_seconds: float,
) -> None:
    """Create, move, light, and remove the routed cars shown in 3D."""
    visible = {car.id: car for car in cars}
    for car_id in tuple(nodes):
        if car_id not in visible:
            nodes.pop(car_id).removeNode()
    for car_id, car in visible.items():
        node = nodes.get(car_id)
        if node is None or node.isEmpty():
            color = car.color
            if isinstance(color, str) and color.startswith("#"):
                color = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
            node = draw_car(CarFeature(
                length=float(getattr(car, "length", 14.0)),
                width=float(getattr(car, "width", 6.0)),
                color=color,
            ), parent)
            node.setName(f"car:{car_id}")
            nodes[car_id] = node
        node.setPos(car.position[0], car.position[1], float(getattr(car, "elevation", 0.0)))
        # Panda's positive heading turns local +Y toward -X.
        node.setH(-degrees(atan2(car.heading[0], car.heading[1])))
        update_car_lights(
            node, elapsed_seconds,
            headlights=True,
            turn_signal=getattr(car, "turn_signal", "off"),
        )
