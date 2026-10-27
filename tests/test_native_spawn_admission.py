"""Run the Python admission regression scenarios through real C++ admission."""
import test_spawn_admission as reference_cases


class NativeSpawnAdmissionTests(reference_cases.SpawnAdmissionTests):
    def setUp(self):
        super().setUp()
        self.traffic.update_mode = 'cpp'

    def test_blocked_retries_reuse_route_until_network_changes(self):
        first = self.traffic.spawn_car(self.city, self.west, self.east)
        backend = self.traffic._native_controller
        source, destination = (backend.endpoint_ids[id(j)] for j in (self.west, self.east))
        route = backend.engine._call('nt_find_route', source, destination)
        for _ in range(4):
            self.assertIsNone(self.traffic.spawn_car(self.city, self.west, self.east))
            self.assertEqual(backend.engine._call('nt_find_route', source, destination), route)
        self.city.rebuild_mobility_network()
        replacement = self.traffic.spawn_car(self.city, self.west, self.east)
        self.assertIsNotNone(replacement)
        self.assertIsNot(replacement.route, first.route)
        self.assertEqual(list(self.traffic.cars), [replacement])

    def test_direct_admission_publishes_pending_placement_to_python_occupancy(self):
        first = self.traffic.spawn_car(self.city, self.west, self.east)
        first.distance = 60
        first.advance(0)
        second = self.traffic.spawn_car(self.city, self.west, self.east)
        self.assertIsNotNone(second)
        self.assertEqual(self.traffic.occupancy.lead_gap(second, 100), 46)
