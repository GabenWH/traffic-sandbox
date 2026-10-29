"""Gameplay must use authored buildings and the existing native transport."""
import json
import unittest
from types import SimpleNamespace

from city import CityMap, Terrain
from models import BuildablePhase
from persistence import world_to_dict, world_from_dict
from ui_tools.buildables import buildables_of_kind
from ui_tools.tools.road_tool import BuildingTool


def placed(city, template, x, y=70):
    host = SimpleNamespace(city_map=city, redraw_world=lambda: None)
    tool = BuildingTool(host)
    tool.selected_spec = next(s for s in tool.specs if s.id == template)
    return tool.place_building((x, y))


def roundtrip(city):
    return world_from_dict(json.loads(json.dumps(world_to_dict(
        city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)))).city_map


class OperationalBuildingTests(unittest.TestCase):
    def test_place_cafe_through_existing_building_tool_and_save(self):
        city = CityMap(terrain=Terrain(trees=[]))
        cafe = placed(city, 'cafe', 400)
        self.assertEqual(cafe.operation['role'], 'cafe')
        self.assertEqual(cafe.phase, BuildablePhase.UNDER_CONSTRUCTION)
        self.assertTrue(cafe.construction_needs)
        self.assertEqual(cafe.occupants, 0)
        self.assertEqual(roundtrip(city).buildings[0].operation, cafe.operation)

    def test_existing_housing_template_keeps_capacity_separate_from_occupancy(self):
        city = CityMap(terrain=Terrain(trees=[]))
        home = placed(city, 'small_house', 200)
        self.assertEqual(home.residents, 4)
        self.assertEqual(home.occupants, 0)
        self.assertEqual(home.operation['role'], 'home')

    def test_operation_validation_rejects_nonfinite_rates_and_bad_recipes(self):
        from building_operations import validate_operation
        for operation in ({'role':'bakery','rate':float('nan')},
                          {'role':'bakery','inputs':{'grain':0}},
                          {'role':'farm','quality':101}):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                validate_operation(operation)


def neighborhood():
    from city_simulation import CitySimulation
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(30,30),(4500,30)])
    home=placed(city,'small_house',200)
    other=placed(city,'small_house',3200)
    cafe=placed(city,'cafe',3400)
    bakery=placed(city,'bakery',3600)
    market=placed(city,'market',3300)
    for b in city.buildings: b.phase=BuildablePhase.OPERATIONAL
    return CitySimulation(city),home,other,cafe,bakery,market


