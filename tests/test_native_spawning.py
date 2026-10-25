"""Real native spawning is compared to the independent Python baseline."""
import random
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from city import CityMap, Terrain
from traffic_testbed import RoadVehicleSimulation, RoutedRoadVehicle


class NativeSpawningTests(unittest.TestCase):
    def test_cpp_random_draws_and_full_state_match_python(self):
        root = Path(__file__).resolve().parents[1]
        rng = random.Random(42)
        rng.random()  # Import partway through a state block.
        initial = rng.getstate()[1]
        sizes = [1, 2, 3, 5, 8, 17, 1000, 2147483649] * 100
        draws = [(n, rng._randbelow(n)) for n in sizes]
        payload = ' '.join(map(str, initial)) + '\n' + str(len(draws)) + '\n'
        payload += '\n'.join(f'{n} {v}' for n, v in draws)
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / 'test-spawning')
            build = subprocess.run(['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                    str(root / 'native/traffic/test_spawning.cpp'),
                                    str(root / 'native/traffic/engine.cpp'), '-o', executable],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([executable], input=payload, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(tuple(map(int, result.stdout.split())), rng.getstate()[1])

    def pair(self, cap=60, interval=1.0):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (500, 100)])
        city.add_road([(250, -150), (250, 100)])
        reference = RoadVehicleSimulation(update_mode='data_first', rng=random.Random(42),
                                          max_cars=cap, spawn_interval=interval)
        try:
            native = RoadVehicleSimulation(update_mode='native', rng=random.Random(42),
                                           max_cars=cap, spawn_interval=interval)
        except ValueError as exc:
            self.fail('Native spawning mode is missing: ' + str(exc))
        for sim in (reference, native):
            for i, j in enumerate(city.cul_de_sacs):
                sim.toggle_junction(j)
                sim._spawn_elapsed[j.id] = i * interval / len(city.cul_de_sacs)
        return city, reference, native

    def compare(self, reference, native, done_a=(), done_b=()):
        a = {c.id: c for c in (*reference.cars, *done_a)}
        b = {c.id: c for c in (*native.cars, *done_b)}
        self.assertEqual(set(a), set(b))
        self.assertEqual(reference.rng.getstate(), native.rng.getstate())
        self.assertEqual(reference._spawn_elapsed, native._spawn_elapsed)
        self.assertEqual(reference._spawned_count, native._spawned_count)
        for key, x in a.items():
            y = b[key]
            self.assertEqual((x.source_id, x.destination_id, x.color, x.brain.merge_style),
                             (y.source_id, y.destination_id, y.color, y.brain.merge_style))
            self.assertEqual(x.route.edges, y.route.edges)
            self.assertAlmostEqual(x.route.cost, y.route.cost, delta=1e-7)
            for attr in ('distance', 'speed', 'total_length'):
                self.assertAlmostEqual(getattr(x, attr), getattr(y, attr), delta=1e-7, msg=(key, attr))
            for attr in ('position', 'heading'):
                for left, right in zip(getattr(x, attr), getattr(y, attr)):
                    self.assertAlmostEqual(left, right, delta=1e-7, msg=(key, attr))
            for attr in ('state', 'signal_intent', 'wait_reason', 'phantom_target'):
                self.assertEqual(getattr(x.brain, attr), getattr(y.brain, attr), (key, attr))
            for attr in ('desired_speed', 'stopped_elapsed'):
                self.assertAlmostEqual(getattr(x.brain, attr), getattr(y.brain, attr), delta=1e-7)
            self.assertEqual(getattr(x.claimed_movement, 'id', None),
                             getattr(y.claimed_movement, 'id', None))

    def test_independent_spawning_matches_every_tick(self):
        city, reference, native = self.pair()
        for _ in range(600):
            self.compare(reference, native, reference.update(city, .05), native.update(city, .05))
        self.assertGreater(native._spawned_count, 10)

    def test_cap_preserves_rng_and_retries_after_space_clears(self):
        city, reference, native = self.pair(cap=1, interval=.05)
        for tick in range(100):
            if tick == 40:
                for sim in (reference, native):
                    sim.remove_vehicle(sim.cars[0].id)
            self.compare(reference, native, reference.update(city, .05), native.update(city, .05))

    def test_native_update_calls_no_python_spawning_routing_or_driving(self):
        from car_brain import CarBrain
        city, _, native = self.pair()
        with patch.object(CityMap, 'find_vehicle_route_between', side_effect=AssertionError('Python routing')), \
             patch.object(RoadVehicleSimulation, 'spawn_car', side_effect=AssertionError('Python spawning')), \
             patch.object(RoadVehicleSimulation, 'admit_route', side_effect=AssertionError('Python admission')), \
             patch.object(native.rng, 'shuffle', side_effect=AssertionError('Python shuffle')), \
             patch.object(native.rng, 'choice', side_effect=AssertionError('Python choice')), \
             patch('pathfinding.astar', side_effect=AssertionError('Python A*')), \
             patch('traffic_testbed.vehicle_footprints_overlap', side_effect=AssertionError('Python footprint check')), \
             patch('traffic_occupancy.TrafficOccupancyIndex.lead_gap', side_effect=AssertionError('Python clearance')), \
             patch.object(CarBrain, 'decide', side_effect=AssertionError('Python decisions')), \
             patch.object(RoutedRoadVehicle, 'advance', side_effect=AssertionError('Python movement')):
            for _ in range(100):
                native.update(city, .05)
        self.assertGreater(len(native.cars), 1)
        self.assertTrue(any(c.distance > 1 for c in native.cars))

    def test_comparison_rejects_corrupted_native_output(self):
        city, reference, native = self.pair()
        for _ in range(20):
            reference.update(city, .05)
            native.update(city, .05)
        car = native.cars[0]
        native._native_controller.engine.place(car.id, car.distance + 1)
        reference.update(city, 0)
        native.update(city, 0)
        with self.assertRaises(AssertionError):
            self.compare(reference, native)

    def test_sources_caps_and_mutations_preserve_parity(self):
        city, reference, native = self.pair(cap=8, interval=.2)
        for tick in range(180):
            for sim in (reference, native):
                if tick == 30:
                    sim.toggle_junction(city.cul_de_sacs[0])
                    sim.max_cars = 2
                if tick == 40:
                    sim.toggle_junction(city.cul_de_sacs[0])
                    sim.max_cars = 10
                    sim.speed_mph = 18
                if tick == 45 and sim.cars:
                    sim.place_vehicle(sim.cars[0].id, 10)
                    sim.resize_vehicle(sim.cars[0].id, length=32, width=9)
                if tick == 60 and sim.cars:
                    car = sim.cars[0]
                    sim.replace_vehicle_route(car.id, car.route, distance=20)
                if tick == 70:
                    sim.reorder_vehicles([c.id for c in reversed(sim.cars)])
                if tick == 80:
                    sim.clear_test_traffic()
                if tick == 90:
                    for j in city.cul_de_sacs:
                        sim.toggle_junction(j)
            if tick == 100:
                city.rebuild_mobility_network()
            dt = .2 if tick == 130 else 0 if tick == 131 else .05
            self.compare(reference, native, reference.update(city, dt), native.update(city, dt))

    def test_external_traffic_blocks_spawn_without_using_capacity(self):
        city, reference, native = self.pair(cap=1, interval=.05)
        source, destination = city.cul_de_sacs[:2]
        route = city.find_vehicle_route_between(source, destination)
        for sim in (reference, native):
            truck = sim.admit_route(route, vehicle_id='delivery', source_id=source.id,
                                   destination_id=destination.id, length=40, width=10)
            self.assertIsNotNone(truck)
        for _ in range(120):
            self.compare(reference, native, reference.update(city, .05), native.update(city, .05))
        self.assertGreater(native._spawned_count, 0)

    def test_native_routes_precise_lane_endpoints(self):
        from mobility import lane_position_at_distance
        city, _, native = self.pair()
        backend = native._native_backend(city)
        self.assertTrue(hasattr(backend, 'find_route'), 'Native precise-endpoint routing is missing')
        lane = city.roads[0].lanes[0]
        start, end = lane_position_at_distance(lane, 30), lane_position_at_distance(lane, 90)
        for source, destination in ((start, end), (start, city.cul_de_sacs[1]),
                                    (city.cul_de_sacs[0], end), (start, start)):
            expected = city.find_vehicle_route_between(source, destination)
            actual = backend.find_route(source, destination)
            self.assertEqual(actual is None, expected is None)
            if actual is not None:
                self.assertAlmostEqual(actual.cost, expected.cost, delta=1e-7)
                from mobility import vehicle_route_points
                self.assertEqual(vehicle_route_points(actual), vehicle_route_points(expected))

    def test_compiled_route_ranges_match_canonical_python_geometry(self):
        import json
        from persistence import world_from_dict
        from traffic_testbed import _controlled_movement_ranges, _route_occupancy_segments
        from native_traffic import _Section, _Movement
        for filename in ('slip_lanes.json', 'roundabout_test.json'):
            city = world_from_dict(json.loads((Path(__file__).parent / 'fixtures' / filename).read_text())).city_map
            native = RoadVehicleSimulation(update_mode='native')
            backend = native._native_backend(city)
            lib, ptr = backend.engine._lib, backend.engine._ptr
            self.assertTrue(hasattr(lib, 'nt_route_sections'), 'Native route metadata view is missing')
            import ctypes as C
            for source in city.cul_de_sacs:
                for destination in city.cul_de_sacs:
                    if source is destination:
                        continue
                    route_id = backend.engine._call('nt_find_route', backend.endpoint_ids[id(source)], backend.endpoint_ids[id(destination)]) - 1
                    if route_id < 0:
                        continue
                    route = backend.path(route_id, source, destination)
                    count = C.c_int()
                    sections = lib.nt_route_sections(ptr, route_id, C.byref(count))
                    actual = [(sections[i].start, sections[i].end, sections[i].offset) for i in range(count.value)]
                    expected = [(start, end, offset) for start, end, _, offset in _route_occupancy_segments(route)]
                    self.assertEqual(actual, expected, filename)
                    movements = lib.nt_route_movements(ptr, route_id, C.byref(count))
                    self.assertEqual([(movements[i].start, movements[i].end) for i in range(count.value)],
                                     [(start, end) for start, end, _ in _controlled_movement_ranges(route)], filename)
            native._discard_native()

    def test_native_debugger_receives_native_results(self):
        from traffic_debugger import TrafficDebugger
        city, _, native = self.pair()
        native.debugger = TrafficDebugger()
        for _ in range(30):
            native.update(city, .05)
        frame = native.debugger.latest_frame
        self.assertIsNotNone(frame, 'Native updates must publish debugger frames')
        self.assertEqual(frame.index, 30)
        self.assertEqual({c.car_id for c in frame.cars}, {c.id for c in native.cars})
        self.assertTrue(all(c.distance_after >= c.distance_before for c in frame.cars))
        self.assertIn('native_movement', frame.timings_ms)

    def test_review_mode_switch_direct_admissions_reimport_native_state(self):
        for generated in (True, False):
            with self.subTest(generated=generated):
                city, reference, native = self.pair()
                reference.update(city, 0)
                native.update(city, 0)
                source, destination = city.cul_de_sacs[:2]
                native.update_mode = 'data_first'
                for sim in (reference, native):
                    if generated:
                        sim.spawn_car(city, source, destination)
                    else:
                        sim.admit_route(city.find_vehicle_route_between(source, destination), vehicle_id='delivery',
                                        source_id=source.id, destination_id=destination.id)
                native.update_mode = 'native'
                self.compare(reference, native, reference.update(city, .05), native.update(city, .05))
                self.assertIsNotNone(native.remove_vehicle(native.cars[0].id))

    def test_review_invalid_lane_graph_is_rejected_before_publication(self):
        import ctypes as C
        from native_traffic import NativeTrafficEngine, _Point
        from native_spawning import Edge, Endpoint
        with NativeTrafficEngine() as engine:
            nodes = (_Point * 2)(_Point(0, 0), _Point(10, 0))
            edge = (Edge * 1)(Edge(0, 1, 0, 0, 0, 1, -1, -1, 10, 0, 0, 10))
            with self.assertRaises(ValueError):
                engine._call('nt_graph', nodes, 2, edge, 1, (_Point * 0)(), 0,
                             (Endpoint * 0)(), 0, (C.c_int * 0)(), 0)

    def test_review_partial_lane_distance_uses_geometry_not_routing_cost(self):
        from dataclasses import replace
        from mobility import lane_position_at_distance, vehicle_route_points
        from models import polyline_length
        city, _, native = self.pair()
        graph = city.mobility.layers['vehicles'].graph
        for node in graph.nodes:
            graph._adjacency[node] = [replace(t, cost=t.cost / 2) if t.edge.kind == 'lane' else t
                                      for t in graph.transitions_from(node)]
        lane = city.roads[0].lanes[0]
        destination = max(city.cul_de_sacs, key=lambda j: j.position[0])
        backend = native._native_backend(city)
        for distance in (2, polyline_length(lane.points) * .75):
            source = lane_position_at_distance(lane, distance)
            expected = city.find_vehicle_route_between(source, destination)
            actual = backend.find_route(source, destination)
            self.assertIsNotNone(actual)
            self.assertAlmostEqual(actual.cost, expected.cost, delta=1e-7)
            self.assertEqual(vehicle_route_points(actual), vehicle_route_points(expected))

    def test_construction_truck_completes_with_shared_native_road_vehicles(self):
        from city import Building, Parcel
        from construction import ConstructionSimulation, UnlimitedConstructionProvider
        from models import BuildablePhase
        from resources import ResourceSpec, TruckSpec
        city = CityMap(width=600, height=300, terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (400, 100)])
        building = Building('Project', Parcel(120, 112, 50, 30), phase=BuildablePhase.UNDER_CONSTRUCTION,
                            construction_needs={'stone': 5})
        city.buildings.append(building)
        native = RoadVehicleSimulation(update_mode='native', spawn_interval=1000)
        construction = ConstructionSimulation({'stone': ResourceSpec('stone', 'Stone', 't', 500, 1)},
                                               {'material': TruckSpec('material', 2500, 10, 0, 18, 8)},
                                               UnlimitedConstructionProvider(), truck_speed=10,
                                               road_vehicles=native)
        construction.update(city, 0)
        truck = construction.trips[0].road_vehicle
        self.assertIs(truck, native.cars[0])
        self.assertEqual(truck.appearance.kind, 'construction_truck')
        completed = construction.update(city, 60)
        self.assertEqual(len(completed), 1)
        self.assertEqual(building.construction_delivered, {'stone': 5})
        self.assertEqual(list(native.cars), [])


if __name__ == '__main__':
    unittest.main()
