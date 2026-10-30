import unittest
from humboldt_water_transit import Configuration, Network, enabled_lines, simulate

class WaterNetworkTests(unittest.TestCase):
    def test_seven_communities_connected_in_mixed_network(self):
        n = Network(Configuration())
        for place in ('arcata','samoa','eureka','king','fields','fortuna','ferndale'):
            self.assertIsNotNone(n.plan('eureka', place, 0)[0], place)

    def test_ferndale_by_bus_not_assumed_navigable_hovercraft(self):
        n = Network(Configuration())
        _, path = n.plan('eureka', 'ferndale', 0)
        self.assertEqual(path[-1]['line'], 'B2')
        self.assertEqual(path[-1]['mode'], 'bus')

    def test_capacity_pushes_second_passenger_to_next_departure(self):
        n = Network(Configuration())
        line = next(l for l in n.lines if l.id == 'F1')
        for _ in range(line.seats):
            n.plan('samoa','eureka', 0, reserve=True)
        _, last = n.plan('samoa','eureka', 0, reserve=True)
        self.assertGreater(last[0]['departure'], 0)

    def test_disabled_modes_not_routed(self):
        for fleet, mode in [('ferry','hovercraft'), ('hovercraft','ferry'), ('bus','ferry')]:
            self.assertTrue(all(l.mode != mode for l in enabled_lines(Configuration(fleet=fleet))))

    def test_sensitive_exclusion(self):
        n = Network(Configuration(sensitive_exclusion=True))
        self.assertFalse(any(l.mode == 'hovercraft' for l in n.lines))
        self.assertIsNotNone(n.plan('arcata', 'eureka', 0)[0])

    def test_road_failure_without_water_leaves_people_unserved(self):
        n = Network(Configuration(fleet='bus', road_closure=True))
        self.assertIsNone(n.plan('fortuna','fields',0)[0])
        self.assertIsNotNone(n.plan('fortuna','ferndale',0)[0])

    def test_no_double_booking_and_reproducible(self):
        config = Configuration(daily_trips=250,seed=12)
        a = simulate(config)
        b = simulate(config)
        self.assertEqual(a['served'], b['served'])
        self.assertEqual(a['passenger_boardings'], b['passenger_boardings'])
        self.assertEqual(a['requested'], a['served'] + a['unserved'])

    def test_hardened_terminals_scenario(self):
        a = Network(Configuration(sea_rise_ft=6,hardened_terminals=False))
        b = Network(Configuration(sea_rise_ft=6,hardened_terminals=True))
        self.assertLess(len(a.lines),len(b.lines))

    def test_validation(self):
        with self.assertRaises(ValueError): Configuration(headway_scale=0)
        with self.assertRaises(ValueError): Configuration(daily_trips=-1)

if __name__ == '__main__': unittest.main()