"""Author bus lines by selecting completed bus-stop buildings in order."""
from tkinter import messagebox
from ..base import CanvasTool

TOOL_ID = 'bus_route'


class BusRouteTool(CanvasTool):
    name = 'Build bus line'
    cursor = 'crosshair'

    def __init__(self,host):
        super().__init__(host)
        self.stops=[]
        self._bindings=[]

    def activate(self):
        self.host.canvas.configure(cursor=self.cursor)
        self._bindings=[('<Return>',self.host.root.bind('<Return>',lambda e:self._finish_ui(),add='+')),
                        ('<Escape>',self.host.root.bind('<Escape>',lambda e:self.cancel(),add='+'))]
        self.refresh()

    def select_stop(self,building):
        self.host.city_simulation.sync_buildings()
        if building is None or building.id not in self.host.city_simulation.transit.stops:
            raise ValueError('Select a completed bus-stop building with road access.')
        if building.id in self.stops:raise ValueError('Select each stop once; the line repeats automatically.')
        self.stops.append(building.id)

    def on_canvas_click(self,event):
        try:self.select_stop(self.host.building_at(self.host.screen_to_world((event.x,event.y))))
        except ValueError as error:messagebox.showerror('Build bus line',str(error),parent=self.host.root)
        self.refresh()

    def finish(self):
        line=self.host.city_simulation.create_line(self.stops)
        self.stops.clear();self.host.redraw_world()
        return line

    def _finish_ui(self):
        try:self.finish()
        except ValueError as error:messagebox.showerror('Build bus line',str(error),parent=self.host.root)
        self.refresh()

    def refresh(self):
        self.host.canvas.delete('bus-route-preview')
        self.host.canvas.create_text(12,65,anchor='nw',text=f'Bus line: {len(self.stops)} stops selected · click completed stops · Enter opens service · Esc clears',tags='bus-route-preview')
        points=[]
        for sid in self.stops:
            stop=self.host.city_simulation.transit.stops.get(sid)
            if stop:points.extend(self.host.world_to_screen(stop.walk_point))
        if len(points)>=4:self.host.canvas.create_line(*points,fill='#c89219',width=3,tags='bus-route-preview')

    def cancel(self):self.stops.clear();self.refresh()

    def deactivate(self):
        for event,binding in self._bindings:self.host.root.unbind(event,binding)
        self._bindings=[];self.host.canvas.delete('bus-route-preview')

    def reset(self):self.stops.clear()


TOOL_CLASS = BusRouteTool
