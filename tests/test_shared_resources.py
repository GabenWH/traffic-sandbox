import unittest
from models import ResourceInventory


class SharedResourceTests(unittest.TestCase):
    def test_transfer_moves_only_available_stock(self):
        source = ResourceInventory({'food': 3})
        destination = ResourceInventory()
        self.assertEqual(source.transfer_to(destination, 'food', 5), 3)
        self.assertEqual(destination.amounts, {'food': 3})
        self.assertEqual(source.amounts.get('food', 0), 0)

    def test_recipe_limits_all_inputs_before_consuming(self):
        inventory = ResourceInventory({'grain': 10, 'water': 2})
        self.assertEqual(inventory.produce({'grain': 2, 'water': 1}, {'food': 3}, 5), 2)
        self.assertEqual(inventory.amounts.get('grain'), 6)
        self.assertEqual(inventory.amounts.get('food'), 6)
        self.assertEqual(inventory.produce({'water': 1}, {'food': 3}, 1), 0)

    def test_inbound_is_not_ordered_again(self):
        inventory = ResourceInventory({'food': 2})
        self.assertEqual(inventory.shortage('food', 10, incoming=7), 1)
        self.assertEqual(inventory.shortage('food', 10, incoming=20), 0)

    def test_invalid_recipe_is_atomic(self):
        inventory = ResourceInventory({'grain': 10})
        with self.assertRaises(ValueError):
            inventory.produce({'grain': 1}, {'food': float('nan')}, 1)
        self.assertEqual(inventory.amounts, {'grain': 10})

    def test_construction_and_consumer_loads_share_physical_limits(self):
        from resources import ResourceSpec, TruckSpec, material_load
        resource=ResourceSpec('stone','Stone','t',1000,.5)
        truck=TruckSpec('small',1500,1,0,15,6)
        self.assertEqual(material_load(resource,truck,requested=10,available=20),1.5)
        self.assertEqual(material_load(resource,truck,requested=10,available=.4),.4)
