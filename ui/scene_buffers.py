"""Compile model geometry on edits; this module never constructs Panda objects."""
from math import cos,sin,pi,sqrt,dist,hypot
import numpy as np
from color_palette import Palette,panda_rgba
from building_footprints import open_ring,prism_geometry
from models import BuildablePhase,WorkType,IntersectionKind
from mobility import vehicle_link_points
from land_ports import land_port_positions
from .scene_geometry import road_deck_quads,road_divider_runs,roundabout_deck_quads,cul_de_sac_deck_quads


def box_quads(a,b,c,d,e,f):
    p=[(a,b,c),(d,b,c),(d,e,c),(a,e,c),(a,b,f),(d,b,f),(d,e,f),(a,e,f)]
    return [tuple(p[i] for i in face) for face in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]]


class GeometryBuffer:
    def __init__(self):self.triangles=[];self.lines=[]
    def faces(self,faces,color):
        rgba=panda_rgba(color)
        for face in faces:
            for p in face:self.triangles.append((*p,*rgba))
    def quads(self,quads,color):
        self.faces(((q[i] for i in (0,1,2,0,2,3)) for q in quads),color)
    def line(self,points,color,closed=False):
        rgba=panda_rgba(color);points=list(points)
        if closed and points:points.append(points[0])
        for a,b in zip(points,points[1:]):self.lines.extend([(*a,*rgba),(*b,*rgba)])
    def disc(self,x,y,z,radius,color):
        self.faces([((x,y,z),(x+radius*cos(i*pi/24),y+radius*sin(i*pi/24),z),
                     (x+radius*cos((i+1)*pi/24),y+radius*sin((i+1)*pi/24),z)) for i in range(48)],color)
    def stroke(self,points,color,width=1,dash=(),plane='xy',clip=None):
        """Expand visible strokes only; retain dash phase across clipped spans."""
        points=list(points);axis=1 if plane=='xy' else 2
        pattern=tuple(float(v) for v in dash if float(v)>0)
        if len(pattern)%2:pattern=pattern*2
        cycle=sum(pattern);phase=0.
        for a,b in zip(points,points[1:]):
            dx,dy=b[0]-a[0],b[axis]-a[axis];length=hypot(dx,dy)
            if not length:continue
            offset=[0.,0.,0.];offset[0]=-dy/length*width/2;offset[axis]=dx/length*width/2
            low,high=0.,1.
            if clip is not None:
                left,bottom,right,top=clip;margin=width/2
                # Liang-Barsky clipping before dash expansion. A projected
                # endpoint can be billions of pixels away; skipping its dashes
                # arithmetically keeps time and memory bounded by the viewport.
                for p,q in ((-dx,a[0]-left+margin),(dx,right+margin-a[0]),
                            (-dy,a[axis]-bottom+margin),(dy,top+margin-a[axis])):
                    if abs(p)<1e-12:
                        if q<0:high=-1.;break
                    elif p<0:low=max(low,q/p)
                    else:high=min(high,q/p)
            start=max(0.,low)*length
            stop=min(1.,high)*length-start
            origin=[a[j]+(b[j]-a[j])*start/length for j in range(3)]
            at=0.
            index=0;remaining=float('inf')
            if pattern:
                position=(phase+start)%cycle
                while position>=pattern[index]:
                    position-=pattern[index];index=(index+1)%len(pattern)
                remaining=pattern[index]-position
            while at<stop-1e-9:
                end=min(stop,at+remaining)
                if index%2==0:
                    first=[origin[j]+(b[j]-a[j])*at/length for j in range(3)]
                    last=[origin[j]+(b[j]-a[j])*end/length for j in range(3)]
                    self.quads([tuple(tuple(p[j]+sign*offset[j] for j in range(3))
                                for p,sign in ((first,1),(last,1),(last,-1),(first,-1)))],color)
                consumed=end-at;at=end;remaining-=consumed
                if pattern and remaining<1e-9:index=(index+1)%len(pattern);remaining=pattern[index]
            if pattern:phase=(phase+length)%cycle
    def arrays(self):
        return (np.asarray(self.triangles,dtype='float32').reshape(-1,7),
                np.asarray(self.lines,dtype='float32').reshape(-1,7))


