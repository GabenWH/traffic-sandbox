import unittest

from city import CityMap, Terrain
from mobility import lane_position_at_distance
from transit import Bus, BusLine, BusStop, TransitSimulation


class TransitTests(unittest.TestCase):
    def system(self, capacity=2, fuel=100):
        city = CityMap(terrain=Terrain(trees=[]))
        road = city.add_road([(0, 0), (6000, 0)])
        lane = next(l for l in road.lanes if l.direction == 'forward')
        sim = TransitSimulation(city)
        sim.add_stop(BusStop('A', lane_position_at_distance(lane, 100), (120, 15)))
        sim.add_stop(BusStop('B', lane_position_at_distance(lane, 5700), (5720, 15)))
        sim.add_line(BusLine('L', ('A', 'B'), headway_seconds=300))
        sim.add_bus(Bus('bus-1', 'L', capacity=capacity, fuel_liters=fuel, service_at=30))
        return sim

    def test_walk_board_native_ride_alight_walk_and_fuel(self):
        sim = self.system()
        person = sim.request_trip(1, (100, 15), (5740, 15))
        self.assertEqual(person.phase, 'walking_to_stop')
        sim.update(20)
        self.assertEqual(person.phase, 'waiting')
        self.assertEqual(len(sim.engine.pedestrian_states()), 0)
        sim.update(30)
        self.assertEqual(person.phase, 'riding')
        bus = sim.buses['bus-1']
        self.assertTrue(any(v.id == bus.id and v.source_type == 'bus' for v in sim.traffic.cars))
        self.assertGreater(bus.distance_feet, 0)
        sim.update(350)
        self.assertEqual(person.phase, 'arrived')
        self.assertEqual(sim.engine.pedestrian_states(), [])
        self.assertIs(sim.buses['bus-1'], bus)
        self.assertLess(bus.fuel_liters, 100)
        self.assertTrue({'board', 'alight', 'arrive'} <= {e['event'] for e in sim.events})

    def test_capacity_leaves_passenger_waiting_for_next_visit(self):
        sim = self.system(capacity=1)
        first = sim.request_trip(1, (100, 15), (5740, 15))
        second = sim.request_trip(2, (100, 15), (5740, 15))
        sim.update(60)
        self.assertEqual(first.phase, 'riding')
        self.assertEqual(second.phase, 'waiting')
        self.assertEqual(sim.buses['bus-1'].passengers, [1])
        sim.update(1200)
        self.assertEqual((first.phase, second.phase), ('arrived', 'arrived'))

    def test_empty_fuel_prevents_departure(self):
        sim = self.system(fuel=0)
        sim.request_trip(1, (100, 15), (5740, 15))
        sim.update(60)
        self.assertEqual(sim.buses['bus-1'].phase, 'out_of_fuel')
        self.assertEqual(len(sim.traffic.cars), 0)

    def test_nearby_destination_chooses_walking(self):
        sim = self.system()
        person = sim.request_trip(1, (100, 15), (144, 15))
        self.assertEqual(person.phase, 'walking_direct')
        sim.update(11)
        self.assertEqual(person.phase, 'arrived')

    def test_invalid_services_and_road_edits_fail_explicitly(self):
        sim = self.system()
        with self.assertRaises(ValueError):
            sim.add_bus(Bus('bad', 'L', capacity=0))
        with self.assertRaises(ValueError):
            sim.add_line(BusLine('bad', ('A', 'missing')))
        sim.city.rebuild_mobility_network()
        with self.assertRaisesRegex(RuntimeError, 'Road network changed'):
            sim.update(1)

    def test_headway_holds_second_bus_at_terminal(self):
        sim = self.system(capacity=1)
        sim.add_bus(Bus('bus-2', 'L', capacity=1, service_at=30))
        sim.request_trip(1, (100, 15), (5740, 15))
        sim.request_trip(2, (100, 15), (5740, 15))
        sim.update(60)
        self.assertEqual(sim.buses['bus-1'].phase, 'driving')
        self.assertEqual(sim.buses['bus-2'].phase, 'docked')
        departures = [e for e in sim.events if e['event'] == 'depart' and e['stop'] == 'A']
        self.assertEqual(len(departures), 1)
        sim.update(300)
        departures = [e for e in sim.events if e['event'] == 'depart' and e['stop'] == 'A']
        self.assertGreaterEqual(len(departures), 2)
        self.assertGreaterEqual(departures[1]['time']-departures[0]['time'], 300)


class TerminalFairnessTests(unittest.TestCase):
    def test_second_bus_gets_departure_when_first_returns_before_headway(self):
        from dataclasses import replace
        sim=TransitTests().system(capacity=1)
        sim.lines['L']=replace(sim.lines['L'],headway_seconds=1200)
        sim.add_bus(Bus('bus-2','L',capacity=1,service_at=30))
        sim.request_trip(1,(100,15),(5740,15));sim.update(60)
        sim.request_trip(2,(100,15),(5740,15));sim.update(1250)
        departures=[e for e in sim.events if e['event']=='depart' and e['bus']=='bus-2']
        self.assertTrue(departures)
        self.assertEqual(departures[0]['passengers'],1)


if __name__ == '__main__':
    unittest.main()