class CityRuntimeTests(unittest.TestCase):
    def test_placed_buildings_activate_after_construction_and_new_homes_are_vacant(self):
        from city_simulation import CitySimulation
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(20,30),(4200,30)])
        cafe=placed(city,'cafe',600)
        runtime=CitySimulation(city)
        self.assertNotIn(cafe.id,runtime.businesses)
        cafe.phase=BuildablePhase.OPERATIONAL
        runtime.sync_buildings()
        self.assertIn(cafe.id,runtime.businesses)
        self.assertIs(runtime.sites[cafe.id]['building'],cafe)
        home=placed(city,'small_house',200)
        home.phase=BuildablePhase.OPERATIONAL
        runtime.sync_buildings()
        self.assertEqual(home.occupants,0)
        household=runtime.invite_household(home.id,4)
        self.assertEqual(home.occupants,4)
        self.assertEqual(len(runtime.residents),4)
        with self.assertRaises(ValueError):runtime.invite_household(home.id,1)

    def test_economy_and_housing_are_not_recalculated_on_each_frame(self):
        runtime,home,*_=neighborhood()
        runtime.invite_household(home.id,2)
        before=dict(runtime.counters)
        for _ in range(100):runtime.update(.05)
        self.assertEqual(runtime.counters['economy'],before['economy'])
        self.assertEqual(runtime.counters['housing'],before['housing'])
        runtime.update(60)
        self.assertEqual(runtime.counters['economy'],before['economy']+1)
        self.assertEqual(runtime.transit.time,runtime.transit.traffic.elapsed_time)

    def test_relocation_reserves_vacancy_and_preserves_people_food_and_car(self):
        runtime,home,target,*_=neighborhood()
        h=runtime.invite_household(home.id,2,car=True)
        rival=runtime.invite_household(home.id,2)
        home.inventory.amounts['food']=20
        runtime.relocate(h.id,target.id)
        runtime.relocate(rival.id,target.id)
        with self.assertRaises(ValueError):runtime.invite_household(target.id,1)
        ids=set(runtime.residents);car_id=runtime.residents[h.members[0]].car_id
        runtime.update(1100)
        self.assertEqual(h.home,target.id)
        self.assertEqual(rival.home,target.id)
        self.assertEqual(set(runtime.residents),ids)
        self.assertEqual((home.occupants,target.occupants),(0,4))
        self.assertEqual(runtime.fleet.vehicles[car_id].site,target.id)
        self.assertAlmostEqual(sum(b.inventory.amounts.get('food',0) for b in runtime.city.buildings)+runtime.consumed,20)

    def test_desirability_uses_resource_access_and_buffer_before_moving(self):
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(home.id,2)
        market.inventory.amounts['food']=100
        self.assertGreater(runtime.desirability(h,target.id),runtime.desirability(h,home.id))
        h.memory.buffer=100;h.memory.target=100
        runtime.assess_household(h.id)
        self.assertIsNone(h.moving_to)
        h.memory.buffer=0;h.memory.target=0
        runtime.assess_household(h.id)
        self.assertEqual(h.moving_to,target.id)

    def test_workday_repeats_and_staff_production_depends_on_arrival(self):
        runtime,home,target,cafe,bakery,market=neighborhood()
        h=runtime.invite_household(target.id,2)
        bakery.inventory.amounts['grain']=100
        # Assign to the actual placed bakery, then exercise two scheduled days.
        p=runtime.residents[h.members[0]]
        p.workplace=bakery.id
        runtime.update(2*86400)
        self.assertGreater(runtime.produced,0)
        self.assertTrue(all(p.state=='home' for p in runtime.residents.values()))
        self.assertGreaterEqual(sum(e['event']=='worker_arrived' for e in runtime.events),2)

    def test_empty_city_can_advance_years_without_movement_or_decision_ticks(self):
        from city_simulation import CitySimulation
        runtime=CitySimulation(CityMap(terrain=Terrain(trees=[])))
        runtime.update(365*86400*3)
        self.assertEqual(runtime.counters['economy'],0)
        self.assertEqual(runtime.counters['housing'],0)
        self.assertEqual(runtime.time,365*86400*3)

    def test_construction_and_households_share_one_native_clock(self):
        from city_simulation import CitySimulation
        from construction import ConstructionSimulation, UnlimitedConstructionProvider
        from resources import load_construction_catalog
        from traffic_testbed import RoadVehicleSimulation
        city=CityMap(terrain=Terrain(trees=[]));city.add_road([(30,30),(4200,30)])
        home=placed(city,'small_house',200)
        traffic=RoadVehicleSimulation(update_mode='cpp',spawn_interval=10000)
        resources,trucks=load_construction_catalog()
        construction=ConstructionSimulation(resources,trucks,UnlimitedConstructionProvider(),road_vehicles=traffic)
        runtime=CitySimulation(city,traffic,construction)
        runtime.update(10)
        self.assertIs(runtime.transit.traffic,construction.road_vehicles)
        self.assertEqual(traffic.elapsed_time,10)
        self.assertEqual(runtime.transit.time,10)
        self.assertNotIn(home.id,runtime._homes)

    def test_disconnected_building_is_inspectable_and_waits_for_jobs(self):
        from city_simulation import CitySimulation
        city=CityMap(terrain=Terrain(trees=[]));home=placed(city,'small_house',200)
        home.phase=BuildablePhase.OPERATIONAL
        runtime=CitySimulation(city);h=runtime.invite_household(home.id,2)
        runtime.update(300)
        self.assertEqual(len(runtime.residents),2)
        self.assertTrue(all(runtime.residents[p].state=='home' for p in h.members))


