"""Map-space landscape data. Coordinates and widths are in feet."""
from dataclasses import dataclass
from functools import cached_property
from building_footprints import triangulate_ring
from math import isfinite


AREA_KINDS = frozenset({'forest', 'meadow', 'farmland', 'water', 'wetland'})
WATERWAY_KINDS = frozenset({'stream', 'river', 'canal', 'ditch'})


def _points(points, minimum):
    result = tuple((float(x), float(y)) for x, y in points)
    if len(result) < minimum or any(not isfinite(v) for p in result for v in p):
        raise ValueError('Invalid landscape coordinates')
    return result


@dataclass(frozen=True)
class LandscapeArea:
    kind: str
    points: tuple
    source: str = ''

    def __post_init__(self):
        if self.kind not in AREA_KINDS:
            raise ValueError('Unknown landscape area kind')
        object.__setattr__(self, 'points', _points(self.points, 3))

    @cached_property
    def triangles(self):
        # Areas are immutable, so their tessellation is valid for their lifetime.
        return tuple(tuple(face) for face in triangulate_ring(self.points))


@dataclass(frozen=True)
class Waterway:
    kind: str
    points: tuple
    width: float
    source: str = ''

    def __post_init__(self):
        if self.kind not in WATERWAY_KINDS:
            raise ValueError('Unknown waterway kind')
        object.__setattr__(self, 'points', _points(self.points, 2))
        width = float(self.width)
        if not isfinite(width) or width <= 0:
            raise ValueError('Waterway width must be positive and finite')
        object.__setattr__(self, 'width', width)


@dataclass(frozen=True)
class ScenicHill:
    x: float
    y: float
    radius_x: float
    radius_y: float
    height: float

    def __post_init__(self):
        if not all(isfinite(float(v)) for v in (self.x,self.y,self.radius_x,self.radius_y,self.height)):
            raise ValueError('Hill values must be finite')
        if self.radius_x <= 0 or self.radius_y <= 0 or self.height <= 0:
            raise ValueError('Hill dimensions must be positive')


def starter_landscape(width=5000, height=3500):
    """A repeatable fictional starter landscape, independent of Arcata data."""
    areas = [
        LandscapeArea('forest', ((80,150),(1000,80),(1460,430),(1200,980),(400,1080),(50,700))),
        LandscapeArea('forest', ((3470,2260),(4220,2020),(4890,2310),(4930,3330),(3700,3380),(3270,2900))),
        LandscapeArea('meadow', ((1430,140),(2900,120),(3170,750),(2400,1090),(1510,920))),
        LandscapeArea('farmland', ((2750,300),(3840,260),(3950,850),(2870,940))),
        LandscapeArea('farmland', ((2840,1020),(3950,940),(4050,1510),(2920,1580))),
        LandscapeArea('meadow', ((610,2330),(1880,2260),(2110,3200),(530,3320))),
    ]
    waterways = [
        Waterway('river', ((0,1920),(620,1900),(1180,1810),(1750,1850),(2340,1740),(2950,1790),(3540,1720),(4200,1790),(5000,1710)), 75),
        Waterway('stream', ((1600,0),(1630,400),(1570,800),(1700,1160),(1650,1460),(1750,1850)), 18),
    ]
    hills = [ScenicHill(-950,650,850,1450,210), ScenicHill(6050,2150,1000,1800,280),
             ScenicHill(2400,4400,2100,800,180)]
    sx,sy=width/5000,height/3500
    if sx!=1 or sy!=1:
        areas=[LandscapeArea(a.kind, [(x*sx,y*sy) for x,y in a.points], a.source) for a in areas]
        waterways=[Waterway(w.kind,[(x*sx,y*sy) for x,y in w.points],w.width,w.source) for w in waterways]
        hills=[ScenicHill(h.x*sx,h.y*sy,h.radius_x*sx,h.radius_y*sy,h.height) for h in hills]
    return areas, waterways, hills
