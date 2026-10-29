import unittest
from math import exp


class MemoryTests(unittest.TestCase):
    def test_buffer_changes_over_years_and_query_is_lazy(self):
        from households import HousingMemory, YEAR
        memory = HousingMemory(buffer=60, target=10)
        self.assertAlmostEqual(memory.value_at(2*YEAR), 10+50/exp(1))
        self.assertEqual(memory.updated_at, 0)
        self.assertGreater(memory.value_at(1), 59.999)
        memory.observe(100, 2*YEAR)
        low = memory.buffer
        self.assertGreater(memory.value_at(4*YEAR), low)

    def test_time_must_be_monotonic_and_finite(self):
        from households import HousingMemory
        memory=HousingMemory(updated_at=5)
        for time in (4,float('nan'),float('inf')):
            with self.assertRaises(ValueError): memory.value_at(time)
