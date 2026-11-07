import unittest
from test_city_gameplay import neighborhood, roundtrip
from city_simulation import CitySimulation


class ResidentResourceTests(unittest.TestCase):
    def test_intermediate_economy_settlements_do_not_rescan_households(self):
        from unittest.mock import patch
        runtime,home,*_=neighborhood()
        runtime.invite_household(home.id,1)
        runtime.import_resources(home.id,'food',1)
        with patch.object(runtime,'_consume_households',wraps=runtime._consume_households) as consume:
            runtime.time=10;runtime._settle_economy(10)
            runtime.time=20;runtime._settle_economy(20)
            self.assertEqual(consume.call_count,0)
            runtime.time=60;runtime._run_event('economy',['economy',None])
            self.assertEqual(consume.call_count,1)
            self.assertAlmostEqual(runtime.consumed,60*3/86400)

    def test_household_consumption_batches_and_settles_before_food_arrives(self):
        runtime,home,*_=neighborhood()
        runtime.invite_household(home.id,1)
        runtime.update(30)
        self.assertEqual(runtime.unmet,0)
        runtime.import_resources(home.id,'food',1)
        self.assertAlmostEqual(runtime.unmet,30*3/86400)
        runtime.update(30)
        self.assertAlmostEqual(runtime.consumed,30*3/86400)
        self.assertAlmostEqual(home.inventory.amounts['food'],1-30*3/86400)

    def test_pending_household_consumption_survives_save(self):
        runtime,home,*_=neighborhood()
        runtime.invite_household(home.id,1)
        runtime.import_resources(home.id,'food',1)
        runtime.update(30)
        restored=CitySimulation(roundtrip(runtime.city))
        runtime.update(30);restored.update(30)
        self.assertAlmostEqual(restored.consumed,60*3/86400)
        self.assertAlmostEqual(runtime.consumed,restored.consumed)

    def test_shopping_reserves_stock_and_delivers_only_after_return(self):
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(target.id,1)
        runtime.import_resources(market.id,'food',20)
        p=runtime.residents[h.members[0]]
        self.assertTrue(runtime.request_shopping(p.id,market.id,'food',3))
        self.assertEqual(market.inventory.amounts['food'],17)
        self.assertEqual(target.inventory.amounts.get('food',0),0)
        self.assertEqual(runtime.incoming(target.id,'food'),3)
        runtime.update(300)
        self.assertEqual(p.state,'home')
        self.assertGreater(target.inventory.amounts.get('food',0),2.9)
        self.assertAlmostEqual(runtime.report()['resource_balance_error'],0)

    def test_delivery_suppresses_duplicate_shopping(self):
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(target.id,1)
        runtime.import_resources(market.id,'food',20)
        runtime.jobs['existing']={'source':market.id,'destination':target.id,
            'resource':'food','amount':3,'reserved':3,'stage':'to_source'}
        self.assertFalse(runtime.request_shopping(h.members[0],market.id,'food',3))
        self.assertEqual(market.inventory.amounts['food'],20)

    def test_shopping_roundtrip_preserves_cargo_and_reservation(self):
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(home.id,1)
        runtime.import_resources(market.id,'food',20)
        runtime.request_shopping(h.members[0],market.id,'food',3)
        runtime.update(10)
        restored=CitySimulation(roundtrip(runtime.city))
        self.assertEqual(restored.incoming(home.id,'food'),3)
        runtime.update(1800);restored.update(1800)
        self.assertEqual(runtime.report(),restored.report())
        self.assertAlmostEqual(restored.report()['resource_balance_error'],0)

    def test_city_economy_uses_attendance_without_population_scan(self):
        runtime,*_=neighborhood()
        class NoScan(dict):
            def values(self):raise AssertionError('population scan')
        runtime.residents=NoScan(runtime.residents)
        runtime._economy(60)