class GameplayPersistenceTests(unittest.TestCase):
    def test_json_roundtrip_preserves_active_relocation_and_native_progress(self):
        from city_simulation import CitySimulation
        runtime,home,target,*_=neighborhood()
        h=runtime.invite_household(home.id,3,car=True)
        runtime.import_resources(home.id,'food',30)
        runtime.relocate(h.id,target.id);runtime.update(5)
        before={r.id:r.distance for r in runtime.transit.engine.pedestrian_states()}
        self.assertTrue(before)
        city=roundtrip(runtime.city);restored=CitySimulation(city)
        self.assertEqual({r.id:r.distance for r in restored.transit.engine.pedestrian_states()},before)
        self.assertEqual(set(runtime.residents),set(restored.residents))
        self.assertEqual(restored.households[h.id].moving_to,target.id)
        runtime.update(1100);restored.update(1100)
        self.assertEqual(restored.households[h.id].home,target.id)
        self.assertEqual(restored.report(),runtime.report())

    def test_active_bus_passengers_and_waiting_queues_restore(self):
        from city_simulation import CitySimulation
        runtime,home,target,*_=neighborhood()
        stops=[]
        for x in (200,3200):
            stop=placed(runtime.city,'bus_stop',x,50);stop.phase=BuildablePhase.OPERATIONAL;stops.append(stop.id)
        runtime.sync_buildings();line=runtime.create_line(stops)
        h=runtime.invite_household(home.id,4)
        # Force the long trip; the planner should use the newly authored line.
        runtime.relocate(h.id,target.id);runtime.update(30)
        self.assertTrue(any(b.passengers for b in runtime.transit.buses.values()))
        snapshot=runtime.snapshot()
        json.dumps(snapshot,allow_nan=False)
        restored=CitySimulation(roundtrip(runtime.city))
        self.assertEqual([b.passengers for b in runtime.transit.buses.values()],
                         [b.passengers for b in restored.transit.buses.values()])
        self.assertEqual({k:list(q) for k,q in runtime.transit.queues.items()},
                         {k:list(q) for k,q in restored.transit.queues.items()})
        restored.update(1200)
        self.assertEqual(restored.households[h.id].home,target.id)
        self.assertTrue(all(b.capacity==60 for b in restored.transit.buses.values()))

    def test_road_edit_retains_household_and_car_while_rerouting(self):
        runtime,home,target,*_=neighborhood()
        h=runtime.invite_household(home.id,3,car=True)
        runtime.relocate(h.id,target.id);runtime.update(10)
        carid=runtime.residents[h.members[0]].car_id
        runtime.city.add_road([(1800,30),(1800,1200)])
        runtime.sync_network();runtime.update(1200)
        self.assertEqual(h.home,target.id)
        self.assertEqual(runtime.fleet.vehicles[carid].site,target.id)
        self.assertEqual(len(runtime.residents),3)

    def test_saved_invalid_membership_is_rejected(self):
        from city_simulation import CitySimulation
        runtime,home,*_=neighborhood();runtime.invite_household(home.id,2)
        city=roundtrip(runtime.city)
        city.gameplay_state['households'][0]['members'].append(9999)
        with self.assertRaises(ValueError):CitySimulation(city)


