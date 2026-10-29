"""Regression cases from the independent whole-branch review."""
import unittest
from tests.test_city_gameplay import neighborhood, placed, roundtrip
from models import BuildablePhase


def disconnect(runtime):
    runtime.city.roads.clear();runtime.city.intersections.clear()
    runtime.city.rebuild_mobility_network();runtime.sync_network();runtime.update(0)


def reconnect(runtime):
    runtime.city.add_road([(30,30),(4500,30)])
    runtime.sync_network();runtime.update(0)


class CityRecoveryTests(unittest.TestCase):
    def test_pending_walk_and_car_survive_two_road_edits(self):
        runtime,home,target,*_=neighborhood()
        h=runtime.invite_household(home.id,2,car=True)
        runtime.import_resources(home.id,'food',20)
        runtime.relocate(h.id,target.id);runtime.update(5)
        disconnect(runtime)
        self.assertTrue(runtime._suspended_walkers)
        self.assertTrue(runtime._resuming_vehicles)
        reconnect(runtime);runtime.update(1200)
        self.assertEqual(h.home,target.id)
        self.assertEqual(len(runtime.residents),2)
        self.assertAlmostEqual(runtime.report()['resource_balance_error'],0,places=7)

    def test_disconnected_bus_line_and_riders_save_restore_and_reconnect(self):
        from city_simulation import CitySimulation
        runtime,home,target,*_=neighborhood()
        stops=[]
        for x in (200,3200):
            b=placed(runtime.city,'bus_stop',x,50);b.phase=BuildablePhase.OPERATIONAL;stops.append(b.id)
        runtime.sync_buildings();lid=runtime.create_line(stops)
        h=runtime.invite_household(home.id,2)
        runtime.relocate(h.id,target.id);runtime.update(30)
        self.assertTrue(any(b.passengers for b in runtime.transit.buses.values()))
        disconnect(runtime)
        restored=CitySimulation(roundtrip(runtime.city))
        reconnect(restored);restored.update(1200)
        self.assertEqual(restored.households[h.id].home,target.id)
        self.assertIn(lid,restored.transit.lines)
        self.assertEqual(len(restored.transit.buses),2)

    def test_served_customer_can_wait_for_disconnected_return_path(self):
        runtime,home,target,cafe,*_=neighborhood()
        h=runtime.invite_household(target.id,2)
        worker=runtime.residents[h.members[0]];worker.workplace=cafe.id;worker.state='work'
        runtime.import_resources(cafe.id,'food',5)
        customer=runtime.residents[h.members[1]]
        # Native arrival is about 57 s; interrupt before the 60 s service event.
        runtime.request_visit(customer.id,cafe.id,'meal');runtime.update(58)
        self.assertEqual(customer.state,'waiting_meal')
        disconnect(runtime);runtime.update(60)
        self.assertEqual(runtime.meals_served,1)
        reconnect(runtime);runtime.update(600)
        self.assertEqual(customer.state,'home')
        self.assertNotIn(customer.id,runtime.visits)
        self.assertEqual(runtime.meals_served,1)

    def test_last_cafe_worker_does_not_leave_for_same_time_lunch(self):
        runtime,home,target,cafe,bakery,*_=neighborhood()
        a=runtime.invite_household(home.id,4)
        b=runtime.invite_household(target.id,4)
        for p in runtime.residents.values():
            if p.worker:p.workplace=cafe.id if p.id in (a.members[0],b.members[0]) else bakery.id
        runtime.import_resources(cafe.id,'food',100)
        runtime.update(13*3600)
        self.assertGreater(runtime.meals_served,0)
        self.assertEqual(runtime.residents[a.members[0]].state,'work')
        self.assertEqual(runtime.residents[b.members[0]].state,'work')

    def test_workplace_closing_during_commute_returns_worker(self):
        runtime,home,_,_,bakery,*_=neighborhood()
        h=runtime.invite_household(home.id,1)
        p=runtime.residents[h.members[0]];p.workplace=bakery.id
        runtime.update(runtime.work_start+60)
        self.assertEqual(p.state,'commuting')
        bakery.phase=BuildablePhase.DECOMMISSIONED;runtime.sync_buildings()
        runtime.update(1800)
        self.assertEqual(p.state,'home')

    def test_failed_car_return_after_visit_uses_city_event_format(self):
        runtime,home,_,cafe,bakery,*_=neighborhood()
        h=runtime.invite_household(home.id,1,car=True)
        p=runtime.residents[h.members[0]]
        p.workplace=bakery.id;p.state='visiting_return';p.return_due=True
        vehicle=runtime.fleet.vehicles[p.car_id];vehicle.site=bakery.id;vehicle.fuel_liters=0
        runtime.visits[p.id]=dict(site=cafe.id,purpose='meal',origin=bakery.id,previous='work')
        runtime._arrive_person(p);runtime.update(10)
        self.assertEqual(p.state,'work')
        self.assertTrue(any(e[2]=='retry_return' for e in runtime._events))
        self.assertIs(runtime.fleet.vehicles[p.car_id],vehicle)

    def test_building_completion_advances_housing_review_without_duplicate_months(self):
        runtime,home,*_=neighborhood()
        h=runtime.invite_household(home.id,2)
        new=placed(runtime.city,'small_house',4100);new.phase=BuildablePhase.OPERATIONAL
        runtime.sync_buildings()
        reviews=[e for e in runtime._events if e[2] in ('assess','assess_changed') and e[3][1]==h.id]
        self.assertLessEqual(min(e[0] for e in reviews),runtime.time+121)
        runtime.update(125)
        monthly=[e for e in runtime._events if e[2]=='assess' and e[3][1]==h.id]
        self.assertEqual(len(monthly),1)

    def test_visit_return_does_not_remove_another_workers_presence(self):
        runtime,home,_,cafe,bakery,*_=neighborhood()
        h=runtime.invite_household(home.id,2,car=True)
        p,other=(runtime.residents[pid] for pid in h.members)
        p.workplace=other.workplace=bakery.id
        p.state='visiting_return';p.return_due=True;other.state='work'
        runtime.staff[bakery.id]=1
        runtime.fleet.vehicles[p.car_id].site=bakery.id
        runtime.visits[p.id]=dict(site=cafe.id,purpose='meal',origin=bakery.id,previous='work')
        runtime._arrive_person(p)
        self.assertEqual(p.state,'returning')
        self.assertEqual(runtime.staff[bakery.id],1)

    def test_closing_service_releases_queued_customer_to_home(self):
        runtime,home,target,cafe,*_=neighborhood()
        h=runtime.invite_household(target.id,2)
        worker=runtime.residents[h.members[0]];worker.workplace=cafe.id;worker.state='work'
        customer=runtime.residents[h.members[1]]
        runtime.import_resources(cafe.id,'food',5)
        # Native arrival is about 57 s; interrupt before the 60 s service event.
        runtime.request_visit(customer.id,cafe.id,'meal');runtime.update(58)
        self.assertEqual(customer.state,'waiting_meal')
        cafe.phase=BuildablePhase.DECOMMISSIONED;runtime.sync_buildings();runtime.update(600)
        self.assertEqual(customer.state,'home')
        self.assertNotIn(customer.id,runtime.visits)
        self.assertNotIn(customer.id,runtime.meal_queues[cafe.id])

    def test_consumption_credit_follows_household_during_move(self):
        runtime,home,target,*_=neighborhood()
        a=runtime.invite_household(home.id,2);b=runtime.invite_household(home.id,2)
        runtime.meal_credit[home.id]=4
        runtime.relocate(a.id,target.id)
        self.assertEqual(a.meal_credit,2)
        self.assertEqual(runtime.meal_credit[home.id],2)
        runtime.relocate(b.id,target.id)
        self.assertEqual(b.meal_credit,2)
        self.assertEqual(runtime.meal_credit[home.id],0)
        runtime.update(1200)
        self.assertGreater(runtime.meal_credit[target.id],0)
        self.assertEqual(a.meal_credit+b.meal_credit,0)

    def test_native_reset_requeues_unfinished_construction_deliveries(self):
        from city import CityMap, Terrain
        from city_simulation import CitySimulation
        from traffic_testbed import RoadVehicleSimulation
        from construction import ConstructionSimulation, UnlimitedConstructionProvider
        from resources import load_construction_catalog
        city=CityMap(terrain=Terrain(trees=[]));city.add_road([(0,100),(800,100)])
        home=placed(city,'small_house',600,140)
        traffic=RoadVehicleSimulation(update_mode='cpp',spawn_interval=10000)
        resources,trucks=load_construction_catalog()
        construction=ConstructionSimulation(resources,trucks,UnlimitedConstructionProvider(),road_vehicles=traffic)
        runtime=CitySimulation(city,traffic,construction);runtime.update(2)
        self.assertTrue(construction.trips)
        traffic.clear_vehicles();runtime.sync_network();runtime.update(1200)
        self.assertEqual(home.phase,BuildablePhase.OPERATIONAL)
        self.assertFalse(construction.trips)

    def test_labor_and_food_accounting_do_not_depend_on_update_chunk_size(self):
        a,home_a,_,_,bakery_a,*_=neighborhood()
        b,home_b,_,_,bakery_b,*_=neighborhood()
        for runtime,home,bakery in ((a,home_a,bakery_a),(b,home_b,bakery_b)):
            h=runtime.invite_household(home.id,1)
            runtime.residents[h.members[0]].workplace=bakery.id
            runtime.import_resources(bakery.id,'grain',100)
        a.update(a.work_start+900)
        b.update(b.work_start)
        for _ in range(900):b.update(1)
        self.assertAlmostEqual(a.produced,b.produced,places=6)
        self.assertAlmostEqual(a.consumed,b.consumed,places=6)
        self.assertEqual(a.workers_arrived,b.workers_arrived)

    def test_cafe_service_budget_depends_on_elapsed_time(self):
        runtime,home,target,cafe,*_=neighborhood()
        h=runtime.invite_household(target.id,3)
        worker=runtime.residents[h.members[0]];worker.workplace=cafe.id;worker.state='work'
        runtime.import_resources(cafe.id,'food',5)
        for pid in h.members[1:]:
            runtime.residents[pid].state='waiting_meal'
            runtime.visits[pid]=dict(site=cafe.id,purpose='meal',origin=target.id,previous='home')
            runtime.meal_queues[cafe.id].append(pid)
        runtime._economy(10)
        self.assertEqual(runtime.meals_served,0)
        runtime._economy(50)
        self.assertEqual(runtime.meals_served,1)
        runtime._economy(60)
        self.assertEqual(runtime.meals_served,2)
