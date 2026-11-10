"""Display-backed scenarios for test_editor_resizing; no mocked renderer/widgets."""
import json
import faulthandler
import sys
import tempfile
import tkinter as tk
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from ui.app import FreewaySimulator
from ui_tools.tools.road_tool import BuildingTool, RoadTool
from ui_tools.tools.route_test_tool import RouteTestTool
from ui_tools.tools.test_traffic_tool import TestTrafficTool
from ui_tools.tools.transit_tool import BusRouteTool
from ui_tools.tools.deconstruct_road_tool import DeconstructRoadTool
from models import BuildablePhase


SIZES = ((1280, 720), (1, 1), (320, 240), (640, 480), (1600, 900),
         (640, 1000), (1600, 300), (1280, 720))


class EditorScenario(TestCase):
    def runTest(self):
        faulthandler.dump_traceback_later(15, repeat=True)
        self.errors = []
        self.root = tk.Tk()
        self.root.geometry('1280x720')
        self.app = FreewaySimulator(self.root)
        self.app.running = False
        self.root.report_callback_exception = lambda *args: self.errors.append(''.join(traceback.format_exception(*args)))
        try:
            self.pump()
            getattr(self, sys.argv[1])()
            self.assertEqual(self.errors, [])
        finally:
            faulthandler.cancel_dump_traceback_later()
            self.app.view3d.close()
            self.root.destroy()

    def pump(self):
        # Settle Tk layout and Panda's asynchronous property acknowledgments.
        for _ in range(3):
            self.root.update()
            self.app.view3d.step()
        self.assertEqual(self.errors, [])

    def resize(self, width, height):
        self.root.geometry(f'{width}x{height}')
        self.pump()
        view = self.app.view3d
        if view.frame.winfo_ismapped():
            self.assertFalse(view.base.win.isClosed())
            self.assertEqual(tuple(view.base.win.getProperties().getSize()),
                             (max(2, view.frame.winfo_width()), max(2, view.frame.winfo_height())))
            self.assertEqual(tuple(view.base.win.getProperties().getOrigin()), (0, 0))

    def tool(self, kind):
        return next(t for menu in self.app.tools for t in menu.iter_canvas_tools() if isinstance(t, kind))

    def modes(self):
        for mode in ('map', 'perspective'):
            if (mode == 'perspective') != self.app.view3d_active:
                self.app.toggle_3d_view()
            yield mode

    def tools(self):
        tools = [t for menu in self.app.tools for t in menu.iter_canvas_tools()]
        # A newly registered tool automatically joins this matrix.
        self.assertGreaterEqual(len(tools), 7)
        for mode in self.modes():
            for tool in tools:
                self.app.select_tool(tool)
                for size in SIZES:
                    print(mode, type(tool).__name__, size, flush=True)
                    self.resize(*size)
                    tool.on_canvas_motion(SimpleNamespace(x=30, y=40))
                    tool.refresh()
                    self.app.canvas.flush()
                self.app.deactivate_tool(tool)
                tool.reset()
                self.assertFalse(self.app.canvas.find_withtag('road_preview'))

    def construction(self):
        road = self.tool(RoadTool)
        building = self.tool(BuildingTool)
        for mode in self.modes():
            with patch('ui.files.messagebox.askyesno', return_value=True):
                self.app.new_world()
            self.app.select_tool(road)
            for size in SIZES:
                print(mode, 'construction', size, flush=True)
                self.resize(*size)
                view = self.app.view3d
                if not view.frame.winfo_ismapped():
                    continue
                # Picking and preview projection must agree with the camera
                # after both a resize and projection switch.
                x, y = view.frame.winfo_width()/2, view.frame.winfo_height()/2
                point = view.point_at_screen(x, y, 0)
                self.assertIsNotNone(point)
                screen = view.screen_position(point)
                self.assertAlmostEqual(screen[0], x, delta=.2)
                self.assertAlmostEqual(screen[1], y, delta=.2)
                self.app._handle_3d_click(x, y)
                self.app._handle_3d_motion(x+60, y+25)
                self.app._handle_3d_click(x+60, y+25)
                road.refresh()
                self.assertEqual(len(road.points), 2)
                before = len(self.app.city_map.roads)
                view.base.messenger.send('enter')
                self.assertEqual(road.points, [], road.panel.message_label.cget('text'))
                self.assertGreater(len(self.app.city_map.roads), before)
                self.app._handle_3d_click(x, y)
                view.base.messenger.send('page_up')
                self.assertEqual(road.draft_elevation, 10)
                view.base.messenger.send('escape')
                self.assertEqual(road.points, [])
            self.app.select_tool(building)
            for size in SIZES:
                self.resize(*size)
                view = self.app.view3d
                x, y = view.frame.winfo_width()/2, view.frame.winfo_height()/2
                point = self.app.screen_to_world((x, y))
                self.app._handle_3d_motion(x, y)
                before = len(self.app.city_map.buildings)
                self.app._handle_3d_click(x, y)
                if len(self.app.city_map.buildings) > before:
                    parcel = self.app.city_map.buildings[-1].parcel
                    self.assertAlmostEqual(parcel.x+parcel.width/2, point[0], delta=.1)
                    self.assertAlmostEqual(parcel.y+parcel.height/2, point[1], delta=.1)
                self.pump()
            self.app.deactivate_tool(building)

    def files(self):
        app = self.app
        app.show_analytics()
        app.show_performance_graph()
        app.show_simulation_performance_graph()
        windows = [app.analytics_window, app.performance_window,
                   app.simulation_performance_window, app.debug_window, app.recent_window]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'world.json')
            for mode in self.modes():
                for size in SIZES:
                    self.resize(*size)
                    for window in windows:
                        window.geometry(f'{max(1,size[0]//2)}x{max(1,size[1]//2)}')
                    app.draw_analytics()
                    app.draw_performance_graph()
                    app.draw_simulation_performance_graph()
                    app.draw_merge_debug()
                    app.draw_recent_changes()
                    app.set_unit_system('metric')
                    app.set_unit_system('imperial')
                    with patch('ui.files.filedialog.asksaveasfilename', return_value=path):
                        app.save_state()
                    saved = json.loads(Path(path).read_text())
                    self.assertIsInstance(saved, dict)
                    with patch('ui.files.filedialog.askopenfilename', return_value=path):
                        app.load_state()
                    app.simulation.history[:]=[(0,30,1),(1,35,2)]
                    for suffix, action in (('csv',app.export_csv),('svg',app.export_svg),
                                           ('profile.json',app.export_simulation_profile_json),
                                           ('profile.csv',app.export_simulation_profile_csv)):
                        output=str(Path(directory)/suffix)
                        with patch('ui.files.filedialog.asksaveasfilename',return_value=output):
                            action()
                        self.assertGreater(Path(output).stat().st_size,0)
                    with patch('ui.files.messagebox.askyesno', return_value=True):
                        app.new_world()
                    self.assertEqual(len(app.city_map.buildings), 0)
                    app.reset_camera()
                    self.pump()

    def rapid(self):
        building = self.tool(BuildingTool)
        for mode in self.modes():
            with patch('ui.files.messagebox.askyesno', return_value=True):
                self.app.new_world()
            self.app.select_tool(building)
            view = self.app.view3d
            for i, size in enumerate(SIZES*10):
                print(mode,'rapid',i,size,flush=True)
                self.root.geometry(f'{size[0]}x{size[1]}')
                self.root.update_idletasks()
                # Layout changes and editor events occur before Panda consumes
                # the queued native-window resize, matching the reported case.
                x,y=view.frame.winfo_width()/2+(i%5)*2,view.frame.winfo_height()/2
                self.app._handle_3d_motion(x,y)
                if i % 8 == 0:
                    self.app._handle_3d_click(x,y)
                view.step()
                self.root.update()
            self.resize(1280,720)
            self.assertGreater(len(self.app.city_map.buildings),0)
            self.app.deactivate_tool(building)

    def actions(self):
        from tests.test_city_gameplay import placed
        app = self.app
        for mode in self.modes():
            for size in SIZES:
                with patch('ui.files.messagebox.askyesno', return_value=True):
                    app.new_world()
                for road in app.city_map.roads:
                    road.phase=BuildablePhase.OPERATIONAL
                authored=app.city_map.add_road([(500,1750),(950,1750)])
                stops = [placed(app.city_map, 'bus_stop', x, 1776) for x in (600,800)]
                for building in stops:
                    self.assertIsNotNone(building)
                    building.phase = BuildablePhase.OPERATIONAL
                app.redraw_world()
                self.resize(*size)
                self.assertEqual(len(app.city_simulation.transit.stops),2)
                app.select_tool(app.inspector_tool)
                for selected in (app.city_map.roads[0], app.city_map.cul_de_sacs[-1], stops[0], None):
                    app.inspector_tool.show_object(selected)
                    self.pump()
                    self.assertTrue(app.inspector_tool._row_widgets)
                app.deactivate_tool(app.inspector_tool)
                route = self.tool(RouteTestTool)
                app.select_tool(route)
                for junction in app.city_map.cul_de_sacs:
                    x,y=app.world_to_screen(junction.position)
                    app._handle_3d_click(x,y)
                route.refresh()
                self.assertIsNotNone(route.route)
                app.view3d.base.messenger.send('escape')
                self.assertIsNone(route.route)
                traffic = self.tool(TestTrafficTool)
                app.select_tool(traffic)
                junction=app.city_map.cul_de_sacs[-1]
                x,y=app.world_to_screen(junction.position)
                app._handle_3d_click(x,y)
                self.assertIn(junction.id, app.test_traffic.active_junction_ids)
                app._handle_3d_click(x,y)
                self.assertNotIn(junction.id, app.test_traffic.active_junction_ids)
                bus = self.tool(BusRouteTool)
                app.select_tool(bus)
                for building in stops:
                    p=building.parcel
                    x,y=app.world_to_screen((p.x+p.width/2,p.y+p.height/2))
                    app._handle_3d_click(x,y)
                self.assertEqual(bus.stops,[b.id for b in stops])
                app.view3d.base.messenger.send('enter')
                self.assertEqual(len(app.city_simulation.transit.lines),1)
                self.assertEqual(bus.stops,[])
                demolition = self.tool(DeconstructRoadTool)
                app.select_tool(demolition)
                x,y=app.world_to_screen((750,1750))
                app._handle_3d_click(x,y)
                self.assertIs(authored.phase,BuildablePhase.DEMOLISHING,demolition.message)
                self.pump()
                app.deactivate_tool(demolition)

    def lifecycle(self):
        view = self.app.view3d
        frames = []
        view.on_before_render = lambda: frames.append(1)
        self.pump()
        # Unmapped Tk parents must not be rendered into or re-opened.
        view.frame.pack_forget()
        self.root.update()
        count = len(frames)
        view.step()
        self.assertEqual(len(frames), count, 'rendered into an unmapped parent')
        view.frame.pack(side='left', fill='both', expand=True)
        self.pump()
        self.assertGreater(len(frames), count)
        self.root.withdraw()
        self.root.update()
        count = len(frames)
        view.step()
        self.assertEqual(len(frames), count)
        self.root.deiconify()
        self.pump()
        for size in SIZES*4:
            self.root.geometry(f'{size[0]}x{size[1]}')
            self.root.update_idletasks()
        self.pump()
        self.root.geometry('640x480')
        view.close()
        count = len(frames)
        self.root.update()
        view._resize()
        view.step()
        self.assertEqual(len(frames), count, 'closed view resumed rendering')


if __name__ == '__main__':
    if sys.argv[1]=='offscreen':
        from ui.view3d import PandaWorldView
        view=PandaWorldView(offscreen=True,width=640,height=480)
        try:
            frames=[]
            view.on_before_render=lambda:frames.append(1)
            view.step()
            assert frames
            assert view.base.win.isValid()
            assert (view.base.win.getXSize(),view.base.win.getYSize())==(640,480)
        finally:view.close()
    else:
        EditorScenario().debug()
