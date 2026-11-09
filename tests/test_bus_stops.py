"""Bus service keeps a physical body from boarding through departure."""
import unittest
import importlib.util
from dataclasses import replace

from city import CityMap, Terrain
from gameplay_persistence import dump_transport, restore_transport
from mobility import lane_position_at_distance
from transit import Bus, BusLine, BusStop, TransitSimulation


class BusStopTests(unittest.TestCase):
    def system(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (2000, 0)])
        lane = next(l for l in road.lanes if l.direction == 'forward')
        sim = TransitSimulation(city)
        self.addCleanup(sim.traffic._discard_native)
        for name, distance in [('A', 100), ('B', 1000)]:
            sim.add_stop(BusStop(name, lane_position_at_distance(lane, distance), (distance, 15)))
        sim.add_line(BusLine('L', ('A', 'B'), dwell_seconds=30, headway_seconds=90))
        sim.add_bus(Bus('bus', 'L'))
        return sim, lane

    def until(self, sim, predicate, seconds=200):
        for _ in range(int(seconds/.05)):
            if predicate():
                return
            sim.update(.05)
        self.fail('Service did not reach the expected state')

    def follower(self, sim, lane, start):
        route = sim.city.find_vehicle_route_between(
            lane_position_at_distance(lane, start), lane_position_at_distance(lane, 1800))
        actor = sim.traffic.admit_route(route, vehicle_id='follower',
            source_id='start', destination_id='end')
        self.assertIsNotNone(actor)
        return actor

    def test_bus_brakes_blocks_traffic_during_boarding_and_departs_from_rest(self):
        sim, lane = self.system()
        bus = sim.buses['bus']
        self.until(sim, lambda: bus.phase == 'driving')
        self.assertLessEqual(bus._car.speed, .5)
        actor = bus._car
        follower = self.follower(sim, lane, 40)
        samples = []
        while bus.phase == 'driving':
            samples.append((actor.total_length-actor.distance, actor.speed))
            sim.update(.05)
        self.assertEqual(bus.stop_index, 1)
        self.assertEqual(actor.speed, 0)
        self.assertTrue(any(0 < d < 30 and 0 < v < 20 for d, v in samples))
        dock_time, position = sim.time, bus.position
        sim.update(20)
        self.assertEqual(bus.phase, 'docked')
        self.assertEqual(bus.position, position)
        self.assertEqual(follower.speed, 0)
        self.assertLessEqual(40+follower.distance+follower.length/2+4, 1000-bus.length/2+1e-6)
        self.until(sim, lambda: bus.phase == 'driving')
        self.assertGreaterEqual(sim.time-dock_time, 30)
        self.assertLessEqual(bus._car.speed, .5)
        sim.update(2)
        self.assertGreater(bus._car.distance, 0)
        self.assertGreater(follower.speed, 0)

    def test_terminal_cannot_board_until_road_space_is_available(self):
        sim, lane = self.system()
        sim.traffic.set_lane_obstacle('blocked', sim.stops['A'].road_position, length=35, width=8)
        sim.lines['L'] = replace(sim.lines['L'], headway_seconds=1)
        person = sim.request_trip(1, (100, 15), (1000, 15), require_bus=True)
        self.until(sim, lambda: person.phase == 'waiting')
        sim.update(35)
        self.assertEqual(person.phase, 'waiting')
        sim.traffic.remove_lane_obstacle('blocked')
        sim.update(.05)
        self.assertEqual(person.phase, 'riding')
        self.assertEqual(sim.buses['bus'].phase, 'docked')
        sim.update(29)
        self.assertEqual(sim.buses['bus'].phase, 'docked')

    def test_save_restore_preserves_docked_body_and_driving_stop(self):
        for phase in ('driving', 'docked'):
            with self.subTest(phase=phase):
                sim, lane = self.system()
                bus = sim.buses['bus']
                self.until(sim, lambda: bus.phase == 'driving')
                if phase == 'docked':
                    self.until(sim, lambda: bus.phase == 'docked')
                data = dump_transport(sim)
                restore_transport(sim, data)
                bus = sim.buses['bus']
                if phase == 'driving':
                    self.until(sim, lambda: bus.phase == 'docked')
                follower = self.follower(sim, lane, 900)
                sim.update(8)
                self.assertEqual(bus.phase, 'docked')
                self.assertEqual(follower.speed, 0)
                self.assertLessEqual(900+follower.distance+follower.length/2+4, 1000-bus.length/2+1e-6)

    def test_new_terminal_bus_cannot_prevent_berthed_bus_departing(self):
        sim, _ = self.system()
        bus = sim.buses['bus']
        self.until(sim, lambda: bus.phase == 'driving')
        self.until(sim, lambda: bus.phase == 'docked' and bus.stop_index == 1)
        self.until(sim, lambda: bus.phase == 'docked' and bus.stop_index == 0)
        sim.add_bus(Bus('new', 'L'))
        self.until(sim, lambda: bus.phase == 'driving')
        self.until(sim, lambda: sim.buses['new'].phase == 'driving')

    def test_waiting_terminal_bus_does_not_disable_idle_time_skipping(self):
        from unittest.mock import patch
        sim, _ = self.system()
        sim.add_bus(Bus('waiting', 'L'))
        with patch.object(sim.traffic, 'update', wraps=sim.traffic.update) as ticks:
            sim.update(20)
        self.assertEqual(sim.time, 20)
        self.assertTrue(all(b.phase == 'docked' for b in sim.buses.values()))
        self.assertLessEqual(ticks.call_count, 1)

    def test_empty_bus_leaves_the_road_when_its_service_closes(self):
        sim, lane = self.system()
        bus = sim.buses['bus']
        bus.service_until = 5
        sim.update(1)
        follower = self.follower(sim, lane, 40)
        sim.update(10)
        self.assertFalse(bus.berthed)
        self.assertGreater(40+follower.distance, 100)

    def test_empty_unfueled_bus_releases_stop_when_service_closes(self):
        sim, lane = self.system()
        bus = sim.buses['bus']
        bus.fuel_liters = 0
        bus.service_until = 40
        sim.add_bus(Bus('next-bus', 'L'))
        sim.update(1)
        follower = self.follower(sim, lane, 40)
        sim.update(120)
        self.assertEqual(bus.phase, 'out_of_fuel')
        self.assertFalse(bus.berthed)
        self.assertTrue(any(e['event'] == 'depart' and e['bus'] == 'next-bus'
                            for e in sim.events))
        self.assertGreater(40 + follower.distance, 100)

    def test_riders_can_wait_for_another_bus_if_fuel_is_insufficient(self):
        sim, _ = self.system()
        bus = sim.buses['bus']
        bus.fuel_liters = .001
        bus.service_until = 40
        sim.add_bus(Bus('next-bus', 'L'))
        person = sim.request_trip(1, (100, 15), (1000, 15), require_bus=True)
        sim.update(100)
        self.assertEqual(bus.passengers, [])
        self.assertNotEqual(person.bus_id, bus.id)
        self.assertTrue(any(e['event'] == 'depart' and e['bus'] == 'next-bus'
                            for e in sim.events))
        self.assertFalse(any(e['event'] == 'board' and e['bus'] == bus.id
                             for e in sim.events))

    def test_unfueled_bus_with_no_closing_time_does_not_block_next_bus(self):
        sim, _ = self.system()
        bus = sim.buses['bus']
        bus.fuel_liters = .001
        sim.add_bus(Bus('next-bus', 'L'))
        person = sim.request_trip(1, (100, 15), (1000, 15), require_bus=True)
        sim.update(100)
        self.assertEqual(bus.phase, 'out_of_fuel')
        self.assertFalse(bus.berthed)
        self.assertNotEqual(person.bus_id, bus.id)
        self.assertTrue(any(e['event'] == 'depart' and e['bus'] == 'next-bus'
                            for e in sim.events))

    def test_service_closing_during_boarding_releases_rider_to_next_bus(self):
        sim, _ = self.system()
        bus = sim.buses['bus']
        bus.service_until = 20
        sim.add_bus(Bus('next-bus', 'L'))
        person = sim.request_trip(1, (100, 15), (1000, 15), require_bus=True)
        sim.update(100)
        self.assertEqual(bus.passengers, [])
        self.assertFalse(bus.berthed)
        self.assertNotEqual(person.bus_id, bus.id)
        self.assertTrue(any(e['event'] == 'depart' and e['bus'] == 'next-bus'
                            for e in sim.events))

    def test_onboard_rider_waits_at_current_stop_if_bus_cannot_continue(self):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (2000, 0)])
        lane = next(l for l in road.lanes if l.direction == 'forward')
        sim = TransitSimulation(city)
        self.addCleanup(sim.traffic._discard_native)
        for name, distance in [('A', 100), ('B', 1000), ('C', 1600)]:
            sim.add_stop(BusStop(name, lane_position_at_distance(lane, distance), (distance, 15)))
        sim.add_line(BusLine('L', ('A', 'B', 'C'), dwell_seconds=10))
        sim.add_bus(Bus('bus', 'L'))
        person = sim.request_trip(1, (100, 15), (1600, 15), require_bus=True)
        self.until(sim, lambda: sim.buses['bus'].phase == 'driving')
        bus = sim.buses['bus']
        self.assertEqual(person.bus_id, bus.id)
        bus.fuel_liters = 0
        self.until(sim, lambda: bus.phase == 'out_of_fuel')
        self.assertEqual(bus.stop_index, 1)
        self.assertEqual(bus.passengers, [])
        self.assertFalse(bus.berthed)
        self.assertEqual((person.phase, person.bus_id, person.board_stop), ('waiting', None, 'B'))
        self.assertIn(person.id, sim.queues[('L', 'B')])

    def test_expiring_berth_is_reused_within_one_large_update(self):
        sim, _ = self.system()
        sim.add_bus(Bus('aaa', 'L', service_until=5))
        sim.update(100)
        departures = [e for e in sim.events if e['event'] == 'depart' and e['bus'] == 'bus']
        self.assertTrue(departures)
        self.assertAlmostEqual(departures[0]['time'], 35)

    @unittest.skipUnless(importlib.util.find_spec('panda3d'), 'Panda3D is required')
    def test_stopped_bus_stays_visible_until_departure(self):
        from types import SimpleNamespace
        from native_viewer import NativeScene
        from panda3d.core import NodePath
        from persistent_fleet import PersistentFleet
        from ui.scene_presenter import ScenePresenter
        sim, _ = self.system()
        fleet = PersistentFleet(sim, {})
        sim.city.gameplay = SimpleNamespace(fleet=fleet, transit=sim)
        scene = NativeScene(NodePath('root'))
        self.addCleanup(scene.close)
        presenter = ScenePresenter(scene)
        sim.update(.05)
        presenter.update(sim.city, sim.traffic)
        self.assertEqual(scene.stats()['parked_vehicles'], 1)
        bus = sim.buses['bus']
        self.until(sim, lambda: bus.phase == 'driving')
        presenter.update(sim.city, sim.traffic)
        self.assertEqual(scene.stats()['parked_vehicles'], 0)
        self.until(sim, lambda: bus.phase == 'docked')
        presenter.update(sim.city, sim.traffic)
        self.assertEqual(scene.stats()['parked_vehicles'], 1)


if __name__ == '__main__':
    unittest.main()
