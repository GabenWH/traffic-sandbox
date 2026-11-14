import unittest
from city_simulation import CitySimulation
from test_city_gameplay import neighborhood, roundtrip


class HouseholdBatchingTests(unittest.TestCase):
    def setUp(self):
        self.runtime, self.home, self.target, self.cafe, *_ = neighborhood()
        self.addCleanup(self.runtime.close)
        self.household = self.runtime.invite_household(self.home.id, 2)
        self.runtime.import_resources(self.home.id, 'food', 10)

    def settle(self, time):
        self.runtime.time = time
        self.runtime._settle_economy(time)

    def test_attendance_settlements_do_not_consume_households_between_minutes(self):
        self.settle(10)
        self.settle(20)
        self.assertEqual(self.home.inventory.amounts['food'], 10)
        self.runtime._run_event('economy', ['economy', None])
        self.assertAlmostEqual(self.home.inventory.amounts['food'], 10 - 2 * 3 * 20 / 86400)

    def test_midminute_food_import_does_not_feed_past_unmet_demand(self):
        self.home.inventory.amounts['food'] = 0
        self.settle(30)
        self.runtime.import_resources(self.home.id, 'food', 2)
        self.assertAlmostEqual(self.runtime.unmet, 2 * 3 * 30 / 86400)
        self.assertEqual(self.home.inventory.amounts['food'], 2)
        self.runtime.time = 60
        self.runtime._run_event('economy', ['economy', None])
        self.assertAlmostEqual(self.home.inventory.amounts['food'], 2 - 2 * 3 * 30 / 86400)

    def test_shopping_receipt_consumes_old_stock_before_receipt(self):
        p = self.runtime.residents[self.household.members[0]]
        p.state = 'visiting_return'
        self.runtime.visits[p.id] = dict(site=self.cafe.id, purpose='shopping', origin=self.home.id,
                                         previous='home', resource='food', amount=3)
        self.runtime.time = 30
        self.runtime._arrive_person(p)
        self.assertAlmostEqual(self.home.inventory.amounts['food'], 13 - 2 * 3 * 30 / 86400)

    def test_direct_shopping_uses_current_household_balance(self):
        market=next(b.site for b in self.runtime.businesses.values() if b.kind=='market')
        self.runtime.import_resources(market,'food',20)
        self.home.inventory.amounts['food']=0.001
        self.settle(30)
        self.assertTrue(self.runtime.request_shopping(self.household.members[0],market))
        self.assertEqual(self.runtime.incoming(self.home.id,'food'),3)
        self.assertEqual(self.home.inventory.amounts.get('food',0),0)

    def test_direct_unloading_does_not_feed_past_unmet_demand(self):
        from persistent_fleet import FleetVehicle
        self.home.inventory.amounts['food']=0
        truck=FleetVehicle('test-unloading','truck',self.home.id,cargo={'food':3})
        self.runtime.fleet.add(truck)
        self.runtime.jobs[truck.id]=dict(source=self.home.id,destination=self.home.id,
            resource='food',amount=3,reserved=0,stage='unloading')
        self.runtime.bay_active[self.home.id]=(truck.id,30,'unload')
        self.runtime.time=30
        self.runtime._logistics()
        self.assertEqual(self.home.inventory.amounts['food'],3)
        self.assertAlmostEqual(self.runtime.unmet,2*3*30/86400)

    def test_meal_credit_is_applied_only_after_meal_time(self):
        worker = self.runtime.residents[self.household.members[0]]
        customer = self.runtime.residents[self.household.members[1]]
        worker.workplace = self.cafe.id
        worker.state = 'commuting'
        self.runtime._arrive_person(worker)
        self.runtime.import_resources(self.cafe.id, 'food', 2)
        customer.state = 'waiting_meal'
        self.runtime.visits[customer.id] = dict(site=self.cafe.id, purpose='meal', origin=self.home.id, previous='home')
        self.runtime.meal_queues[self.cafe.id].append(customer.id)
        self.runtime.meal_capacity[self.cafe.id] = 1
        self.settle(30)
        self.assertAlmostEqual(self.home.inventory.amounts['food'], 10 - 2 * 3 * 30 / 86400)
        self.assertEqual(self.runtime.meal_credit[self.home.id], 1)
        self.runtime.time = 60
        self.runtime._run_event('economy', ['economy', None])
        self.assertAlmostEqual(self.runtime.meal_credit[self.home.id], 1 - 2 * 3 * 30 / 86400)

    def test_new_household_is_not_charged_for_time_before_invitation(self):
        self.settle(30)
        self.runtime.invite_household(self.target.id, 1)
        self.assertAlmostEqual(self.runtime.consumed, 2 * 3 * 30 / 86400)
        self.assertEqual(self.runtime.unmet, 0)

    def test_save_midminute_and_legacy_save_continue_without_double_consumption(self):
        self.runtime.update(30)
        self.runtime._settle_economy(self.runtime.time)
        saved = roundtrip(self.runtime.city)
        restored = CitySimulation(saved)
        self.addCleanup(restored.close)
        self.runtime.update(30)
        restored.update(30)
        self.assertEqual(self.runtime.report(), restored.report())
        self.assertAlmostEqual(restored.consumed, 2 * 3 * 60 / 86400)
        legacy = roundtrip(self.runtime.city)
        legacy.gameplay_state.pop('last_household_economy', None)
        old = CitySimulation(legacy)
        self.addCleanup(old.close)
        old.update(60)
        self.assertAlmostEqual(old.consumed, 2 * 3 * 120 / 86400)

    def test_legacy_save_preserves_unsettled_midminute_interval(self):
        self.runtime.update(30)
        legacy=roundtrip(self.runtime.city)
        data=legacy.gameplay_state
        data.pop('last_household_economy')
        data['last_economy']=20
        # Represent a real old save: stock/metrics settled at t=20, clock t=30.
        delta=2*3*10/86400
        data['metrics']['consumed']-=delta
        next(b for b in legacy.buildings if b.id==self.home.id).inventory.amounts['food']+=delta
        restored=CitySimulation(legacy)
        self.addCleanup(restored.close)
        restored.update(30)
        self.assertAlmostEqual(restored.consumed,2*3*60/86400)
        self.assertAlmostEqual(restored.sites[self.home.id]['building'].inventory.amounts['food'],10-2*3*60/86400)

    def test_invalid_household_save_clock_is_rejected(self):
        self.runtime.update(30)
        for clock in (float('nan'),float('inf'),-1,31,True):
            with self.subTest(clock=clock):
                saved=roundtrip(self.runtime.city)
                saved.gameplay_state['last_household_economy']=clock
                with self.assertRaises(ValueError):
                    CitySimulation(saved)


if __name__ == '__main__':
    unittest.main()
