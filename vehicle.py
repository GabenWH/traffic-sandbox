"""Shared public shape of a vehicle, independent of its road network."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal, Protocol, runtime_checkable


Point = tuple[float, float]
VehicleShape = Literal["car", "material_truck", "crew_truck"]


@dataclass(frozen=True)
class VehicleAppearance:
    """Data needed to choose and decorate a vehicle model in any view."""

    kind: str = "car"
    shape: VehicleShape = "car"
    visual_key: str | None = None
    cargo_key: str | None = None
    load_fraction: float = 0.0
    workers: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("Vehicle kind must be a nonempty string")
        if self.shape not in ("car", "material_truck", "crew_truck"):
            raise ValueError("Unsupported vehicle shape")
        if not isfinite(self.load_fraction) or not 0 <= self.load_fraction <= 1:
            raise ValueError("Vehicle load fraction must be between zero and one")
        if isinstance(self.workers, bool) or not isinstance(self.workers, int) or self.workers < 0:
            raise ValueError("Vehicle worker count must be a nonnegative integer")


@runtime_checkable
class Vehicle(Protocol):
    """Position, dimensions, and presentation shared by app road users."""

    @property
    def id(self) -> str: ...

    @property
    def position(self) -> Point: ...

    @property
    def heading(self) -> Point: ...

    @property
    def length(self) -> float: ...

    @property
    def width(self) -> float: ...

    @property
    def speed(self) -> float: ...

    @property
    def color(self) -> str: ...

    @property
    def appearance(self) -> VehicleAppearance: ...
