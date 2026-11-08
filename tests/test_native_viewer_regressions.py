"""Migration compatibility cases found by independent review."""
import unittest
from types import SimpleNamespace
import numpy as np
from city import CityMap,Terrain
from models import BuildablePhase,IntersectionKind
from color_palette import Palette,panda_rgba


class NativeViewerRegressionTests(unittest.TestCase):
    def test_elevated_roundabout_arc_and_entry_exit_keep_junction_height(self):
        from ui.scene_buffers import route_heights
        from pathfinding import Path
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,250),(500,250)],elevations=[30,30])
        city.add_road([(250,0),(250,500)],elevations=[30,30])
        junction=city.standard_intersections[0];junction.kind=IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network();links=[];kinds=set()
        for node in city.mobility.layers['vehicles'].graph.nodes:
            for t in city.mobility.layers['vehicles'].graph.transitions_from(node):
                if getattr(t.edge.value,'road_id',None)==f'roundabout:{junction.id}':
                    links.append(t.edge);kinds.add('arc')
                elif getattr(t.edge.value,'roundabout_role','') in ('entry','exit'):
                    links.append(t.edge);kinds.add(t.edge.value.roundabout_role)
        self.assertEqual(kinds,{'arc','entry','exit'})
        for link in links:
            ruler=route_heights(city,SimpleNamespace(route=Path((),(link,),1)))
            self.assertTrue(np.all(ruler[:,1]==30),repr(ruler))

    def test_cul_de_sac_pavement_covers_the_turnaround_behind_road_end(self):
        from ui.scene_buffers import compile_city
        from building_footprints import contains_point
        city=CityMap(terrain=Terrain(trees=[]));city.add_road([(100,100),(500,100)])
        triangles,_=compile_city(city);color=np.array(panda_rgba(Palette.ROAD_SURFACE))
        faces=triangles[np.all(np.isclose(triangles[:,3:],color),axis=1),:3].reshape(-1,3,3)
        self.assertTrue(any(contains_point([tuple(p[:2]) for p in face],(92,100)) for face in faces))

    def test_stop_bars_and_demolition_stripes_are_compiled_at_road_height(self):
        from ui.scene_buffers import compile_city
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,250),(500,250)],elevations=[30,30])
        city.add_road([(250,0),(250,500)],elevations=[30,30])
        city.standard_intersections[0].set_all_way_stop(True)
        city.roads[0].phase=BuildablePhase.DEMOLISHING
        triangles,lines=compile_city(city);vertices=np.concatenate((triangles,lines))
        for color in (Palette.ROAD_MARKING,'#ffb000'):
            marked=vertices[np.all(np.isclose(vertices[:,3:],panda_rgba(color)),axis=1)]
            self.assertGreater(len(marked),0)
            self.assertTrue(np.all(marked[:,2]>=30))

    def test_parked_cargo_and_dimensions_update_native_instances(self):
        from tests.test_parking import fleet_with_shared_lot
        from persistent_fleet import FleetVehicle
        from native_viewer import NativeScene
        from ui.scene_presenter import ScenePresenter
        from panda3d.core import NodePath,GeomVertexReader
        fleet=fleet_with_shared_lot();truck=FleetVehicle('t','truck','a',length=28,width=8,capacity=100)
        fleet.add(truck);city=fleet.transit.city;city.gameplay=SimpleNamespace(fleet=fleet)
        root=NodePath('root');scene=NativeScene(root);presenter=ScenePresenter(scene)
        def parked_data():
            nodes=root.findAllMatches('**/parked/**/+GeomNode')
            return nodes[0].node().getGeom(0).getVertexData()
        try:
            presenter.update(city,fleet.transit.traffic)
            empty_rows=parked_data().getArray(0).getNumRows()
            truck.cargo['stone']=50;presenter.update(city,fleet.transit.traffic)
            self.assertGreater(parked_data().getArray(0).getNumRows(),empty_rows)
            truck.width=9;presenter.update(city,fleet.transit.traffic)
            self.assertAlmostEqual(GeomVertexReader(parked_data(),'instance_size').getData4()[2],9)
            truck.cargo.clear();presenter.update(city,fleet.transit.traffic)
            self.assertEqual(parked_data().getArray(0).getNumRows(),empty_rows)
        finally:scene.close();fleet.transit.traffic._discard_native()

    def test_native_hud_retains_bus_stop_waiting_counts(self):
        from ui.gameplay import CityGameplayMixin
        from ui.native_canvas import NativeCanvas
        class Host(CityGameplayMixin):pass
        host=Host();host.canvas=NativeCanvas(None,None);host.world_to_screen=lambda p:p
        host.city_simulation=SimpleNamespace(time=0,residents={},households={},
            transit=SimpleNamespace(stops={'s':SimpleNamespace(walk_point=(100,100))},queues={('line','s'):[1,2]}))
        host.draw_native_hud()
        labels=[options.get('text') for _,_,options in host.canvas._items.values()]
        self.assertIn('BUS · 2 waiting',labels)

    def test_editor_line_width_and_dash_have_visible_geometry(self):
        from ui.native_canvas import NativeCanvas
        from native_viewer import NativeScene
        from panda3d.core import NodePath
        root=NodePath('overlay');scene=NativeScene(root)
        try:
            canvas=NativeCanvas(None,SimpleNamespace(overlay_scene=scene))
            canvas.create_line(0,0,100,0,fill='#ffffff',width=40,dash=(10,10));canvas.flush()
            self.assertGreater(scene.stats()['static_triangles'],0)
            nodes=root.findAllMatches('**/+GeomNode')
            self.assertGreaterEqual(float(nodes[0].node().getBounds().getMax()[2]),20)
        finally:scene.close()

    def test_truck_and_bus_indicators_have_geometry_and_native_blink_state(self):
        from native_viewer import NativeScene
        from native_traffic import NativeVehicleView
        from vehicle import VehicleAppearance
        from panda3d.core import NodePath,GeomVertexReader
        for appearance in (VehicleAppearance(kind='material_truck',shape='material_truck'),
                           VehicleAppearance(kind='crew_truck',shape='crew_truck'),VehicleAppearance(kind='bus')):
            with self.subTest(kind=appearance.kind):
                root=NodePath('lamps');scene=NativeScene(root)
                try:
                    scene.register_vehicle(1,appearance,30,8,'#ff0000',np.array([(0.,0.)]))
                    rows=(NativeVehicleView*1)();rows[0].handle=1;rows[0].alive=1
                    rows[0].hy=1;rows[0].signal=1
                    scene.update_states(rows,1,.25)
                    data=root.find('**/actors/**/+GeomNode').node().getGeom(0).getVertexData()
                    colors=GeomVertexReader(data,'color');roles=set()
                    while not colors.isAtEnd():roles.add(round(colors.getData4()[3]))
                    self.assertTrue({4,5}.issubset(roles))
                    lamps=GeomVertexReader(data,'instance_lamps').getData4()
                    self.assertEqual((lamps[1],lamps[2]),(1,0))
                    scene.update_states(rows,1,.75)
                    self.assertEqual(GeomVertexReader(data,'instance_lamps').getData4()[1],0)
                finally:scene.close()

    def test_live_debug_window_only_reads_the_eight_displayed_cars(self):
        from ui.dashboards import DashboardMixin
        from unittest.mock import Mock
        class Host(DashboardMixin):pass
        host=Host();host.debug_canvas=Mock();host.debug_canvas.winfo_exists.return_value=True
        brain=SimpleNamespace(wait_reason='',state=SimpleNamespace(value='cruising'),
                              desired_speed=10,signal_intent=SimpleNamespace(value='off'))
        cars=[SimpleNamespace(id=str(i),brain=brain,speed=10) for i in range(8)]
        # A ninth row must never be read: the debug panel only displays eight.
        host.road_vehicles=SimpleNamespace(vehicles=cars+[object()])
        host.simulation=SimpleNamespace(merge_debug_lines=lambda:[])
        host.test_traffic=SimpleNamespace(debugger=SimpleNamespace(latest_summary=lambda:None))
        host.recent_errors=[];host.draw_merge_debug()
        text=host.debug_canvas.create_text.call_args.kwargs['text']
        self.assertIn('7: cruising',text)


if __name__=='__main__':unittest.main()
