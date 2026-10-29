import unittest
from types import SimpleNamespace
from tests.test_city_gameplay import neighborhood, placed
from models import BuildablePhase


class GameplayUITests(unittest.TestCase):
    def test_existing_app_update_drives_exactly_one_traffic_clock(self):
        from ui.app import FreewaySimulator
        runtime,*_=neighborhood()
        host=SimpleNamespace(city_simulation=runtime,city_map=runtime.city,running=True,simulation_speed=1,
            draw_road_vehicles=lambda:None,draw_city_activity=lambda:None,redraw_world=lambda:None)
        FreewaySimulator._update_construction(host,5)
        self.assertEqual(runtime.time,5)
        self.assertEqual(runtime.transit.traffic.elapsed_time,5)

    def test_household_and_truck_commands_use_inspected_placed_building(self):
        from ui.gameplay import CityGameplayMixin
        runtime,home,_,cafe,*_=neighborhood()
        class Host(CityGameplayMixin):pass
        host=Host();host.city_simulation=runtime;host.root=None
        host.inspector_tool=SimpleNamespace(selected=home)
        h=host.invite_household_selected(3)
        self.assertEqual(h.home,home.id)
        host.inspector_tool.selected=cafe
        truck=host.commission_truck_selected()
        self.assertEqual(truck.site,cafe.id)
        self.assertIs(runtime.sites[home.id]['building'],home)

    def test_route_tool_connects_authored_stops_with_sixty_seat_buses(self):
        from ui_tools.tools.transit_tool import BusRouteTool
        runtime,*_=neighborhood()
        stops=[]
        for x in (500,3300):
            b=placed(runtime.city,'bus_stop',x,50);b.phase=BuildablePhase.OPERATIONAL;stops.append(b)
        runtime.sync_buildings()
        host=SimpleNamespace(city_simulation=runtime,redraw_world=lambda:None)
        tool=BusRouteTool(host)
        for stop in stops:tool.select_stop(stop)
        line=tool.finish()
        self.assertEqual(runtime.transit.lines[line].stop_ids,tuple(b.id for b in stops))
        self.assertEqual(len(runtime.transit.buses),2)
        self.assertTrue(all(b.capacity==60 for b in runtime.transit.buses.values()))