class ConstructionLaborTests(unittest.TestCase):
    def runtime(self):
        from construction import ConstructionSimulation,UnlimitedConstructionProvider
        from resources import load_construction_catalog
        runtime,home,target,cafe,bakery,market=neighborhood()
        from models import BuildablePhase
        target.phase=BuildablePhase.UNDER_CONSTRUCTION
        target.construction_needs={};target.construction_delivered={}
        target.construction_workers=1;target.construction_work=10000
        resources,trucks=load_construction_catalog()
        construction=ConstructionSimulation(resources,trucks,UnlimitedConstructionProvider(),road_vehicles=runtime.transit.traffic)
        runtime.construction=construction
        from test_city_gameplay import placed
        company=placed(runtime.city,'construction_company',1000)
        company.phase=BuildablePhase.OPERATIONAL
        runtime.sync_buildings()
        h=runtime.invite_household(home.id,1)
        runtime.assign_workplace(h.members[0],company.id)
        return runtime,target,runtime.residents[h.members[0]]

    def test_construction_needs_resident_arrival_and_pauses_after_departure(self):
        runtime,site,p=self.runtime()
        runtime.update(60)
        self.assertIsNone(site.active_work)
        self.assertEqual(site.assigned_workers,0)
        self.assertFalse(any(type(t.payload).__name__=='CrewPayload' for t in runtime.construction.pending_trips))
        p.worksite=site.id;p.state='commuting_site';runtime._arrive_person(p)
        runtime.update(10)
        self.assertGreater(site.active_work.completed_work,0)
        self.assertEqual(site.assigned_workers,1)
        runtime._safe_depart(p,True)
        before=site.active_work.completed_work
        runtime.update(10)
        self.assertEqual(site.active_work.completed_work,before)
        self.assertEqual(site.assigned_workers,0)

    def test_late_arrival_after_shift_does_not_produce_labor(self):
        runtime,site,p=self.runtime()
        p.return_due=True;p.state='commuting'
        runtime._arrive_person(p)
        runtime.update(2)
        self.assertEqual(site.assigned_workers,0)
        self.assertIsNone(site.active_work)

    def test_instant_commute_retains_attendance(self):
        runtime,site,p=self.runtime()
        runtime.sites[p.workplace]['walk_point']=runtime.sites[p.home]['walk_point']
        self.assertTrue(runtime._safe_depart(p))
        self.assertEqual(p.state,'work')
        self.assertEqual(runtime.staff[p.workplace],1)

    def test_shift_end_stops_labor_even_when_return_route_is_unavailable(self):
        from unittest.mock import patch
        runtime,site,p=self.runtime()
        p.worksite=site.id;p.state='commuting_site';runtime._arrive_person(p);runtime.update(10)
        before=site.active_work.completed_work
        p.return_due=True
        with patch.object(runtime,'_depart',return_value=False):
            runtime._safe_depart(p,True);runtime.update(10)
        self.assertEqual(runtime.staff[site.id],0)
        self.assertEqual(site.active_work.completed_work,before)

    def test_settling_labor_does_not_lose_dispatch_clock_time(self):
        runtime,site,p=self.runtime()
        runtime.construction._seconds_until_next_departure=20
        runtime.time=1
        runtime._settle_economy(1)
        runtime._run_event('construction',['construction',None])
        self.assertEqual(runtime.construction._seconds_until_next_departure,19)

