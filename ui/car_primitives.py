"""A nine-box car, facing local +Y with its tires resting at Z=0."""

from dataclasses import dataclass
from math import isfinite

from panda3d.core import (
    Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
    GeomVertexWriter, NodePath,
)


@dataclass
class CarFeature:
    """Overall dimensions in feet, including the wheels."""

    length: float = 14.0
    width: float = 6.0
    height: float = 5.0
    color: tuple[float, float, float] = (0.18, 0.48, 0.82)


def _unit_box() -> GeomNode:
    data = GeomVertexData("car-box", GeomVertexFormat.getV3n3(), Geom.UHStatic)
    vertices = GeomVertexWriter(data, "vertex")
    normals = GeomVertexWriter(data, "normal")
    triangles = GeomTriangles(Geom.UHStatic)
    # Each face has its own vertices for sharp, flat normals.
    for normal, corners in (
        ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
        ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
        ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
        ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
        ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
        ((0, 1, 0), ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0))),
    ):
        start = vertices.getWriteRow()
        for x, y, z in corners:
            vertices.addData3(x - 0.5, y - 0.5, z - 0.5)
            normals.addData3(*normal)
        triangles.addVertices(start, start + 1, start + 2)
        triangles.addVertices(start, start + 2, start + 3)
    geometry = Geom(data)
    geometry.addPrimitive(triangles)
    node = GeomNode("car-box")
    node.addGeom(geometry)
    return node


def draw_car(car: CarFeature, parent: NodePath) -> NodePath:
    """Attach a car; move/rotate the returned node with setPos and setHpr.

    Nine solids: body, cabin, four wheels, headlight bar, two front indicators.
    Call update_car_lights each frame with the simulation's elapsed time.
    """
    if any(not isfinite(value) or value <= 0
           for value in (car.length, car.width, car.height)):
        raise ValueError("Car dimensions must be finite and positive")
    root = parent.attachNewNode("car")
    box = _unit_box()

    def part(name, position, size, color):
        node = root.attachNewNode(box.makeCopy())
        node.setName(name)
        node.setPos(position[0] * car.width, position[1] * car.length,
                    position[2] * car.height)
        node.setScale(size[0] * car.width, size[1] * car.length,
                      size[2] * car.height)
        node.setColor(*color, 1)
        return node

    part("body", (0, -0.01, 0.40), (0.90, 0.98, 0.40), car.color)
    part("cabin", (0, -0.06, 0.80), (0.72, 0.46, 0.40), (0.12, 0.22, 0.30))
    for side, x in (("left", -0.44), ("right", 0.44)):
        for end, y in (("front", 0.30), ("rear", -0.30)):
            part(f"wheel-{side}-{end}", (x, y, 0.16), (0.12, 0.13, 0.32),
                 (0.07, 0.08, 0.09))
    part("headlights", (0, 0.49, 0.43), (0.56, 0.02, 0.12), (1, 0.96, 0.73))
    for side, x in (("left", -0.38), ("right", 0.38)):
        part(f"blinker-{side}", (x, 0.49, 0.43), (0.12, 0.02, 0.12), (1, 0.46, 0.02))
    update_car_lights(root, 0)
    return root


def update_car_lights(
    node: NodePath, elapsed_seconds: float, *, headlights: bool = True,
    turn_signal: str = "off",
) -> None:
    """Set visible lamp colors; indicators flash at 1 Hz, including hazards.

    turn_signal accepts 'off', 'left', 'right', or 'hazard'. These are visible
    lamps, not lights that illuminate the road. Left/right are the driver's.
    """
    if turn_signal not in ("off", "left", "right", "hazard"):
        raise ValueError("Turn signal must be off, left, right, or hazard")
    lamp = node.find("headlights")
    lamp.setLightOff()
    lamp.setColor(*((1, 0.96, 0.73, 1) if headlights else (0.20, 0.21, 0.22, 1)))
    flash_on = elapsed_seconds % 1.0 < 0.5
    for side in ("left", "right"):
        lamp = node.find(f"blinker-{side}")
        lamp.setLightOff()
        active = flash_on and turn_signal in (side, "hazard")
        lamp.setColor(*((1, 0.46, 0.02, 1) if active else (0.24, 0.11, 0.02, 1)))
