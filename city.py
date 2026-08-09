"""City-builder world data, kept separate from vehicle simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from models import Road


class ZoneType(StrEnum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    CIVIC = "civic"


@dataclass
class Terrain:
    """Terrain appearance for the buildable map."""

    grass_color: str = "#78b85a"
    trees: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class Parcel:
    x: float
    y: float
    width: float
    height: float
    zone: ZoneType | None = None


@dataclass
class Building:
    name: str
    parcel: Parcel
    residents: int = 0
    jobs: int = 0


@dataclass
class CityMap:
    """Own terrain and city objects; traffic uses its roads later."""

    terrain: Terrain = field(default_factory=Terrain)
    roads: list[Road] = field(default_factory=list)
    parcels: list[Parcel] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)

    def zone_parcel(self, parcel: Parcel, zone: ZoneType) -> None:
        parcel.zone = zone