class GameplayLifecycleTests(unittest.TestCase):
    def test_occupied_households_drive_food_demand_and_import_ledger(self):
        runtime,home,target,*_=neighborhood()
        runtime.invite_household(home.id,2)
        runtime.import_resources(home.id,'food',20)
        runtime.update(3600)
        self.assertAlmostEqual(runtime.consumed,2*3/24)
        self.assertAlmostEqual(runtime.report()['resource_balance_error'],0,places=7)
        self.assertEqual(target.inventory.amounts.get('food',0),0)

    def test_cafe_gets_scheduled_customers_in_the_authored_city(self):
        runtime,home,target,cafe,*_=neighborhood()
        h=runtime.invite_household(target.id,4)
        runtime.residents[h.members[0]].workplace=cafe.id
        runtime.import_resources(cafe.id,'food',100)
        runtime.update(13*3600)
        self.assertGreater(runtime.meals_served,0)

    def test_closed_workplace_returns_workers_and_stops_production(self):
        runtime,home,target,cafe,bakery,*_=neighborhood()
        h=runtime.invite_household(target.id,2)
        p=runtime.residents[h.members[0]];p.workplace=bakery.id
        runtime.import_resources(bakery.id,'grain',100)
        runtime.update(9*3600)
        self.assertEqual(p.state,'work')
        bakery.phase=BuildablePhase.DECOMMISSIONED;runtime.sync_buildings()
        before=runtime.produced
        runtime.update(3600)
        self.assertEqual(p.state,'home')
        self.assertEqual(runtime.produced,before)

    def test_clear_debug_traffic_retains_logical_active_household(self):
        runtime,home,target,*_=neighborhood()
        h=runtime.invite_household(home.id,2,car=True)
        runtime.relocate(h.id,target.id);runtime.update(5)
        runtime.transit.traffic.clear_vehicles()
        runtime.sync_network();runtime.update(1200)
        self.assertEqual(h.home,target.id)
        self.assertEqual(len(runtime.fleet.vehicles),1)

    def test_each_authored_clinic_serves_its_own_queue(self):
        runtime,home,target,*_=neighborhood()
        clinics=[]
        for x in (3100,3350):
            c=placed(runtime.city,'clinic',x);c.phase=BuildablePhase.OPERATIONAL;clinics.append(c)
        runtime.sync_buildings();h=runtime.invite_household(target.id,4)
        for i,c in enumerate(clinics):
            p=runtime.residents[h.members[i]];p.workplace=c.id;p.state='work'
            runtime.import_resources(c.id,'medicine',1)
            runtime.request_visit(h.members[2+i],c.id,'care')
        runtime.update(500)
        self.assertEqual(runtime.treated,2)
        self.assertEqual(runtime.medical_sinks,2)

    def test_production_never_counts_time_before_first_worker_arrival(self):
        runtime,home,_,_,bakery,*_=neighborhood()
        h=runtime.invite_household(home.id,1)
        p=runtime.residents[h.members[0]];p.workplace=bakery.id
        runtime.import_resources(bakery.id,'grain',100)
        runtime.update(27900)
        arrival=next(e['time'] for e in runtime.events if e['event']=='worker_arrived')
        self.assertLessEqual(runtime.produced,6*(runtime.time-arrival)/3600+1e-8)

    def test_imported_vehicles_begin_with_zero_fuel_consumption(self):
        runtime,home,_,cafe,*_=neighborhood()
        runtime.invite_household(home.id,2,car=True)
        runtime.commission_truck(cafe.id)
        self.assertEqual(runtime.report()['fuel_used_liters'],0)

    def test_recipe_conversion_is_accounted_separately_from_construction(self):
        runtime,home,target,cafe,bakery,*_=neighborhood()
        h=runtime.invite_household(target.id,1)
        p=runtime.residents[h.members[0]];p.workplace=bakery.id;p.state='work'
        bakery.operation['inputs']={'grain':2};runtime.sync_buildings()
        runtime.import_resources(bakery.id,'grain',20)
        runtime.import_resources(home.id,'food',10)
        home.inventory.amounts['lumber']=20  # Construction's separate ledger.
        runtime.update(600)
        self.assertGreater(runtime.produced,0)
        self.assertAlmostEqual(runtime.report()['resource_balance_error'],0,places=7)

    def test_active_walking_does_not_copy_population_into_python_every_tick(self):
        from unittest.mock import patch
        runtime,home,target,*_=neighborhood()
        h=runtime.invite_household(home.id,2)
        runtime.relocate(h.id,target.id);runtime.update(0)
        with patch.object(runtime.transit.engine,'pedestrian_states',side_effect=AssertionError('per-tick population copy')):
            runtime.update(1)
        self.assertEqual(len(runtime.transit.engine.pedestrian_states()),2)
