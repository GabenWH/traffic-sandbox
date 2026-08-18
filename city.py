"""City-builder world data, kept separate from vehicle simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from random import Random

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

    @classmethod
    def starter_terrain(cls) -> "Terrain":
        """Create a repeatable, lightly wooded buildable landscape."""
        random = Random(41)
        return cls(trees=[(random.randrange(80, 4920), random.randrange(80, 3420)) for _ in range(180)])


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

    width: float = 5000
    height: float = 3500
    terrain: Terrain = field(default_factory=Terrain.starter_terrain)
    roads: list[Road] = field(default_factory=list)
    parcels: list[Parcel] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)

    def zone_parcel(self, parcel: Parcel, zone: ZoneType) -> None:
        parcel.zone = zone
