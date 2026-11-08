"""Change-driven metadata boundary; ordinary frames consume C++ buffers directly."""
from collections import OrderedDict
from native_viewer import Parked,visual
from .scene_buffers import route_heights


class ScenePresenter:
    def __init__(self,scene):
        self.scene=scene;self.metadata_key=None;self.parked_key=None
        self.road_key=None;self.roads={};self.height_cache=OrderedDict()

    def invalidate(self):
        self.metadata_key=self.parked_key=self.road_key=None;self.height_cache.clear()

    def update(self,city,simulation):
        controller=simulation._native_backend(city)
        engine=controller.engine
        road_key=(id(city),city.mobility_revision)
        if self.road_key!=road_key:
            self.roads={road.id:road for road in city.roads};self.height_cache.clear();self.road_key=road_key
        key=(id(engine),road_key,simulation._roster_revision.stamp(),
             getattr(simulation,'_scene_metadata_revision',0))
        if self.metadata_key!=key:
            self.scene.clear_metadata()
            for car in simulation.vehicles:
                entry=self.height_cache.get(id(car.route))
                if entry is None or entry[0] is not car.route:
                    entry=(car.route,route_heights(city,car,self.roads))
                    self.height_cache[id(car.route)]=entry
                    while len(self.height_cache)>4096:self.height_cache.popitem(last=False)
                self.scene.register_vehicle(engine._handles[car.id],car.appearance,car.length,car.width,car.color,entry[1])
            self.metadata_key=key
        runtime=getattr(city,'gameplay',None)
        if runtime is not None:
            fleet=runtime.fleet;fleet._ensure_indexes()
            key=(id(fleet),fleet._presentation_revision,road_key)
            if key!=self.parked_key:
                parked=[]
                for i,p in enumerate(fleet.parked_vehicles()):
                    z=p.elevation
                    record=fleet.vehicles[p.id]
                    if record.road_stop_lane_id:
                        lane=fleet._lanes_by_id.get(record.road_stop_lane_id)
                        road=self.roads.get(lane.road_id) if lane else None
                        if road:z=road.elevation_at(p.position)
                    parked.append(Parked(visual(i,p.appearance,p.length,p.width,p.color),
                                          *p.position,z,*p.heading))
                self.scene.replace_parked(parked);self.parked_key=key
        elif self.parked_key is not None:
            self.scene.replace_parked([]);self.parked_key=None
        self.scene.update_native(engine,simulation.elapsed_time)
