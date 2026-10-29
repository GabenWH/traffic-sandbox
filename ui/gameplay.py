"""Player commands and presentation for the shared authored-city runtime."""
from tkinter import messagebox, simpledialog
from city import Building
from households import DAY


class CityGameplayMixin:
    def prepare_city_runtime(self,city):
        from city_simulation import CitySimulation
        from construction import ConstructionSimulation
        from traffic_testbed import RoadVehicleSimulation
        from traffic_debugger import TrafficDebugger
        old=self.construction_simulation
        traffic=RoadVehicleSimulation(update_mode='cpp',debugger=TrafficDebugger())
        construction=ConstructionSimulation(old.resources,old.trucks,old.provider,road_vehicles=traffic)
        try:runtime=CitySimulation(city,traffic,construction)
        except Exception:
            traffic._before_native_discard=None
            traffic._discard_native()
            raise
        return traffic,construction,runtime

    def install_city_runtime(self,prepared):
        self.road_vehicles,self.construction_simulation,self.city_simulation=prepared
        self.test_traffic=self.road_vehicles

    def _gameplay_building(self):
        selected=getattr(getattr(self,'inspector_tool',None),'selected',None)
        if not isinstance(selected,Building):
            raise ValueError('Select a building with Inspect first.')
        self.city_simulation.sync_buildings()
        return selected

    def invite_household_selected(self,size=None):
        try:
            building=self._gameplay_building()
            if size is None:
                size=simpledialog.askinteger('Move in household','Number of newcomers (1–4):',
                    initialvalue=min(4,self.city_simulation.vacancy(building.id)),minvalue=1,maxvalue=4,parent=self.root)
            if size is None:return
            return self.city_simulation.invite_household(building.id,size,car=True)
        except ValueError as error:messagebox.showerror('Move in household',str(error),parent=self.root)

    def commission_truck_selected(self):
        try:return self.city_simulation.commission_truck(self._gameplay_building().id)
        except ValueError as error:messagebox.showerror('Commission delivery truck',str(error),parent=self.root)

    def assign_selected_workplace(self):
        try:
            building=self._gameplay_building()
            pid=simpledialog.askinteger('Assign worker','Resident ID (shown in the home inspector):',minvalue=0,parent=self.root)
            if pid is not None:self.city_simulation.assign_workplace(pid,building.id)
        except (ValueError,KeyError) as error:messagebox.showerror('Assign worker',str(error),parent=self.root)

    def supply_selected_building(self):
        try:
            building=self._gameplay_building()
            value=simpledialog.askstring('Import supplies','Resource and amount, for example: seed 400',parent=self.root)
            if not value:return
            resource,amount=value.split()
            self.city_simulation.import_resources(building.id,resource,float(amount))
        except (ValueError,KeyError) as error:messagebox.showerror('Import supplies',str(error),parent=self.root)

    def refuel_selected_building(self):
        try:
            building=self._gameplay_building()
            amount=simpledialog.askfloat('Refuel','Litres to import per parked vehicle:',initialvalue=50,minvalue=.1,parent=self.root)
            if amount is not None:self.city_simulation.refuel_at(building.id,amount)
        except ValueError as error:messagebox.showerror('Refuel',str(error),parent=self.root)

    def draw_city_activity(self):
        runtime=self.city_simulation
        self.canvas.delete('town-activity')
        states=runtime.transit.engine.pedestrian_states()
        radius=max(1.5,2*self.camera_zoom)
        for p in states:
            x,y=self.world_to_screen((p.x,p.y))
            self.canvas.create_oval(x-radius,y-radius,x+radius,y+radius,
                fill='#e5a833' if p.waiting else '#8c31bc',outline='',tags='town-activity')
        for stop in runtime.transit.stops.values():
            x,y=self.world_to_screen(stop.walk_point)
            waiting=sum(len(q) for (line,sid),q in runtime.transit.queues.items() if sid==stop.id)
            self.canvas.create_text(x,y-12,text=f'BUS · {waiting} waiting',fill='#634b09',tags='town-activity')
        self.canvas.create_text(12,42,anchor='nw',text=(f'Day {int(runtime.time//DAY)+1}  '
            f'{int(runtime.time%DAY//3600):02d}:{int(runtime.time%3600//60):02d}   '
            f'{len(runtime.residents)} people · {len(runtime.households)} households'),
            fill='#243545',tags='town-activity')
        if self.view3d_active and self.view3d is not None:
            self.view3d.update_pedestrians(states)

    def draw_passenger_bus(self,bus_actor):
        x,y=bus_actor.position;hx,hy=bus_actor.heading
        length,width=bus_actor.length,bus_actor.width
        points=[]
        for along,across in ((.5,.5),(.5,-.5),(-.5,-.5),(-.5,.5)):
            points.extend(self.world_to_screen((x+hx*length*along-hy*width*across,
                                               y+hy*length*along+hx*width*across)))
        self.canvas.create_polygon(*points,fill='#e3a82f',outline='#695210',tags='construction-truck')
        sx,sy=self.world_to_screen((x,y))
        bus=self.city_simulation.transit.buses.get(bus_actor.id)
        self.canvas.create_text(sx,sy-10,text=f'{len(bus.passengers) if bus else 0}/60',tags='construction-truck')
