"""Retained editor overlays with the small Tk Canvas API the existing tools use.

World scenery and all actors use native scene buffers, not this adapter. Only
tool previews, route highlights and HUD annotations are compiled when changed.
"""
from math import cos,sin,pi
from color_palette import panda_rgba
from .scene_buffers import GeometryBuffer


class NativeCanvas:
    def __init__(self,widget,view):
        self._widget=widget;self.view=view;self._items={};self._next=1;self._dirty=False

    def __getattr__(self,name):return getattr(self._widget,name)
    def winfo_width(self):return self.view.frame.winfo_width()
    def winfo_height(self):return self.view.frame.winfo_height()
    def winfo_rootx(self):return self.view.frame.winfo_rootx()
    def winfo_rooty(self):return self.view.frame.winfo_rooty()

    def configure(self,**kwargs):
        if self._widget is not None:self._widget.configure(**kwargs)
        if self.view is not None and 'cursor' in kwargs:self.view.frame.configure(cursor=kwargs['cursor'])
    config=configure

    def _create(self,kind,coords,options):
        if len(coords)==1 and hasattr(coords[0],'__iter__'):coords=tuple(coords[0])
        tags=options.get('tags',());options=dict(options)
        options['tags']=(tags,) if isinstance(tags,str) else tuple(tags)
        ident=self._next;self._next+=1
        self._items[ident]=[kind,list(coords),options];self._dirty=True;return ident
    def create_line(self,*coords,**options):return self._create('line',coords,options)
    def create_polygon(self,*coords,**options):return self._create('polygon',coords,options)
    def create_rectangle(self,*coords,**options):return self._create('rectangle',coords,options)
    def create_oval(self,*coords,**options):return self._create('oval',coords,options)
    def create_text(self,*coords,**options):return self._create('text',coords,options)

    def find_withtag(self,tag):
        return tuple(i for i,(_,_,o) in self._items.items() if tag=='all' or i==tag or tag in o['tags'])
    def find_all(self):return tuple(self._items)
    def delete(self,*tags):
        for tag in tags:
            for ident in self.find_withtag(tag):self._items.pop(ident);self._dirty=True
    def coords(self,ident,*coords):
        if ident not in self._items:return []
        if coords:
            if len(coords)==1 and hasattr(coords[0],'__iter__'):coords=coords[0]
            self._items[ident][1]=list(coords);self._dirty=True
        return list(self._items[ident][1])
    def itemconfigure(self,tag,**options):
        for ident in self.find_withtag(tag):
            current=self._items[ident][2]
            if any(current.get(k)!=v for k,v in options.items()):current.update(options);self._dirty=True
    itemconfig=itemconfigure
    def itemcget(self,ident,key):return self._items[ident][2].get(key,'')
    def gettags(self,ident):return self._items[ident][2]['tags'] if ident in self._items else ()
    def tag_raise(self,tag,*args):
        for ident in self.find_withtag(tag):self._items[ident]=self._items.pop(ident)
    def tag_lower(self,tag,*args):
        ids=self.find_withtag(tag);self._items={**{i:self._items[i] for i in ids},**self._items}
    lift=tag_raise
    lower=tag_lower
    def bbox(self,tag):
        points=[]
        for i in self.find_withtag(tag):
            kind,coords,options=self._items[i]
            if kind=='text':
                x,y=coords;points.extend([(x,y),(x+len(options.get('text',''))*8,y+18)])
            else:points.extend(zip(coords[::2],coords[1::2]))
        if not points:return None
        xs,ys=zip(*points);return min(xs),min(ys),max(xs),max(ys)
    def find_overlapping(self,x1,y1,x2,y2):
        result=[]
        for i in self._items:
            b=self.bbox(i)
            if b and b[0]<=x2 and b[2]>=x1 and b[1]<=y2 and b[3]>=y1:result.append(i)
        return tuple(result)

    def flush(self):
        if not self._dirty:return
        buf=GeometryBuffer();texts=[]
        for kind,coords,o in self._items.values():
            if o.get('state')=='hidden':continue
            fill=o.get('fill','#000000' if kind in ('line','text') else '')
            outline=o.get('outline','#000000' if kind in ('rectangle','oval') else '')
            if kind=='text':
                font=o.get('font',('',11));size=abs(font[1])*1.333 if isinstance(font,tuple) and len(font)>1 else 15
                anchor=o.get('anchor','center');align=0 if 'w' in anchor else 2 if 'e' in anchor else 1
                texts.append((coords[0],coords[1],size,*panda_rgba(fill),o.get('width',0),align,str(o.get('text',''))));continue
            points=list(zip(coords[::2],coords[1::2]))
            if kind=='rectangle' and len(points)==2:
                (a,b),(c,d)=points;points=[(a,b),(c,b),(c,d),(a,d)]
            elif kind=='oval' and len(points)==2:
                (a,b),(c,d)=points;x,y=(a+c)/2,(b+d)/2
                points=[(x+(c-a)/2*cos(i*2*pi/24),y+(d-b)/2*sin(i*2*pi/24)) for i in range(24)]
            vertices=[(x,0,-y) for x,y in points]
            if kind=='line':
                if fill:buf.line(vertices,fill)
            else:
                if fill and len(vertices)>2:buf.faces([(vertices[0],vertices[i],vertices[i+1]) for i in range(1,len(vertices)-1)],fill)
                if outline:buf.line(vertices,outline,True)
        self.view.overlay_scene.replace_static(*buf.arrays())
        self.view.overlay_scene.replace_texts(texts);self._dirty=False
