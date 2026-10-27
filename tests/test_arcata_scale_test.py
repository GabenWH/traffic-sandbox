import unittest

from tools.run_arcata_scale_test import cap_for_staged_run


class ArcataScaleTestTests(unittest.TestCase):
    def test_staged_cap_changes_at_equal_simulated_time_boundaries(self):
        caps = (100, 200)

        self.assertEqual(cap_for_staged_run(0.0, 300.0, caps), 100)
        self.assertEqual(cap_for_staged_run(149.95, 300.0, caps), 100)
        self.assertEqual(cap_for_staged_run(150.0, 300.0, caps), 200)
        self.assertEqual(cap_for_staged_run(300.0, 300.0, caps), 200)


if __name__ == "__main__":
    unittest.main()
