import unittest
from city import CityMap,Terrain
from mobility import lane_position_at_distance
from transit import TransitSimulation,Bus,BusLine,BusStop


class TransferTests(unittest.TestCase):
    def test_two_lines_transfer_at_shared_stop_and_keep_capacity(self):
        city=CityMap(terrain=Terrain(trees=[]));road=city.add_road([(0,0),(9000,0)])
        lane=road.lanes[0];sim=TransitSimulation(city)
        for name,x in [('A',120),('H',4500),('C',8500)]:
            sim.add_stop(BusStop(name,lane_position_at_distance(lane,x-20),(x,15)))
        for name,stops in [('west',('A','H')),('east',('H','C'))]:
            sim.add_line(BusLine(name,stops,headway_seconds=10))
            sim.add_bus(Bus(name,name,service_at=10))
        person=sim.request_trip(1,(100,15),(8520,15))
        self.assertEqual([l['line'] for l in person.itinerary],['west','east'])
        sim.update(1600)
        self.assertEqual(person.phase,'arrived')
        boards=[e for e in sim.events if e['event']=='board']
        self.assertEqual([e['bus'] for e in boards],['west','east'])
        self.assertTrue(all(b.capacity==60 for b in sim.buses.values()))

    def test_distant_stop_makes_walking_directly_faster(self):
        city=CityMap(terrain=Terrain(trees=[]));road=city.add_road([(0,0),(9000,0)])
        lane=road.lanes[0];sim=TransitSimulation(city)
        for name,x in [('far',120),('end',8500)]:
            sim.add_stop(BusStop(name,lane_position_at_distance(lane,x-20),(x,15)))
        sim.add_line(BusLine('line',('far','end'),headway_seconds=10))
        sim.add_bus(Bus('bus','line'))
        # Walking 6,880 feet backward to the stop is worse than a direct
        # 1,500-foot walk, even before waiting and riding are added.
        person=sim.request_trip(2,(7000,15),(8500,15))
        self.assertEqual(person.phase,'walking_direct')
        self.assertEqual(person.itinerary,[])