class ShoppingFailureTests(unittest.TestCase):
    def test_failed_route_does_not_reserve_food(self):
        from unittest.mock import patch
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(home.id,1)
        runtime.import_resources(market.id,'food',20)
        with patch.object(runtime.transit,'request_trip',side_effect=ValueError('no route')):
            with self.assertRaises(ValueError):runtime.request_shopping(h.members[0],market.id)
        self.assertEqual(market.inventory.amounts['food'],20)
        self.assertEqual(runtime.visits,{})
        self.assertEqual(runtime.residents[h.members[0]].state,'home')

    def test_closed_market_returns_reservation_without_free_groceries(self):
        from models import BuildablePhase
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(home.id,1)
        runtime.import_resources(market.id,'food',20)
        runtime.request_shopping(h.members[0],market.id)
        runtime.update(10)
        market.phase=BuildablePhase.DECOMMISSIONED;runtime.sync_buildings()
        runtime.update(1800)
        self.assertEqual(runtime.residents[h.members[0]].state,'home')
        self.assertEqual(market.inventory.amounts['food'],20)
        self.assertEqual(home.inventory.amounts.get('food',0),0)
        self.assertAlmostEqual(runtime.report()['resource_balance_error'],0)

    def test_shopping_return_after_shift_start_resumes_commute(self):
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(home.id,1)
        runtime.update(runtime.work_start-60)
        runtime.import_resources(market.id,'food',20)
        p=runtime.residents[h.members[0]]
        runtime.request_shopping(p.id,market.id)
        runtime.update(2400)
        self.assertIn(p.state,('commuting','work'))

    def test_shopping_cannot_bypass_reservation_api(self):
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(home.id,1)
        with self.assertRaises(ValueError):
            runtime.request_visit(h.members[0],market.id,'shopping')
        self.assertEqual(runtime.visits,{})
        runtime.report()

class WorkforceBootstrapTests(unittest.TestCase):
    def test_empty_city_keeps_bootstrap_crews_then_switches_to_residents(self):
        from construction import ConstructionSimulation,UnlimitedConstructionProvider,CrewPayload
        from resources import load_construction_catalog
        from traffic_testbed import RoadVehicleSimulation
        from city import CityMap,Terrain
        from test_city_gameplay import placed
        from models import BuildablePhase
        city=CityMap(terrain=Terrain(trees=[]));city.add_road([(0,30),(4500,30)])
        home=placed(city,'small_house',200)
        traffic=RoadVehicleSimulation(update_mode='cpp',spawn_interval=10000)
        resources,trucks=load_construction_catalog()
        construction=ConstructionSimulation(resources,trucks,UnlimitedConstructionProvider(),road_vehicles=traffic)
        runtime=CitySimulation(city,traffic,construction)
        self.assertFalse(construction.resident_workforce)
        runtime.update(1)
        self.assertTrue(any(isinstance(t.payload,CrewPayload) for t in construction.pending_trips))
        home.phase=BuildablePhase.OPERATIONAL;runtime.sync_buildings()
        site=placed(city,'small_house',800);site.assigned_workers=2;runtime.sync_buildings()
        runtime.invite_household(home.id,1)
        self.assertFalse(construction.resident_workforce)
        company=placed(city,'construction_company',1200);company.phase=BuildablePhase.OPERATIONAL
        runtime.sync_buildings()
        self.assertTrue(construction.resident_workforce)
        self.assertEqual(site.assigned_workers,0)


