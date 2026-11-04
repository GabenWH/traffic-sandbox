import importlib.util
import unittest


class CommuteScheduleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('commute_schedule'),'Distributed departures are missing')

    def test_offsets_are_repeatable_and_spread_over_two_hours(self):
        from commute_schedule import CommutePolicy
        policy=CommutePolicy();times=[policy.offset(i,'office-'+str(i%7)) for i in range(1000)]
        self.assertGreater(len(set(times)),800)
        self.assertGreater(max(times)-min(times),5000)
        self.assertTrue(all(0<=x<=7200 for x in times))
        self.assertEqual(times,[policy.offset(i,'office-'+str(i%7)) for i in range(1000)])
        self.assertEqual(CommutePolicy(departure_window=0).offset(99,'office'),0)

    def test_global_and_entrance_limits_are_independent(self):
        from commute_schedule import CommutePolicy,DepartureLimits
        limits=DepartureLimits(CommutePolicy(starts_per_second=2,burst=2,max_active_vehicles=2))
        self.assertTrue(limits.available(0,('lot','a'),0));limits.consume(0,('lot','a'))
        self.assertFalse(limits.available(0,('lot','a'),0))
        self.assertTrue(limits.available(0,('lot','b'),0));limits.consume(0,('lot','b'))
        self.assertFalse(limits.available(0,None,None))
        self.assertFalse(limits.available(.5,('lot','a'),0))
        self.assertTrue(limits.available(.5,('lot','c'),0));limits.consume(.5,('lot','c'))
        self.assertTrue(limits.available(1,('lot','a'),0))
        self.assertFalse(limits.available(1,('lot','a'),2))

    def test_limits_survive_save_without_refilling_a_burst(self):
        from commute_schedule import CommutePolicy,DepartureLimits
        policy=CommutePolicy(burst=1);a=DepartureLimits(policy);a.consume(10,('lot','a'))
        b=DepartureLimits.from_dict(policy,a.to_dict())
        self.assertFalse(b.available(10,None,None))
        self.assertFalse(b.available(10.5,('lot','a'),0))
        self.assertTrue(b.available(11,('lot','a'),0))

    def test_invalid_rates_and_limits_fail_before_simulation(self):
        from commute_schedule import CommutePolicy
        for options in ({'starts_per_second':0},{'burst':0},{'max_active_vehicles':-1},
                        {'departure_window':float('nan')},{'cars_per_entrance_per_second':0}):
            with self.subTest(options=options),self.assertRaises(ValueError):CommutePolicy(**options)