def _building(buf,b):
    parcel=b.parcel
    rings=[open_ring(r) for r in parcel.footprints] if parcel.footprints else []
    if not rings:
        x,y=parcel.x+parcel.width/2,parcel.y+parcel.height/2
        w,d=parcel.width*.88,parcel.height*.88
        buf.quads(box_quads(parcel.x,parcel.y,0,parcel.x+parcel.width,parcel.y+parcel.height,2),'#777c80')
        rings=[[(x-w/2,y-d/2),(x+w/2,y-d/2),(x+w/2,y+d/2),(x-w/2,y+d/2)]]
    height=min(48,12+4*sqrt(max(1,b.residents+b.jobs)/4))
    building=b.phase in (BuildablePhase.PLANNING,BuildablePhase.UNDER_CONSTRUCTION)
    progress=b.active_work.progress if building and b.active_work and b.active_work.kind is WorkType.CONSTRUCTION else 0
    top=2+height*(progress if building else 1)
    for ring in rings:
        for low,high,color in [(0,2,'#777c80'),(2,top,b.color),*(([(top,top+2,'#454b52')]) if not building else [])]:
            if high<=low:continue
            walls,faces=prism_geometry(ring,low,high);buf.quads(walls,color);buf.faces(faces,color)
        if building:
            for x,y in ring:buf.line([(x,y,2),(x,y,2+height)],'#ffb000')
            buf.line([(x,y,2+height) for x,y in ring],'#ffb000',True)
        elif not parcel.footprints:
            # Keep the original facade detail, compiled once with the building.
            columns=max(1,min(5,int(w//24)));ww=min(5,w/(columns*2.5));wh=min(5,height/6)
            for z in (2+height*.38,2+height*.72):
                for column in range(columns):
                    wx=x+(column-(columns-1)/2)*w/(columns+1)
                    for wy in (y-d/2-.15,y+d/2+.15):
                        buf.quads(box_quads(wx-ww/2,wy-.25,z-wh/2,wx+ww/2,wy+.25,z+wh/2),'#8ecae6')


def _tree(buf,index,x,y):
    redwood=index%4==0;height=55 if redwood else 30
    def cone(radius,top_radius,low,high,color):
        faces=[]
        for i in range(8):
            a,b=2*pi*i/8,2*pi*(i+1)/8
            va=(x+radius*cos(a)*height,y+radius*sin(a)*height,low*height)
            vb=(x+radius*cos(b)*height,y+radius*sin(b)*height,low*height)
            ta=(x+top_radius*cos(a)*height,y+top_radius*sin(a)*height,high*height)
            tb=(x+top_radius*cos(b)*height,y+top_radius*sin(b)*height,high*height)
            faces.extend([(va,vb,ta),((x,y,low*height),vb,va)])
            if top_radius:faces.extend([(vb,tb,ta),((x,y,high*height),ta,tb)])
        buf.faces(faces,color)
    cone(.065 if redwood else .045,.018 if redwood else .045,0,.96 if redwood else .7,Palette.ROUNDABOUT_APRON)
    for tier in range(9 if redwood else 1):
        low=.32+tier*.065 if redwood else .22
        cone(.19*(1-tier/11) if redwood else .30,0,low,min(1,low+.22) if redwood else 1,
             Palette.TREE_CANOPY if tier%2 or not redwood else Palette.TREE_OUTLINE)


def compile_city(city):
    """Return owned contiguous triangle/line buffers, each row XYZ + RGBA."""
    buf=GeometryBuffer()
    buf.quads([((0,0,-.5),(city.width,0,-.5),(city.width,city.height,-.5),(0,city.height,-.5))],city.terrain.grass_color)
    for road in city.roads:
        decks=road_deck_quads(road);buf.quads(decks,Palette.ROAD_SURFACE)
        sides=[]
        for a,b,c,d in decks:
            sides.extend([(a,d,(d[0],d[1],d[2]-2),(a[0],a[1],a[2]-2)),
                          (b,c,(c[0],c[1],c[2]-2),(b[0],b[1],b[2]-2))])
        buf.quads(sides,Palette.ROAD_EDGE)
        for i,(a,b) in enumerate(zip(road.centerline,road.centerline[1:])):
            for f in ((.25,.75) if dist(a,b)>=40 else (.5,)):
                h=road.elevations[i]+f*(road.elevations[i+1]-road.elevations[i])
                if h>=6:
                    x,y=a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1])
                    buf.quads(box_quads(x-2.5,y-2.5,0,x+2.5,y+2.5,h),Palette.ROAD_EDGE)
        if road.forward_lane_count and road.reverse_lane_count:
            for run in road_divider_runs(road,city.intersections):
                buf.line([(x,y,z+.2) for x,y,z in run],Palette.ROAD_DIVIDER)
    for junction in city.intersections:
        if junction.kind is IntersectionKind.ROUNDABOUT:
            for quads,color in zip(roundabout_deck_quads(junction),
                [Palette.ROAD_SURFACE,Palette.ROUNDABOUT_APRON,Palette.ROUNDABOUT_ISLAND]):buf.quads(quads,color)
        elif junction.kind is not IntersectionKind.CUL_DE_SAC and junction.connected_roads:
            buf.disc(*junction.position,junction.elevation+.03,junction.radius,Palette.ROAD_SURFACE)
        if junction.kind is IntersectionKind.ROUNDABOUT:
            from roundabouts import yield_mark
            from mobility import road_output_node
            graph=city.mobility.layers['vehicles'].graph
            for port in junction.incoming_ports():
                entry=next((t.edge.value for t in graph.transitions_from(road_output_node(port))
                            if getattr(t.edge.value,'roundabout_role','')=='entry'),None)
                if entry is None:continue
                p,h=yield_mark(entry);side=(-h[1],h[0]);half=port.width/2
                buf.stroke([(p[0]-side[0]*half,p[1]-side[1]*half,junction.elevation+.12),
                            (p[0]+side[0]*half,p[1]+side[1]*half,junction.elevation+.12)],Palette.ROAD_MARKING,2,(3,3))
        for port in {c.source_output for c in junction.lane_connections if c.control.kind.value=='stop'}:
            sx,sy=-port.heading[1]*port.width/2,port.heading[0]*port.width/2
            x,y=port.position
            buf.stroke([(x-sx,y-sy,junction.elevation+.12),(x+sx,y+sy,junction.elevation+.12)],Palette.ROAD_MARKING,2)
    for bulb in city.cul_de_sacs:
        pavement,curb=cul_de_sac_deck_quads(bulb)
        buf.quads(pavement,Palette.ROAD_SURFACE)
        buf.quads(curb,Palette.ROAD_EDGE)
    for road in city.roads:
        if road.phase is BuildablePhase.DEMOLISHING:
            buf.stroke([(*p,road.elevation_at(p)+.15) for p in road.centerline],
                       '#ffb000',max(2,road.width/3),(5,4))
    for lot in city.parking_lots:
        for surface in lot.driveway_surfaces+([lot.surface] if lot.surface else []):
            _,triangles=prism_geometry(surface,.04,.05);buf.faces(triangles,'#606568')
        for space in lot.spaces:buf.line([(x,y,.08) for x,y in space.corners],'#e9e2c7',True)
    for building in city.buildings:_building(buf,building)
    for i,(x,y) in enumerate(city.terrain.trees):_tree(buf,i,x,y)
    for x,y in land_port_positions(city):
        for dy in (-14,14):buf.line([(x+12,y+dy,.5),(x+12,y+dy,34)],'#ffd166')
        buf.line([(x+12,y-14,34),(x+12,y+14,34)],'#ffd166')
        buf.line([(x-18,y,1),(x+5,y,1),(x-3,y-8,1)],'#ffd166')
        buf.line([(x+5,y,1),(x-3,y+8,1)],'#ffd166')
    return buf.arrays()


def route_heights(city,car,roads=None):
    """Compile the actual route's elevation ruler once, without XY road search."""
    roads={r.id:r for r in city.roads} if roads is None else roads
    points=[]
    for link in car.route.edges:
        geometry=vehicle_link_points(link)
        if not geometry:continue
        value=link.value;lane=getattr(value,'lane',value)
        road=roads.get(getattr(lane,'road_id',None))
        if road is not None:
            heights=[road.elevation_at(p) for p in geometry]
        elif getattr(lane,'road_id',None) is not None and str(lane.road_id).startswith('roundabout:'):
            junction=next((j for j in getattr(city,'intersections',()) if f'roundabout:{j.id}'==lane.road_id),None)
            if junction is None:raise ValueError('Route references a missing roundabout')
            heights=[junction.elevation]*len(geometry)
        elif link.kind=='lane_connection':
            source=value.source_output.road
            destination=value.destination_input.road
            start=source.elevation_at(value.source_output.position) if source else 0.
            end=destination.elevation_at(value.destination_input.position) if destination else start
            lengths=[0.]
            for a,b in zip(geometry,geometry[1:]):lengths.append(lengths[-1]+dist(a,b))
            heights=[start+(end-start)*d/lengths[-1] if lengths[-1] else start for d in lengths]
        else:heights=[getattr(getattr(value,'port',None),'elevation',0.)]*len(geometry)
        for xy,z in zip(geometry,heights):
            if points and points[-1][:2]==tuple(xy):continue
            points.append((*xy,z))
    if not points:return np.array([(0.,0.)],dtype='float64')
    ruler=[(0.,points[0][2])];travelled=0.
    for a,b in zip(points,points[1:]):
        travelled+=dist(a[:2],b[:2]);ruler.append((travelled,b[2]))
    if all(z==ruler[0][1] for _,z in ruler):ruler=ruler[:1]
    return np.asarray(ruler,dtype='float64')