class ConstructionCompanyTests(unittest.TestCase):
    runtime=ConstructionLaborTests.runtime
    def test_employer_stays_company_through_site_trip_and_completion(self):
        runtime,site,p=self.runtime()
        company=p.workplace
        runtime._safe_depart(p)
        runtime.update(400)
        self.assertEqual(p.workplace,company)
        self.assertEqual(p.worksite,site.id)
        self.assertIn(p.state,('commuting_site','work'))
        runtime.update(800)
        self.assertEqual(p.state,'work')
        self.assertEqual(runtime.staff[site.id],1)
        self.assertEqual(runtime.staff[company],0)
        site.active_work.required_work=site.active_work.completed_work+1
        runtime.update(1000)
        self.assertEqual(p.workplace,company)
        self.assertIsNone(p.worksite)
        self.assertEqual(p.state,'work')
        self.assertEqual(runtime.staff[company],1)

    def test_save_during_site_trip_keeps_employer_and_assignment(self):
        runtime,site,p=self.runtime()
        runtime._safe_depart(p);runtime.update(400)
        from construction import ConstructionSimulation,UnlimitedConstructionProvider
        from resources import load_construction_catalog
        from traffic_testbed import RoadVehicleSimulation
        city=roundtrip(runtime.city)
        traffic=RoadVehicleSimulation(update_mode='cpp',spawn_interval=10000)
        resources,trucks=load_construction_catalog()
        construction=ConstructionSimulation(resources,trucks,UnlimitedConstructionProvider(),road_vehicles=traffic)
        restored=CitySimulation(city,traffic,construction)
        q=restored.residents[p.id]
        self.assertEqual(q.workplace,p.workplace)
        self.assertEqual(q.worksite,site.id)
        restored.update(800)
        restored_site=restored.sites[site.id]['building']
        self.assertGreater(restored_site.active_work.completed_work,0)
        restored_site.active_work.required_work=restored_site.active_work.completed_work+1
        restored.update(1000)
        self.assertIsNone(q.worksite)
        self.assertEqual(q.workplace,p.workplace)
        q.return_due=True;restored._safe_depart(q,True);restored.update(1000)
        self.assertEqual(q.state,'home')

    def test_failed_site_return_preserves_shift(self):
        from unittest.mock import patch
        from models import BuildablePhase
        runtime,site,p=self.runtime()
        p.worksite=site.id;p.state='commuting_site';runtime._arrive_person(p)
        site.phase=BuildablePhase.OPERATIONAL
        with patch.object(runtime.transit,'request_trip',side_effect=ValueError('closed path')):
            runtime.sync_buildings();runtime.update(61)
        self.assertFalse(p.return_due)

    def test_builder_retrieves_car_at_company_before_going_home(self):
        from persistent_fleet import FleetVehicle
        runtime,site,p=self.runtime()
        p.mode='car';p.car_id='builder-car'
        runtime.fleet.add(FleetVehicle(p.car_id,'car',p.home,driver=p.id))
        runtime._safe_depart(p);runtime.update(1400)
        self.assertEqual(p.worksite,site.id)
        self.assertEqual(p.state,'work')
        p.return_due=True;runtime._safe_depart(p,True);runtime.update(1400)
        self.assertEqual(p.state,'home')
        self.assertEqual(runtime.fleet.vehicles[p.car_id].site,p.home)

    def test_dispatch_looks_at_available_builders_not_whole_population(self):
        runtime,site,p=self.runtime()
        p.state='commuting';runtime._arrive_person(p)
        class NoScan(dict):
            def values(self):raise AssertionError('population scan during dispatch')
        runtime.residents=NoScan(runtime.residents)
        runtime._dispatch_builders()
        self.assertEqual(p.worksite,site.id)

    def test_builder_retries_temporarily_blocked_dispatch(self):
        from unittest.mock import patch
        runtime,site,p=self.runtime()
        p.state='commuting';runtime._arrive_person(p)
        with patch.object(runtime.transit,'request_trip',side_effect=ValueError('temporary closure')):
            runtime.update(1)
        runtime.update(1000)
        self.assertEqual(p.worksite,site.id)
        self.assertEqual(p.state,'work')

    def test_builder_can_shop_then_commute_by_car_and_walk_to_site(self):
        from persistent_fleet import FleetVehicle
        runtime,site,p=self.runtime()
        market=next(b for b in runtime.businesses.values() if b.kind=='market')
        runtime.import_resources(market.site,'food',20)
        runtime.request_shopping(p.id,market.site);runtime.update(1800)
        self.assertEqual(p.state,'home')
        p.mode='car';p.car_id='builder-car'
        runtime.fleet.add(FleetVehicle(p.car_id,'car',p.home,driver=p.id))
        runtime._safe_depart(p);runtime.update(1400)
        self.assertEqual(p.worksite,site.id)
        self.assertEqual(p.state,'work')

    def test_closing_company_does_not_restore_unlimited_bootstrap_labor(self):
        from models import BuildablePhase
        runtime,site,p=self.runtime()
        runtime.sites[p.workplace]['building'].phase=BuildablePhase.DECOMMISSIONED
        runtime.sync_buildings()
        self.assertTrue(runtime.construction.resident_workforce)
        self.assertTrue(runtime.snapshot()['resident_construction_started'])
