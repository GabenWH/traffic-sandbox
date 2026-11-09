"""Shared stationary pedestrian presentation for stops and crossing queues.

Callers own queue membership and release permissions. This module only places
individual people; it never boards a bus or grants permission to cross a road.
Coordinates and spacing are in world feet, matching moving pedestrians.
"""
from dataclasses import dataclass
from math import hypot

@dataclass(frozen=True)
class WaitingArea:
    people: tuple
    position: tuple
    along: tuple = (1., 0.)
    away: tuple = (0., 1.)
    elevation: float = 0.

@dataclass(frozen=True)
class WaitingPerson:
    id: int
    position: tuple
    heading: tuple
    elevation: float


def waiting_person_poses(areas):
    """Arrange each queue in four-wide rows extending away from the road."""
    for area in areas:
        size=hypot(*area.along)
        tx,ty=(area.along[0]/size,area.along[1]/size) if size else (1.,0.)
        nx,ny=-ty,tx
        if nx*area.away[0]+ny*area.away[1]<0:nx,ny=-nx,-ny
        for index,pid in enumerate(area.people):
            column,row=index%4,index//4
            yield WaitingPerson(pid,
                (area.position[0]+column*3*tx+row*3*nx,
                 area.position[1]+column*3*ty+row*3*ny),
                (-nx,-ny),area.elevation)
