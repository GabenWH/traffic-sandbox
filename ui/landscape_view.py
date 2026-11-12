"""Grass surface for the native viewer, rebuilt only when the city changes.

The procedural patch and bounded tuft scatter are adapted from Ferns-Forest's
MeadowGround.shader / MeadowScatter.cginc (Unity Built-in RP) to Panda GLSL.
World-space feet are converted to metres to preserve the original scale.
"""
from panda3d.core import Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat, GeomVertexWriter, Shader
from .landscape_geometry import grass_triangles

VERTEX = '''#version 330
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelViewMatrix;
in vec4 p3d_Vertex;
in vec4 p3d_Color;
out vec3 position_m;
out vec4 tint;
out vec3 view_position_m;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    position_m = p3d_Vertex.xyz * 0.3048;
    view_position_m = (p3d_ModelViewMatrix * p3d_Vertex).xyz * 0.3048;
    tint = p3d_Color;
}
'''
FRAGMENT = '''#version 330
in vec3 position_m;
in vec4 tint;
in vec3 view_position_m;
out vec4 fragColor;
float hash2(vec2 p) {
    vec3 q = fract(vec3(p.x,p.y,p.x) * .1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x+q.y)*q.z);
}
float triangleNoise(vec2 p) {
    vec2 cell=floor(p), f=fract(p);
    float b=hash2(cell+vec2(1,0)), c=hash2(cell+vec2(0,1));
    if (f.x+f.y<=1.) return hash2(cell)*(1.-f.x-f.y)+b*f.x+c*f.y;
    return hash2(cell+1.)*(f.x+f.y-1.)+b*(1.-f.y)+c*(1.-f.x);
}
float mark(vec2 cell, float index, vec2 p, float pixel) {
    if (hash2(cell+vec2(71.7,-19.3)) >= .55) return 0.;
    if (index > .5 && hash2(cell+vec2(-37.1,93.7)) >= .8) return 0.;
    vec2 center=cell+vec2(hash2(cell+vec2(13.1,57.7)),hash2(cell+vec2(-51.3,11.9)));
    if (index > .5) center+=(vec2(hash2(cell+vec2(23.9,-61.1)),hash2(cell+vec2(-73.3,29.7)))-.5)*.3;
    vec2 seed=cell+vec2(index*137.3,-index*79.1);
    float angle=hash2(seed+vec2(47.3,83.1))*6.28318530718;
    vec2 dir=vec2(cos(angle),sin(angle));
    float width=mix(.035,.09,hash2(seed+vec2(-17.7,41.3)));
    float halfLength=mix(.14,.30,hash2(seed+vec2(89.9,-31.7)));
    vec2 q=p-center;
    float along=dot(q,dir), across=dot(q,vec2(-dir.y,dir.x));
    float feather=clamp(pixel,.001,.08);
    float taper=clamp((halfLength-along)/(2.*halfLength),0.,1.);
    float side=1.-smoothstep(width*taper,width*taper+feather,abs(across));
    float tip=1.-smoothstep(halfLength-feather,halfLength+feather,abs(along));
    return side*tip;
}
void main() {
    vec2 broadUV=position_m.xy*.32;
    vec2 warp=vec2(triangleNoise(broadUV*.47+13.1),triangleNoise(broadUV*.47-7.3))-.5;
    vec2 warped=broadUV+warp*.25;
    vec2 rotated=vec2(.8*warped.x-.6*warped.y,.6*warped.x+.8*warped.y)*1.73+5.7;
    float broad=triangleNoise(warped)*.7+triangleNoise(rotated)*.3;
    float broadWidth=max(.06,fwidth(broad));
    float patches=smoothstep(.43-broadWidth,.57+broadWidth,broad);
    float broadPixel=max(max(fwidth(warped.x),fwidth(warped.y)),max(fwidth(rotated.x),fwidth(rotated.y)));
    patches=mix(.5,patches,1.-smoothstep(.3,1.,broadPixel));
    vec3 meadow=mix(tint.rgb,tint.rgb*vec3(1.13,1.05,.83),patches*.55);
    vec2 uv=position_m.xy*9.;
    float pixel=max(.001,max(fwidth(uv.x),fwidth(uv.y)));
    float weight=(1.-smoothstep(8.,24.,length(view_position_m)))*(1.-smoothstep(.2,.75,pixel));
    float stroke=0.;
    if (weight>0.) {
        vec2 cell=floor(uv);
        for (int y=-1;y<=1;y++) for (int x=-1;x<=1;x++)
            for (int i=0;i<2;i++) stroke=max(stroke,mark(cell+vec2(x,y),float(i),uv,pixel));
    }
    vec3 normal=normalize(cross(dFdx(position_m),dFdy(position_m)));
    if (normal.z<0.) normal=-normal;
    float light=.72+.28*max(0.,dot(normal,normalize(vec3(-.4,-.35,1.))));
    fragColor=vec4(mix(meadow,vec3(.854,.854,.485),stroke*.3*weight)*light,tint.a);
}
'''


class LandscapeView:
    def __init__(self, parent):
        self.root=parent.attachNewNode('landscape')
        self.root.setScale(1,-1,1)
        self.root.setTwoSided(True)
        self.shader=Shader.make(Shader.SL_GLSL, VERTEX, FRAGMENT)
        self._key=None

    def replace(self, city):
        terrain=city.terrain
        key=(city.width,city.height,terrain.bounds,terrain.grass_color,
             tuple(a for a in terrain.areas if a.kind=='meadow'),tuple(terrain.hills))
        if key==self._key:return
        rows=grass_triangles(city)
        data=GeomVertexData('grass',GeomVertexFormat.getV3c4(),Geom.UHStatic)
        data.setNumRows(len(rows))
        vertex,color=GeomVertexWriter(data,'vertex'),GeomVertexWriter(data,'color')
        for x,y,z,r,g,b,a in rows:
            vertex.addData3(float(x),float(y),float(z))
            color.addData4(float(r),float(g),float(b),float(a))
        triangles=GeomTriangles(Geom.UHStatic)
        for i in range(0,len(rows),3): triangles.addVertices(i,i+1,i+2)
        triangles.closePrimitive()
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode('grass'); node.addGeom(geom)
        replacement=self.root.attachNewNode(node)
        replacement.setShader(self.shader)
        for child in self.root.getChildren():
            if child != replacement: child.removeNode()
        self._key=key

    def close(self):
        self.root.removeNode()
