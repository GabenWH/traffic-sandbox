"""Shared, change-driven landscape geometry in map coordinates."""
from math import cos, sin, pi, hypot
import numpy as np
from color_palette import panda_rgba

AREA_COLORS = {
    'forest': '#4c864e', 'meadow': '#91bb65', 'farmland': '#a99b62',
    'water': '#4f8fad', 'wetland': '#789d78',
}
AREA_DEPTH = {'meadow':-.46, 'forest':-.43, 'farmland':-.41, 'wetland':-.39, 'water':-.32}
WATER_COLOR = '#4f8fad'


def _add(triangles, face, color):
    rgba=panda_rgba(color)
    triangles.extend((*p,*rgba) for p in face)


def grass_triangles(city):
    """Return grassy ground and hill triangles with per-vertex color."""
    terrain=city.terrain
    left,top,right,bottom=terrain.bounds or (0,0,city.width,city.height)
    triangles=[]
    a,b,c,d=(left,top,-.5),(right,top,-.5),(right,bottom,-.5),(left,bottom,-.5)
    _add(triangles,(a,b,c,a,c,d),terrain.grass_color)
    for area in terrain.areas:
        if area.kind!='meadow':continue
        for face in area.triangles:
            _add(triangles,((x,y,-.46) for x,y in face),AREA_COLORS['meadow'])
    # Rings meet the base at z=-.5. Hills in the starter are deliberately
    # beyond the buildable map so roads and buildings retain their elevations.
    for hill in terrain.hills:
        rings=[]
        for ring in range(9):
            t=ring/8
            z=-.5 + hill.height * (1-t*t)**1.8
            rings.append([(hill.x+hill.radius_x*t*cos(2*pi*i/32),
                           hill.y+hill.radius_y*t*sin(2*pi*i/32),z) for i in range(32)])
        for ring in range(8):
            for i in range(32):
                j=(i+1)%32
                _add(triangles,(rings[ring][i],rings[ring+1][i],rings[ring+1][j],
                                rings[ring][i],rings[ring+1][j],rings[ring][j]),terrain.grass_color)
    return np.asarray(triangles,dtype='float32').reshape(-1,7)


def waterway_quads(points, width, z):
    """Join segments at shared mitred banks, avoiding holes at bends."""
    clean=[]
    for point in points:
        if not clean or tuple(point)!=clean[-1]: clean.append(tuple(point))
    if len(clean)<2: return []
    normals=[]
    for a,b in zip(clean,clean[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1]
        length=hypot(dx,dy); normals.append((-dy/length,dx/length))
    banks=[]
    for i,(x,y) in enumerate(clean):
        if i==0: nx,ny=normals[0]; scale=width/2
        elif i==len(clean)-1: nx,ny=normals[-1]; scale=width/2
        else:
            a,b=normals[i-1],normals[i]
            nx,ny=a[0]+b[0],a[1]+b[1]
            length=hypot(nx,ny)
            if length<1e-6: nx,ny=b; scale=width/2
            else:
                nx,ny=nx/length,ny/length
                scale=min(width, (width/2)/max(.5,nx*b[0]+ny*b[1]))
        banks.append(((x+nx*scale,y+ny*scale,z),(x-nx*scale,y-ny*scale,z)))
    return [(a[0],b[0],b[1],a[1]) for a,b in zip(banks,banks[1:])]


def solid_landscape(buf, terrain):
    for area in terrain.areas:
        if area.kind=='meadow':continue
        for face in area.triangles:
            z = AREA_DEPTH[area.kind]
            buf.faces([[(x,y,z) for x,y in face]],AREA_COLORS[area.kind])
    for water in terrain.waterways:
        z = -.29 if water.kind == 'river' else -.30
        buf.quads(waterway_quads(water.points, water.width, z), WATER_COLOR)
