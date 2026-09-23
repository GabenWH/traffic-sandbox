"""Primitive trees for Panda3D; dimensions are fractions of total height."""

from dataclasses import dataclass
from math import cos, isfinite, pi, sin

from panda3d.core import (
    Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
    GeomVertexWriter, NodePath, Vec3,
)


@dataclass
class TreeFeature:
    """Height is in world units. Age is stored for future growth behavior."""

    species: str = "pine"
    height: float = 20.0
    age: float = 0.0
    x: float = 0.0
    y: float = 0.0


def _tapered_cylinder(name: str, radius: float, top_radius: float,
                      bottom: float, top: float) -> GeomNode:
    """Make one closed, eight-sided cylinder, frustum, or cone."""
    data = GeomVertexData(name, GeomVertexFormat.getV3n3(), Geom.UHStatic)
    vertices = GeomVertexWriter(data, "vertex")
    normals = GeomVertexWriter(data, "normal")
    triangles = GeomTriangles(Geom.UHStatic)

    def triangle(a: Vec3, b: Vec3, c: Vec3) -> None:
        normal = (b - a).cross(c - a)
        normal.normalize()
        start = vertices.getWriteRow()
        for point in (a, b, c):
            vertices.addData3(point)
            normals.addData3(normal)
        triangles.addVertices(start, start + 1, start + 2)

    for index in range(8):
        a, b = 2 * pi * index / 8, 2 * pi * (index + 1) / 8
        low_a = Vec3(radius * cos(a), radius * sin(a), bottom)
        low_b = Vec3(radius * cos(b), radius * sin(b), bottom)
        high_a = Vec3(top_radius * cos(a), top_radius * sin(a), top)
        high_b = Vec3(top_radius * cos(b), top_radius * sin(b), top)
        triangle(low_a, low_b, high_a)
        triangle(Vec3(0, 0, bottom), low_b, low_a)
        if top_radius > 0:
            triangle(low_b, high_b, high_a)
            triangle(Vec3(0, 0, top), high_a, high_b)

    geometry = Geom(data)
    geometry.addPrimitive(triangles)
    node = GeomNode(name)
    node.addGeom(geometry)
    return node


def draw_tree(tree: TreeFeature, parent: NodePath) -> NodePath:
    """Attach a tree at the origin; position the returned NodePath as needed.

    draw_tree(TreeFeature("pine", height=20, age=5), parent)
    draw_tree(TreeFeature("redwood", height=60, age=100), parent)

    Pine uses two solid primitives; redwood uses ten. Age is metadata only.
    """
    if tree.species not in ("pine", "redwood"):
        raise ValueError("Tree species must be 'pine' or 'redwood'")
    if not isfinite(tree.height) or tree.height <= 0:
        raise ValueError("Tree height must be finite and positive")

    root = parent.attachNewNode(f"tree:{tree.species}")
    root.setPos(tree.x, tree.y, 0)
    root.setScale(tree.height)

    def part(name, radius, top_radius, bottom, top, color):
        node = root.attachNewNode(
            _tapered_cylinder(name, radius, top_radius, bottom, top)
        )
        node.setColor(*color, 1)

    if tree.species == "pine":
        part("trunk", 0.045, 0.045, 0, 0.7, (0.38, 0.23, 0.12))
        part("foliage", 0.30, 0, 0.22, 1, (0.16, 0.39, 0.19))
    else:
        part("trunk", 0.065, 0.018, 0, 0.96, (0.48, 0.22, 0.14))
        for tier in range(9):
            bottom = 0.32 + tier * 0.065
            top = min(1.0, bottom + 0.22)
            radius = 0.19 * (1 - tier / 11)
            part(f"foliage-{tier}", radius, 0, bottom, top,
                 (0.12, 0.30 + tier * 0.008, 0.17))
    return root
