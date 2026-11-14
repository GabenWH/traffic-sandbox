import unittest
from types import SimpleNamespace

from town_services import ServiceTown
from test_city_gameplay import neighborhood, roundtrip
from city_simulation import CitySimulation


class IncomingTotalsTests(unittest.TestCase):
    def test_totals_match_live_queries_for_stages_resources_and_visit_states(self):
        town = ServiceTown.__new__(ServiceTown)
        town.jobs = {
            i: dict(destination='a' if i % 2 else 'b', resource='grain' if i % 3 else 'food',
                    amount=value, stage=stage)
            for i, (stage, value) in enumerate(zip(
                ('to_source', 'loading', 'outbound', 'unloading', 'return', 'outbound'),
                (1e16, 1., 1., 0.1, 20., 0.2)))
        }
        town.visits = {
            1: dict(purpose='shopping', origin='a', resource='food', amount=2.9, picked_up=False),
            2: dict(purpose='shopping', origin='b', resource='grain', amount=1.2, picked_up=True),
            3: dict(purpose='shopping', origin='a', resource='food', amount=0.1, cancelled=True),
            4: dict(purpose='meal', origin='a'),
        }
        totals = town._incoming_totals()
        for site in ('a', 'b', 'missing'):
            for resource in ('food', 'grain', 'medicine'):
                self.assertEqual(totals.get((site, resource), 0), town.incoming(site, resource))
        town.visits.clear()
        town.jobs[0]['stage'] = 'return'
        updated = town._incoming_totals()
        self.assertEqual(updated.get(('a', 'food'), 0), town.incoming('a', 'food'))

    def test_grouping_preserves_compensated_float_sums(self):
        town=ServiceTown.__new__(ServiceTown)
        town.jobs={i:dict(destination='a',resource='food',amount=value,stage='outbound')
                   for i,value in enumerate((1e16,1.,1.))}
        town.visits={i:dict(origin='a',resource='food',purpose='shopping',amount=value)
                     for i,value in enumerate((0.1,0.2,0.3))}
        self.assertEqual(town._incoming_totals()['a','food'],town.incoming('a','food'))

    def test_request_pass_does_not_scan_jobs_and_visits_per_site(self):
        town = ServiceTown.__new__(ServiceTown)
        town.jobs = {}
        town.visits = {}
        town.bay_active = {}
        town.handling = {}
        town.fleet = SimpleNamespace(vehicles={})
        town.businesses = {}
        town._choose_shoppers = lambda: None
        town.sites = {str(i): dict(building=SimpleNamespace(inventory=SimpleNamespace(
            amounts={'food': 10}, shortage=lambda *args: 0))) for i in range(100)}
        town._resident_count = lambda sid: 1
        def unexpected(*args):
            self.fail('per-site incoming scan')
        town.incoming = unexpected
        town._logistics()
        self.assertEqual(town.requests, [])

    def test_shared_home_shopping_reservation_is_live_and_roundtrips(self):
        runtime, home, target, cafe, bakery, market = neighborhood()
        self.addCleanup(runtime.close)
        runtime.invite_household(home.id, 1)
        runtime.invite_household(home.id, 1)
        runtime.import_resources(market.id, 'food', 20)
        runtime._choose_shoppers()
        self.assertEqual(runtime.incoming(home.id, 'food'), 3)
        self.assertEqual(len(runtime.visits), 1)
        restored = CitySimulation(roundtrip(runtime.city))
        self.addCleanup(restored.close)
        self.assertEqual(runtime._incoming_totals(), restored._incoming_totals())
        runtime._logistics()
        restored._logistics()
        self.assertEqual(runtime.requests, restored.requests)
        self.assertEqual(runtime.incoming(home.id, 'food'), 3)


if __name__ == '__main__':
    unittest.main()
