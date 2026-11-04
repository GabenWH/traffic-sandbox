"""Geometry for optional non-rectangular building footprints."""
from math import dist


def open_ring(points):
    """Remove a repeated closing point and consecutive duplicate vertices."""
    result = []
    for point in points:
        point = tuple(point)
        if not result or point != result[-1]:
            result.append(point)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    return result


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def distance_to_segment(point, start, end):
    dx, dy = end[0]-start[0], end[1]-start[1]
    length_squared = dx*dx+dy*dy
    if not length_squared:
        return dist(point, start)
    t = max(0.0, min(1.0, ((point[0]-start[0])*dx+(point[1]-start[1])*dy)/length_squared))
    return dist(point, (start[0]+t*dx, start[1]+t*dy))


def contains_point(points, point):
    """Include the polygon edge, as the existing rectangular parcel does."""
    ring = open_ring(points)
    if len(ring) < 3:
        return False
    inside = False
    x, y = point
    for a, b in zip(ring, ring[1:]+ring[:1]):
        if distance_to_segment(point, a, b) <= 1e-7:
            return True
        if (a[1] > y) != (b[1] > y) and x < a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]):
            inside = not inside
    return inside


def distance_to_ring(points, point):
    ring = open_ring(points)
    if len(ring) < 3:
        raise ValueError('A building footprint needs at least three vertices')
    if contains_point(ring, point):
        return 0.0
    return min(distance_to_segment(point, a, b) for a, b in zip(ring, ring[1:]+ring[:1]))


def triangulate_ring(points):
    """Triangulate a simple (possibly concave) outer ring without new dependencies."""
    ring = open_ring(points)
    if len(ring) < 3:
        raise ValueError('A building footprint needs at least three vertices')
    # Remove vertices that merely subdivide a straight edge.
    changed = True
    while changed and len(ring) > 3:
        changed = False
        for i in range(len(ring)):
            a, b, c = ring[i-1], ring[i], ring[(i+1)%len(ring)]
            if abs(_cross(a,b,c)) <= 1e-9 and (b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]) >= 0:
                ring.pop(i)
                changed = True
                break
    origin = ring[0]
    area2 = sum(_cross(origin, a, b) for a,b in zip(ring, ring[1:]+ring[:1]))
    if abs(area2) <= 1e-9:
        raise ValueError('A building footprint must have nonzero area')
    direction = 1 if area2 > 0 else -1
    indices = list(range(len(ring)))
    triangles = []
    while len(indices) > 3:
        for i, idx in enumerate(indices):
            previous, following = indices[i-1], indices[(i+1)%len(indices)]
            a,b,c = ring[previous], ring[idx], ring[following]
            if direction*_cross(a,b,c) <= 1e-9:
                continue
            if any(direction*_cross(a,b,ring[j]) >= -1e-9 and
                   direction*_cross(b,c,ring[j]) >= -1e-9 and
                   direction*_cross(c,a,ring[j]) >= -1e-9
                   for j in indices if j not in (previous,idx,following)):
                continue
            triangles.append((a,b,c))
            indices.pop(i)
            break
        else:
            raise ValueError('Building footprint is not a simple polygon')
    triangles.append(tuple(ring[i] for i in indices))
    return triangles


def prism_geometry(points, bottom, top):
    """Return side quads and top triangles at a building's true outline."""
    ring = open_ring(points)
    sides = [((a[0],a[1],bottom), (b[0],b[1],bottom),
              (b[0],b[1],top), (a[0],a[1],top))
             for a,b in zip(ring, ring[1:]+ring[:1])]
    roof = [tuple((x,y,top) for x,y in triangle) for triangle in triangulate_ring(ring)]
    return sides, roof


def subtract_courtyards(exteriors, courtyards):
    """Partition exterior-minus-holes into simple filled polygons.

    Horizontal bands at every vertex avoid introducing bridges across holes.
    Within each band, edge ordering is constant and even/odd spans are filled.
    The resulting parts use the existing footprint/render/save contracts.
    """
    outers=[open_ring(r) for r in exteriors]
    holes=[open_ring(r) for r in courtyards]
    rings=outers+holes
    for ring in rings:triangulate_ring(ring)
    def edges(ring):return list(zip(ring,ring[1:]+ring[:1]))
    def meet(a,b,c,d):
        if _cross(a,b,c)*_cross(a,b,d)<0 and _cross(c,d,a)*_cross(c,d,b)<0:return True
        return any(distance_to_segment(p,q,r)<1e-7 for p,q,r in
                   ((a,c,d),(b,c,d),(c,a,b),(d,a,b)))
    for hole in holes:
        if not any(all(contains_point(outer,p) for p in hole) and
                   not any(meet(a,b,c,d) for a,b in edges(hole) for c,d in edges(outer))
                   for outer in outers):
            raise ValueError('Courtyard must be strictly inside a building exterior')
    for i,hole in enumerate(holes):
        for other in holes[i+1:]:
            if (contains_point(hole,other[0]) or contains_point(other,hole[0]) or
                    any(meet(a,b,c,d) for a,b in edges(hole) for c,d in edges(other))):
                raise ValueError('Courtyards must not overlap')
    levels=sorted({p[1] for r in rings for p in r})
    segments=[(a,b) for r in rings for a,b in edges(r) if a[1]!=b[1]]
    parts=[]
    for low,high in zip(levels,levels[1:]):
        if high-low<1e-7:continue
        mid=(low+high)/2
        def at(edge,y):
            a,b=edge
            return a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
        active=sorted((e for e in segments if min(e[0][1],e[1][1])<mid<max(e[0][1],e[1][1])),
                      key=lambda e:at(e,mid))
        if len(active)%2:raise ValueError('Invalid courtyard boundary')
        for left,right in zip(active[::2],active[1::2]):
            if at(right,mid)-at(left,mid)<1e-7:continue
            part=open_ring([(at(left,low),low),(at(right,low),low),
                            (at(right,high),high),(at(left,high),high)])
            if len(part)>=3:
                triangulate_ring(part)
                parts.append(part)
    if not parts:raise ValueError('Courtyards leave no building area')
    return parts
