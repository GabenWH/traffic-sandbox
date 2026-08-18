"""Conversions between canonical simulation values and display units.

The traffic model stores distance in pixels/feet and speed limits in MPH.
Keeping that stable makes old saves and physics independent of a user's
display preference. This module is the one place UI code converts values.
"""

from __future__ import annotations

from config import (
    DEFAULT_UNIT_SYSTEM,
    KILOMETERS_PER_MILE,
    METERS_PER_FOOT,
    MIN_SPEED_LIMIT_MPH,
    MAX_SPEED_LIMIT_MPH,
    PIXELS_PER_FOOT,
    PIXELS_PER_MILE,
    SECONDS_PER_HOUR,
    STANDARD_GRAVITY_FEET_PER_SECOND_SQUARED,
    UNIT_SYSTEMS,
)


def validate_unit_system(unit_system: str) -> str:
    """Return a supported system or raise a clear error for configuration."""
    if unit_system not in UNIT_SYSTEMS:
        choices = ", ".join(UNIT_SYSTEMS)
        raise ValueError(f"Unknown unit system {unit_system!r}; choose {choices}.")
    return unit_system


validate_unit_system(DEFAULT_UNIT_SYSTEM)


def speed_unit(unit_system: str) -> str:
    """Return the abbreviated road-speed unit for a display system."""
    return "mph" if validate_unit_system(unit_system) == "imperial" else "km/h"


def distance_unit(unit_system: str) -> str:
    """Return the practical short-distance unit for a display system."""
    return "ft" if validate_unit_system(unit_system) == "imperial" else "m"


def mph_to_display(speed_mph: float, unit_system: str) -> float:
    """Convert canonical MPH to the selected road-speed unit."""
    return speed_mph if validate_unit_system(unit_system) == "imperial" else speed_mph * KILOMETERS_PER_MILE


def display_to_mph(speed: float, unit_system: str) -> float:
    """Convert a user-entered road speed into canonical MPH."""
    return speed if validate_unit_system(unit_system) == "imperial" else speed / KILOMETERS_PER_MILE


def pixels_to_display_distance(pixels: float, unit_system: str) -> float:
    """Convert canonical world pixels into feet or metres for the UI."""
    feet = pixels / PIXELS_PER_FOOT
    return feet if validate_unit_system(unit_system) == "imperial" else feet * METERS_PER_FOOT


def display_distance_to_pixels(distance: float, unit_system: str) -> float:
    """Convert a UI distance in feet/metres back into world pixels."""
    feet = distance if validate_unit_system(unit_system) == "imperial" else distance / METERS_PER_FOOT
    return feet * PIXELS_PER_FOOT


def speed_limit_bounds(unit_system: str) -> tuple[float, float]:
    """Return the legal sign range in the selected display unit."""
    return (
        mph_to_display(MIN_SPEED_LIMIT_MPH, unit_system),
        mph_to_display(MAX_SPEED_LIMIT_MPH, unit_system),
    )


def acceleration_unit(unit_system: str) -> str:
    """Return the requested acceleration unit: g in Imperial, m/s² in Metric."""
    return "g" if validate_unit_system(unit_system) == "imperial" else "m/s²"


def pixels_per_second_squared_to_display_acceleration(
    acceleration: float, unit_system: str,
) -> float:
    """Convert model acceleration into g or metres per second squared."""
    feet_per_second_squared = acceleration / PIXELS_PER_FOOT
    if validate_unit_system(unit_system) == "imperial":
        return feet_per_second_squared / STANDARD_GRAVITY_FEET_PER_SECOND_SQUARED
    return feet_per_second_squared * METERS_PER_FOOT


def pixels_per_second_to_mph(speed: float) -> float:
    """Convert a model speed into canonical MPH without magic conversion values."""
    return speed * SECONDS_PER_HOUR / PIXELS_PER_MILE


def mph_to_pixels_per_second(speed_mph: float) -> float:
    """Convert canonical MPH into the model's world speed."""
    return speed_mph * PIXELS_PER_MILE / SECONDS_PER_HOUR
