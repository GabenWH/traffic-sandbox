"""Focused checks for the opt-in resource economy prototype."""
import unittest

from resource_economy import EconomyError, ResourceEconomy, ResourceNode
from models import ResourceInventory


class ResourceEconomyTests(unittest.TestCase):
    def setUp(self):
        self.world = ResourceEconomy.load()
        self.world.add_node(ResourceNode('port', unlimited_imports=frozenset({
            'gravel', 'sand', 'cement', 'fuel', 'timber'})))
        self.world.add_node(ResourceNode('plant',
            inventory=ResourceInventory({'electricity': 100, 'potable_water': 10}),
            recipes=('concrete_batch',)))
        self.world.add_node(ResourceNode('house'))

    def test_import_port_is_unlimited_but_other_nodes_deplete(self):
        a = self.world.reserve_delivery('port','plant','gravel',30,max_payload_kg=7500,max_cargo_m3=10)
        b = self.world.reserve_delivery('port','plant','gravel',30,max_payload_kg=7500,max_cargo_m3=10)
        self.assertEqual(a.amount,7.5)
        self.assertEqual(b.amount,7.5)
        self.world.pickup(a.id); self.world.deliver(a.id)
        self.world.pickup(b.id); self.world.deliver(b.id)
        self.assertEqual(self.world.nodes['plant'].inventory.amounts['gravel'],15)
        c = self.world.reserve_delivery('plant','house','gravel',20,max_payload_kg=7500,max_cargo_m3=10)
        d = self.world.reserve_delivery('plant','house','gravel',20,max_payload_kg=7500,max_cargo_m3=10)
        e = self.world.reserve_delivery('plant','house','gravel',20,max_payload_kg=7500,max_cargo_m3=10)
        self.assertEqual((c.amount,d.amount),(7.5,7.5))
        self.assertIsNone(e)
        self.world.pickup(c.id); self.world.deliver(c.id)
        self.assertEqual(self.world.nodes['house'].inventory.amounts['gravel'],7.5)
        self.assertEqual(self.world.nodes['plant'].inventory.amounts['gravel'],7.5)

    def test_plant_consumes_multiple_inputs_creates_concrete_waste_and_pollution(self):
        self.world.nodes['plant'].inventory.add('gravel',2)
        self.world.nodes['plant'].inventory.add('sand',1)
        self.world.nodes['plant'].inventory.add('cement',1)
        self.assertTrue(self.world.process('plant','concrete_batch',batches=2))
        stock = self.world.nodes['plant'].inventory.amounts
        self.assertAlmostEqual(stock['concrete'],3.2)
        self.assertAlmostEqual(stock['construction_waste'],0.2)
        self.assertAlmostEqual(stock['wastewater'],0.1)
        self.assertAlmostEqual(self.world.emissions['air_pollution'],0.4)
        self.assertEqual(stock['electricity'],40)
        self.assertFalse(self.world.process('plant','concrete_batch',batches=1))

    def test_generator_recipe_can_create_material_without_inputs(self):
        self.world.add_node(ResourceNode('forest',recipes=('timber_growth',)))
        self.assertTrue(self.world.process('forest','timber_growth',3))
        self.assertEqual(self.world.nodes['forest'].inventory.amounts['timber'],3)

    def test_in_transit_does_not_arrive_until_callback(self):
        order = self.world.reserve_delivery('port','house','timber',3,max_payload_kg=2000,max_cargo_m3=10)
        self.world.pickup(order.id)
        self.assertNotIn('timber',self.world.nodes['house'].inventory.amounts)
        self.world.deliver(order.id)
        self.assertAlmostEqual(self.world.nodes['house'].inventory.amounts['timber'],2000/700)
        with self.assertRaises(EconomyError):
            self.world.deliver(order.id)

    def test_cancel_releases_reservation_and_restores_pickup_stock(self):
        self.world.nodes['plant'].inventory.add('lumber',10)
        a = self.world.reserve_delivery('plant','house','lumber',10,max_payload_kg=10000,max_cargo_m3=10)
        self.assertEqual(self.world.available('plant','lumber'),0)
        self.world.cancel(a.id)
        self.assertEqual(self.world.available('plant','lumber'),10)
        b = self.world.reserve_delivery('plant','house','lumber',10,max_payload_kg=10000,max_cargo_m3=10)
        self.world.pickup(b.id)
        self.assertNotIn('lumber',self.world.nodes['plant'].inventory.amounts)
        self.world.cancel(b.id)
        self.assertEqual(self.world.nodes['plant'].inventory.amounts['lumber'],10)

    def test_utilities_and_pollution_never_become_truck_cargo(self):
        for resource in ('electricity','potable_water','air_pollution'):
            with self.subTest(resource=resource), self.assertRaises(EconomyError):
                self.world.reserve_delivery('port','plant',resource,1,max_payload_kg=7500,max_cargo_m3=10)

    def test_missing_inputs_are_atomic_and_reserved_stock_cannot_be_consumed(self):
        self.world.nodes['plant'].inventory.add('gravel',1)
        self.world.nodes['plant'].inventory.add('sand',0.5)
        self.world.nodes['plant'].inventory.add('cement',0.3)
        order = self.world.reserve_delivery('plant','house','gravel',1,max_payload_kg=7500,max_cargo_m3=10)
        before = dict(self.world.nodes['plant'].inventory.amounts)
        self.assertFalse(self.world.process('plant','concrete_batch'))
        self.assertEqual(before,self.world.nodes['plant'].inventory.amounts)
        self.world.cancel(order.id)
        self.assertTrue(self.world.process('plant','concrete_batch'))


if __name__ == '__main__':
    unittest.main()
