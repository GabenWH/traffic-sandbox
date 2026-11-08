"""One embedded Panda window; C++ owns scene meshes and actor presentation."""
from __future__ import annotations
import tkinter as tk
from math import cos,hypot,radians,sin
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (NativeWindowHandle,Point2,Point3,Vec3,WindowProperties,
                         OrthographicLens,PerspectiveLens,loadPrcFileData)
from color_palette import Palette,panda_rgba
from land_ports import land_port_focus_point
from native_viewer import NativeScene
from .scene_buffers import compile_city,GeometryBuffer
from .scene_presenter import ScenePresenter
from .camera3d import OrbitCamera,map_to_panda,panda_to_map,ray_to_height
from .viewport import Viewport,MIN_ZOOM,MAX_ZOOM,ZOOM_STEP


class _OffscreenFrame:
    def __init__(self,width,height):self.width,self.height=width,height
    def winfo_width(self):return self.width
    def winfo_height(self):return self.height
    def winfo_rootx(self):return 0
    def winfo_rooty(self):return 0
    def configure(self,**kwargs):pass
    def bind(self,*args,**kwargs):pass


class PandaWorldView:
    def __init__(self,parent=None,*,mode='perspective',offscreen=False,width=960,height=640):
        self.frame=_OffscreenFrame(width,height) if offscreen else tk.Frame(parent,bg=Palette.ROAD_SURFACE)
        loadPrcFileData('','audio-library-name null')
        if offscreen:
            loadPrcFileData('',f'load-display p3headlessgl\nwin-size {width} {height}\nsync-video false')
        self.base=ShowBase(windowType='offscreen' if offscreen else 'none')
        self.base.disableMouse();self.base.setBackgroundColor(*panda_rgba(Palette.TERRAIN_GRASS))
        self.orbit=OrbitCamera((2500,1750,0));self.map_view=Viewport(0,0,1)
        self.mode=mode;self.city=None;self.overlay_canvas=None
        self.native_scene=NativeScene(self.base.render,self.base.cam)
        self.presenter=ScenePresenter(self.native_scene)
        self.overlay_scene=NativeScene(self.base.pixel2d)
        self.preview_scene=NativeScene(self.base.render)
        self._orthographic=OrthographicLens();self._orthographic.setNearFar(1,40000)
        self._perspective=PerspectiveLens();self._perspective.setNearFar(1,20000)
        self.on_click=self.on_right_click=self.on_motion=self.on_key=None
        self.on_camera_change=self.on_before_render=None;self._camera_stamp=None
        self._last_pointer=None;self._drag_mode=None
        self.base.accept('mouse1',self._click)
        self.base.accept('mouse3',self._right_click)
        self.base.accept('mouse2',lambda:self._start_drag('pan'))
        self.base.accept('alt-mouse2',lambda:self._start_drag('orbit' if self.mode=='perspective' else 'pan'))
        for event in ('mouse2-up','alt-mouse2-up'):self.base.accept(event,self._end_drag)
        self.base.accept('wheel_up',lambda:self._wheel(1/ZOOM_STEP))
        self.base.accept('wheel_down',lambda:self._wheel(ZOOM_STEP))
        for key in ('page_up','page_down','enter','escape'):self.base.accept(key,self._emit_key,[key])
        self.frame.bind('<Configure>',self._resize)
        self._presentation_task_name=f'native-viewer-{id(self)}'
        self.base.taskMgr.add(self._before_render_task,self._presentation_task_name,sort=49)
        if self.base.win is not None:self._apply_camera()

    def set_callbacks(self,*,on_click=None,on_right_click=None,on_motion=None,on_key=None,
                      on_camera_change=None,on_before_render=None):
        self.on_click,self.on_right_click,self.on_motion,self.on_key=on_click,on_right_click,on_motion,on_key
        self.on_camera_change,self.on_before_render=on_camera_change,on_before_render

    def _open(self):
        # Tk and Panda use separate X connections. Realize/flush the parent
        # before Panda creates its child (startup now opens the native view).
        self.frame.update_idletasks()
        properties=WindowProperties()
        properties.setParentWindow(NativeWindowHandle.makeInt(self.frame.winfo_id()))
        properties.setOrigin(0,0)
        properties.setSize(max(2,self.frame.winfo_width()),max(2,self.frame.winfo_height()))
        self.base.openWindow(props=properties,requireWindow=True)
        self.base.setupMouse(self.base.win)
        self.native_scene.set_camera(self.base.cam);self._apply_camera()

    def _resize(self,_event=None):
        if self.base.win is None:return
        properties=WindowProperties();properties.setOrigin(0,0)
        properties.setSize(max(2,self.frame.winfo_width()),max(2,self.frame.winfo_height()))
        self.base.win.requestProperties(properties);self._apply_camera()

    def step(self):
        if self.base.win is None:self._open()
        self.base.taskMgr.step()

    def _before_render_task(self,task):
        self._process_pointer()
        if self.on_before_render is not None:self.on_before_render()
        if self.overlay_canvas is not None:self.overlay_canvas.flush()
        return task.cont

    def _pointer(self):
        watcher=self.base.mouseWatcherNode
        if watcher is None or not watcher.hasMouse():return None
        mouse=watcher.getMouse()
        return (round((mouse.x+1)*self.frame.winfo_width()/2),round((1-mouse.y)*self.frame.winfo_height()/2))

    def _click(self):
        point=self._pointer()
        if point is not None and self.on_click is not None:self.on_click(*point)

    def _right_click(self):
        point=self._pointer()
        if point is not None and self.on_right_click is not None:self.on_right_click(*point)

    def _emit_key(self,key):
        if self.on_key is not None:self.on_key(key)

    def _start_drag(self,mode):self._drag_mode=mode;self._last_pointer=self._pointer()
    def _end_drag(self):self._drag_mode=None

    def _wheel(self,factor):
        point=self._pointer()
        if self.mode=='map':
            point=point or (0,0);before=self.map_view.screen_to_world(point)
            self.map_view.zoom=max(MIN_ZOOM,min(MAX_ZOOM,self.map_view.zoom/factor))
            self.map_view.x=before[0]-point[0]/self.map_view.zoom
            self.map_view.y=before[1]-point[1]/self.map_view.zoom
            self._apply_camera();return
        before=self.point_at_screen(*point,0) if point else None
        self.orbit.zoom(factor);self._apply_camera()
        after=self.point_at_screen(*point,0) if point else None
        if before is not None and after is not None:
            x,y,z=self.orbit.target;self.orbit.target=(x+before[0]-after[0],y+before[1]-after[1],z)
            self._apply_camera()

    def _process_pointer(self):
        point=self._pointer()
        if point is None:self._last_pointer=None;return
        if self._last_pointer is not None and point!=self._last_pointer:
            dx,dy=point[0]-self._last_pointer[0],point[1]-self._last_pointer[1]
            if self._drag_mode=='orbit':self.orbit.rotate(-dx*.35,-dy*.35);self._apply_camera()
            elif self._drag_mode=='pan':
                if self.mode=='map':self.map_view.x-=dx/self.map_view.zoom;self.map_view.y-=dy/self.map_view.zoom
                else:
                    scale=self.orbit.distance/max(1,self.frame.winfo_height())
                    orientation=self.base.camera.getQuat(self.base.render)
                    right,up=orientation.xform(Vec3(1,0,0)),orientation.xform(Vec3(0,0,1))
                    rl,ul=hypot(right.x,right.y) or 1,hypot(up.x,up.y) or 1
                    x,y,z=self.orbit.target
                    self.orbit.target=(x+(-right.x/rl*dx+up.x/ul*dy)*scale,y-(-right.y/rl*dx+up.y/ul*dy)*scale,z)
                self._apply_camera()
            if self.on_motion is not None:self.on_motion(*point)
        self._last_pointer=point

    def show_city(self,city):
        if self.city is not city:self.orbit.target=(*land_port_focus_point(city),0)
        triangles,lines=compile_city(city)
        self.native_scene.replace_static(triangles,lines)
        self.city=city;self.presenter.invalidate()
        self.base.setBackgroundColor(*panda_rgba(city.terrain.grass_color));self._apply_camera()

    def update_road_vehicles(self,simulation):
        if self.city is not None:self.presenter.update(self.city,simulation)

    def set_mode(self,mode):
        if mode not in ('map','perspective'):raise ValueError('Unknown Panda camera mode')
        self.mode=mode;self._apply_camera()

    def _apply_camera(self):
        if self.base.camera is None or self.base.camera.isEmpty():return
        width,height=max(2,self.frame.winfo_width()),max(2,self.frame.winfo_height())
        if self.mode=='map':
            lens=self._orthographic;lens.setFilmSize(width/self.map_view.zoom,height/self.map_view.zoom)
            x,y=self.map_view.x+width/(2*self.map_view.zoom),self.map_view.y+height/(2*self.map_view.zoom)
            self.base.camera.setPos(x,-y,10000);self.base.camera.setHpr(0,-90,0)
            self.native_scene.set_bounds((self.map_view.x,self.map_view.y,self.map_view.x+width/self.map_view.zoom,self.map_view.y+height/self.map_view.zoom))
        else:
            lens=self._perspective;lens.setAspectRatio(width/height)
            self.base.camera.setPos(*map_to_panda(self.orbit.position))
            yaw=radians(self.orbit.yaw);up=Vec3(-cos(yaw),sin(yaw),0) if self.orbit.pitch>=90 else Vec3(0,0,1)
            self.base.camera.lookAt(Point3(*map_to_panda(self.orbit.target)),up)
            self.native_scene.set_bounds(None)
        self.base.cam.node().setLens(lens);self.base.camLens=lens
        stamp=(self.mode,width,height,self.map_view.x,self.map_view.y,self.map_view.zoom,
               self.orbit.target,self.orbit.yaw,self.orbit.pitch,self.orbit.distance)
        if stamp!=getattr(self,'_camera_stamp',None):
            self._camera_stamp=stamp
            callback=getattr(self,'on_camera_change',None)
            if callback is not None:callback()

    def point_at_screen(self,screen_x,screen_y,elevation):
        if self.base.win is None:return None
        x=screen_x/max(1,self.frame.winfo_width())*2-1;y=1-screen_y/max(1,self.frame.winfo_height())*2
        near,far=Point3(),Point3()
        if not self.base.camLens.extrude(Point2(x,y),near,far):return None
        transform=self.base.camera.getMat(self.base.render);start,end=transform.xformPoint(near),transform.xformPoint(far)
        point=ray_to_height((start.x,start.y,start.z),(end.x-start.x,end.y-start.y,end.z-start.z),elevation)
        return None if point is None else panda_to_map((*point,elevation))[:2]

    def screen_position(self,point,elevation=0):
        if self.base.win is None:return None
        camera_point=self.base.camera.getRelativePoint(self.base.render,Point3(*map_to_panda((*point,elevation))))
        projected=Point2()
        if not self.base.camLens.project(camera_point,projected):return None
        return ((projected.x+1)*self.frame.winfo_width()/2,(1-projected.y)*self.frame.winfo_height()/2)

    def nearest_road_endpoint(self,screen_x,screen_y,tolerance=14):
        if self.city is None:return None
        closest=None
        for road in self.city.roads:
            for point,elevation in [(road.centerline[0],road.elevations[0]),(road.centerline[-1],road.elevations[-1])]:
                screen=self.screen_position(point,elevation)
                if screen is not None:
                    distance=hypot(screen[0]-screen_x,screen[1]-screen_y)
                    if distance<=tolerance:closest=(point,elevation);tolerance=distance
        return closest

    def show_road_preview(self,points,elevations,pointer,pointer_elevation):
        buf=GeometryBuffer();path=[(*p,z+1) for p,z in zip(points,elevations)]
        if pointer is not None:path.append((*pointer,pointer_elevation+1))
        buf.line(path,Palette.ROUTE_HIGHLIGHT);self.preview_scene.replace_static(*buf.arrays())

    def clear_preview(self):
        buf=GeometryBuffer();self.preview_scene.replace_static(*buf.arrays())

    def close(self):
        if getattr(self,'_closed',False):return
        self._closed=True
        self.base.taskMgr.remove(self._presentation_task_name)
        self.native_scene.close();self.overlay_scene.close();self.preview_scene.close()
        if self.base.win is not None:self.base.closeWindow(self.base.win)
        self.base.graphicsEngine.renderFrame();self.base.graphicsEngine.syncFrame()
        self.base.destroy()
