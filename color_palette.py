"""Shared world colors for the Tk canvas and Panda3D renderers."""

from __future__ import annotations


class Palette:
    """Named hex colors used by the 2D world renderer and its 3D twin."""

    TERRAIN_GRASS = "#78b85a"
    TREE_CANOPY = "#397a3e"
    TREE_OUTLINE = "#2f6835"
    WHITE = "#ffffff"
    BUILDING_SHADOW = "#40505a"
    BUILDING_OUTLINE = "#eee4d5"
    ROAD_SURFACE = "#4d535a"
    ROAD_DIVIDER = "#f4c542"
    ROAD_EDGE = "#c9cdd0"
    ROUNDABOUT_APRON = "#c6a96b"
    ROUNDABOUT_ISLAND = "#67884b"
    ROUNDABOUT_ISLAND_OUTLINE = "#e6dfbe"
    ROAD_MARKING = "#f7f7f2"
    LANE_MARKING = "#f4f0bd"
    LANE_LABEL = "#d9dde0"
    ROUTE_HIGHLIGHT = "#37e6ff"
    ROUTE_ERROR = "#ff5b72"
    CAR_OUTLINE = "#20252a"
    SIGNAL_AMBER = "#ffb000"
    SIGNAL_OUTLINE = "#5f3e00"
    CAR_WHEEL = "#16191c"
    CAR_WHEEL_OUTLINE = "#08090a"
    HEADLIGHT = "#fff7b0"
    WINDSHIELD = "#8ecae6"
    WINDSHIELD_OUTLINE = "#29566b"
    SPEED_SIGN = "#f8f8f8"


def panda_rgba(
    color: str | tuple[float, float, float], alpha: float = 1.0,
) -> tuple[float, float, float, float]:
    """Convert a Tk hex color or RGB tuple to Panda3D's normalized RGBA."""
    if isinstance(color, str):
        if len(color) != 7 or not color.startswith("#"):
            raise ValueError(f"Expected a #RRGGBB color, got {color!r}")
        rgb = tuple(
            int(color[index:index + 2], 16) / 255
            for index in (1, 3, 5)
        )
    else:
        rgb = color
    return (*rgb, alpha)
