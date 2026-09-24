"""A nine-box car, facing local +Y with its tires resting at Z=0."""

from dataclasses import dataclass
from math import isfinite

from panda3d.core import (
    Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
    GeomVertexWriter, NodePath,
)

from color_palette import Palette, panda_rgba


@dataclass
class CarFeature:
    """Overall dimensions in feet, including the wheels."""

    length: float = 14.0
    width: float = 6.0
    height: float = 5.0
    color: str | tuple[float, float, float] = Palette.WINDSHIELD_OUTLINE


@dataclass(frozen=True)
class TruckFeature:
    """Low-poly construction truck dimensions and visible load."""

    length: float
    width: float
    kind: str
    cargo_key: str | None = None
    load_fraction: float = 0.0
    workers: int = 0


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
        node.setColor(*panda_rgba(color))
        return node

    part("body", (0, -0.01, 0.40), (0.90, 0.98, 0.40), car.color)
    part(
        "cabin", (0, -0.06, 0.80), (0.72, 0.46, 0.40),
        Palette.WINDSHIELD_OUTLINE,
    )
    for side, x in (("left", -0.44), ("right", 0.44)):
        for end, y in (("front", 0.30), ("rear", -0.30)):
            part(f"wheel-{side}-{end}", (x, y, 0.16), (0.12, 0.13, 0.32),
                 Palette.CAR_WHEEL)
    part(
        "headlights", (0, 0.49, 0.43), (0.56, 0.02, 0.12),
        Palette.HEADLIGHT,
    )
    for side, x in (("left", -0.38), ("right", 0.38)):
        part(
            f"blinker-{side}", (x, 0.49, 0.43), (0.12, 0.02, 0.12),
            Palette.SIGNAL_AMBER,
        )
    update_car_lights(root, 0)
    return root


def draw_truck(truck: TruckFeature, parent: NodePath) -> NodePath:
    """Attach a box-built construction truck facing local +Y."""
    if any(not isfinite(value) or value <= 0
           for value in (truck.length, truck.width)):
        raise ValueError("Truck dimensions must be finite and positive")
    if truck.kind not in ("material", "crew"):
        raise ValueError("Truck kind must be material or crew")
    if not isfinite(truck.load_fraction) or not 0 <= truck.load_fraction <= 1:
        raise ValueError("Truck load fraction must be between zero and one")
    if isinstance(truck.workers, bool) or not isinstance(truck.workers, int) or truck.workers < 0:
        raise ValueError("Truck worker count must be a nonnegative integer")

    height = 8.5 if truck.kind == "crew" else 8.0
    cab_color = "#ffb000" if truck.kind == "crew" else "#37e6ff"
    root = parent.attachNewNode("construction-truck")
    box = _unit_box()

    def part(name, position, size, color):
        node = root.attachNewNode(box.makeCopy())
        node.setName(name)
        node.setPos(position[0] * truck.width, position[1] * truck.length,
                    position[2] * height)
        node.setScale(size[0] * truck.width, size[1] * truck.length,
                      size[2] * height)
        node.setColor(*panda_rgba(color))
        return node

    part("chassis", (0, -0.01, 0.25), (0.86, 0.88, 0.22), "#343b40")
    for side, x in (("left", -0.48), ("right", 0.48)):
        for end, y in (("front", 0.29), ("rear", -0.30)):
            part(f"wheel-{side}-{end}", (x, y, 0.14), (0.13, 0.19, 0.28),
                 Palette.CAR_WHEEL)

    if truck.kind == "material":
        part("flatbed", (0, -0.15, 0.39), (0.82, 0.57, 0.08), "#8e969b")
        for side, x in (("left", -0.41), ("right", 0.41)):
            part(f"bed-rail-{side}", (x, -0.15, 0.49), (0.035, 0.58, 0.20),
                 "#a9b0b4")
        if truck.load_fraction > 0:
            load = max(0.25, truck.load_fraction)
            cargo_height = 0.06 if truck.cargo_key == "lumber" else 0.08
            cargo_height *= load
            cargo_color = {
                "lumber": "#bd8956",
                "stone": "#8c9296",
                "steel": "#8295a7",
            }.get(truck.cargo_key, "#a7a7a7")
            if truck.cargo_key == "stone":
                for index, (x, y) in enumerate((
                    (-0.20, -0.27), (0.20, -0.27),
                    (-0.20, -0.06), (0.20, -0.06),
                )):
                    part(f"cargo-stone-{index}", (x, y, 0.47 + cargo_height / 2),
                         (0.22, 0.14, cargo_height), cargo_color)
            else:
                for index, x in enumerate((-0.24, 0.0, 0.24)):
                    part(f"cargo-{truck.cargo_key or 'material'}-{index}",
                         (x, -0.15, 0.47 + cargo_height / 2),
                         (0.13, 0.42 * load, cargo_height), cargo_color)
        part("cab", (0, 0.28, 0.58), (0.84, 0.36, 0.58), cab_color)
    else:
        part("crew-compartment", (0, -0.15, 0.55), (0.86, 0.58, 0.52), "#eee1c6")
        for side, x in (("left", -0.44), ("right", 0.44)):
            part(f"crew-window-{side}", (x, -0.15, 0.61), (0.02, 0.32, 0.18),
                 Palette.WINDSHIELD_OUTLINE)
        for index in range(min(3, truck.workers)):
            part(f"crew-roof-marker-{index}", ((index - 1) * 0.20, -0.15, 0.83),
                 (0.08, 0.08, 0.05), "#ffb000")
        part("cab", (0, 0.28, 0.58), (0.84, 0.36, 0.58), cab_color)

    part("windshield", (0, 0.465, 0.61), (0.62, 0.025, 0.25), Palette.WINDSHIELD_OUTLINE)
    for side, x in (("left", -0.29), ("right", 0.29)):
        part(f"headlight-{side}", (x, 0.48, 0.42), (0.16, 0.025, 0.10), Palette.HEADLIGHT)
        part(f"indicator-{side}", (x * 1.72, 0.48, 0.42),
             (0.08, 0.025, 0.10), Palette.SIGNAL_AMBER)
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
    lamp.setColor(*panda_rgba(
        Palette.HEADLIGHT if headlights else Palette.CAR_OUTLINE,
    ))
    flash_on = elapsed_seconds % 1.0 < 0.5
    for side in ("left", "right"):
        lamp = node.find(f"blinker-{side}")
        lamp.setLightOff()
        active = flash_on and turn_signal in (side, "hazard")
        lamp.setColor(*panda_rgba(
            Palette.SIGNAL_AMBER if active else Palette.SIGNAL_OUTLINE,
        ))
