"""The mapped-building benchmark must seed one shared runtime and end on time."""
import contextlib
import io
import unittest

from city import Building, CityMap, Parcel, Terrain, ZoneType
from models import BuildablePhase


def small_city():
    city = CityMap(width=1400,height=600,terrain=Terrain(trees=[]))
    city.add_road([(20,100),(1300,100)])
    for ident,x,residents,zone in [('home-a',200,4,ZoneType.RESIDENTIAL),
                                  ('home-b',400,4,ZoneType.RESIDENTIAL),
                                  ('job',900,0,ZoneType.COMMERCIAL)]:
        parcel=Parcel(x,170,40,40,zone)
        city.parcels.append(parcel)
        city.buildings.append(Building(ident,parcel,id=ident,residents=residents,
                                       phase=BuildablePhase.OPERATIONAL))
    return city


class NeighborhoodWorkdayTests(unittest.TestCase):
    def test_all_households_and_cars_use_mapped_buildings_in_one_runtime(self):
        from tools.run_arcata_city_workday import build_scenario
        city=small_city();original=[b.id for b in city.buildings]
        from commute_schedule import CommutePolicy
        runtime,config=build_scenario(city,cars=2,seed=42,start_hour=7.49,
                                       commute_policy=CommutePolicy(departure_window=0))
        self.assertEqual([b.id for b in city.buildings],original)
        self.assertEqual(len(runtime.residents),8)
        self.assertEqual(len(runtime.households),2)
        self.assertEqual(sum(p.worker for p in runtime.residents.values()),4)
        self.assertEqual(len(runtime.fleet.vehicles),2)
        self.assertTrue(all(p.workplace=='job' for p in runtime.residents.values() if p.worker))
        self.assertTrue(all(v.parking_space_id for v in runtime.fleet.vehicles.values()))
        self.assertEqual(config['synthetic_locations'],False)
        self.assertEqual(config['cars'],2)
        runtime.update(300)
        self.assertEqual(runtime.workers_arrived,4)
        self.assertEqual(runtime.fleet.parked_at('job'),2)
        self.assertAlmostEqual(runtime.report()['resource_balance_error'],0,places=6)

    def test_fractional_duration_reports_exact_end_and_fifty_ms_steps(self):
        from tools.run_arcata_city_workday import build_scenario,run_workday
        runtime,_=build_scenario(small_city(),cars=1,seed=42,start_hour=6)
        reports=[]
        result=run_workday(runtime,hours=1/3600,report_every=.4,emit=reports.append)
        self.assertEqual(result['stop_reason'],'duration')
        self.assertAlmostEqual(result['simulated_seconds'],1)
        self.assertEqual(result['ticks'],20)
        self.assertAlmostEqual(runtime.time,21601)
        self.assertEqual(len(reports),4) # initial, .4, .8, 1.0
        self.assertAlmostEqual(reports[-1]['simulated_seconds'],1)
        self.assertEqual(reports[-1]['population'],8)
        self.assertIn('tick_p99_ms',reports[-1])

    def test_expired_wall_budget_finishes_with_a_report(self):
        from tools.run_arcata_city_workday import build_scenario,run_workday
        import time
        runtime,_=build_scenario(small_city(),cars=0,seed=42,start_hour=6)
        reports=[]
        result=run_workday(runtime,hours=1,report_every=60,emit=reports.append,
                           deadline=time.perf_counter()-1)
        self.assertEqual(result['stop_reason'],'wall_limit')
        self.assertEqual(result['ticks'],0)
        self.assertEqual(result['simulated_seconds'],0)
        self.assertTrue(reports)

    def test_population_target_uses_existing_capacity_without_adding_buildings(self):
        from tools.run_arcata_city_workday import build_scenario
        city=small_city()
        runtime,config=build_scenario(city,cars=1,seed=42,start_hour=6,population=6)
        self.assertEqual(len(runtime.residents),6)
        self.assertEqual(sum(p.worker for p in runtime.residents.values()),3)
        self.assertEqual(sum(b.residents for b in city.buildings),8)
        self.assertEqual(len(city.buildings),3)
        self.assertEqual(config['population'],6)
        self.assertEqual(config['requested_population'],6)
        with self.assertRaisesRegex(ValueError,'capacity'):
            build_scenario(small_city(),cars=0,seed=42,start_hour=6,population=10000)

    def test_default_run_uses_citywide_data_and_ten_thousand_residents(self):
        from tools.run_arcata_city_workday import parse_args
        args=parse_args([])
        self.assertEqual(args.population,10000)
        self.assertEqual(args.cars,1000)
        self.assertIn('citywide',args.buildings.name)
        self.assertEqual(args.departure_window_minutes,120)
        self.assertEqual(args.departures_per_second,20)
        self.assertEqual(args.max_active_cars,2000)

    def test_configurable_departure_limits_are_reported_and_bad_values_fail_early(self):
        from tools.run_arcata_city_workday import build_scenario,parse_args
        from commute_schedule import CommutePolicy
        runtime,config=build_scenario(small_city(),cars=1,commute_policy=CommutePolicy(
            departure_window=1800,starts_per_second=3,max_active_vehicles=7))
        self.assertEqual(config['commute_policy']['departure_window'],1800)
        self.assertEqual(config['commute_policy']['max_active_vehicles'],7)
        self.assertIn('routing_pending',runtime.report())
        for options in (['--departure-window-minutes','-1'],['--departures-per-second','0'],['--max-active-cars','0']):
            with self.subTest(options=options),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):parse_args(options)

    def test_stack_watch_records_main_thread_and_stops(self):
        from tools.run_arcata_city_workday import start_stack_watch
        from pathlib import Path
        import tempfile,time
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stacks.log'
            stop,worker=start_stack_watch(path,.01,time.perf_counter())
            try:
                deadline=time.perf_counter()+5
                while not path.exists() and time.perf_counter()<deadline:time.sleep(.01)
            finally:
                stop.set();worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertIn('test_stack_watch_records_main_thread',path.read_text())

    def test_cli_rejects_bad_limits_before_loading_the_map(self):
        from tools.run_arcata_city_workday import parse_args
        for args in (['--hours','0'],['--hours','nan'],['--hours','inf'],
                     ['--wall-seconds','0'],['--report-every','0'],['--cars','-1'],
                     ['--population','0'],['--stack-every','-1']):
            with self.subTest(args=args),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:parse_args(args)
                self.assertEqual(result.exception.code,2)
