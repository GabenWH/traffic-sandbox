"""Behavior examples for connected lanes and the new junction rules."""
import unittest
from types import SimpleNamespace

from city import CityMap, Terrain
from models import IntersectionKind, ManeuverType
from persistence import world_to_dict, world_from_dict
from traffic_occupancy import TrafficOccupancyIndex
from traffic_testbed import TestTrafficSimulation
from intersection_controls import AllWayStopCoordinator


def cross_city():
    city = CityMap(terrain=Terrain(trees=[]))
    city.add_road([(0, 300), (600, 300)])
    city.add_road([(300, 0), (300, 600)])
    return city


class ConnectedTrafficTests(unittest.TestCase):
    def test_following_sees_car_after_lane_boundary(self):
        # Two cars use different link keys, but the follower's route joins them.
        follower = SimpleNamespace(id='f', length=14, distance=90,
            route_segments=((0, 100, ('lane', 'a'), 0), (100, 200, ('lane', 'b'), 0)))
        leader = SimpleNamespace(id='l', length=14, distance=110,
            route_segments=follower.route_segments)
        follower.occupancy_position = lambda: (('lane', 'a'), 90)
        leader.occupancy_position = lambda: (('lane', 'b'), 10)
        index = TrafficOccupancyIndex()
        index.rebuild([follower, leader])
        self.assertEqual(index.lead_gap(follower, 100), 6)

    def test_uncontrolled_car_can_request_entry_without_stopping(self):
        city = cross_city()
        connection = city.standard_intersections[0].lane_connections[0]
        coordinator = AllWayStopCoordinator()
        self.assertTrue(hasattr(coordinator, 'observe_approach'),
                        'Uncontrolled cars need arrival registration without a full stop')
        coordinator.observe_approach('car', connection, 1.0)
        self.assertTrue(coordinator.can_claim('car', connection))

    def test_roundabout_routes_share_ring_lanes_and_survive_save(self):
        city = cross_city()
        junction = city.standard_intersections[0]
        self.assertIn('roundabout', [kind.value for kind in IntersectionKind])
        junction.kind = IntersectionKind('roundabout')
        city.rebuild_mobility_network()
        west = next(j for j in city.cul_de_sacs if j.position == (0, 300))
        east = next(j for j in city.cul_de_sacs if j.position == (600, 300))
        north = next(j for j in city.cul_de_sacs if j.position == (300, 0))
        traffic = TestTrafficSimulation()
        a = traffic.spawn_car(city, west, east)
        self.assertIsNotNone(a)
        traffic.clear_cars()
        b = traffic.spawn_car(city, west, north)
        self.assertIsNotNone(b)
        ring_a = {s[2] for s in a.route_segments if 'roundabout' in str(s[2])}
        ring_b = {s[2] for s in b.route_segments if 'roundabout' in str(s[2])}
        self.assertTrue(ring_a & ring_b, 'Different destinations must share physical ring lanes')
        loaded = world_from_dict(world_to_dict(city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1)).city_map
        restored = next(j for j in loaded.intersections if j.id == junction.id)
        self.assertEqual(restored.kind.value, 'roundabout')
        self.assertTrue(loaded.find_vehicle_route_between(
            next(j for j in loaded.cul_de_sacs if j.id == west.id),
            next(j for j in loaded.cul_de_sacs if j.id == east.id)))

    def test_uncontrolled_cross_traffic_yields_and_both_finish(self):
        from math import dist
        city = cross_city()
        endpoints = {j.position: j for j in city.cul_de_sacs}
        traffic = TestTrafficSimulation(spawn_interval=1000)
        a = traffic.spawn_car(city, endpoints[(0, 300)], endpoints[(600, 300)])
        b = traffic.spawn_car(city, endpoints[(300, 0)], endpoints[(300, 600)])
        minimum = 1000
        waited = False
        for _ in range(700):
            traffic.update(city, 0.05)
            if a in traffic.cars and b in traffic.cars:
                minimum = min(minimum, dist(a.position, b.position))
                waited |= bool(a.brain.wait_reason or b.brain.wait_reason)
        self.assertGreater(minimum, 14)
        self.assertTrue(waited)
        self.assertEqual(traffic.cars, [])

    def test_yield_brain_keeps_moving_when_entry_is_available(self):
        from car_brain import CarBrain, CarObservation
        self.assertIn('must_yield', CarObservation.__dataclass_fields__)
        decision = CarBrain().decide(CarObservation(cruise_speed=25, speed=20,
            distance_to_stop=10, must_yield=True, has_priority=True), 0.05)
        self.assertTrue(decision.request_claim)
        self.assertEqual(decision.desired_speed, 25)

    def test_merge_yields_to_car_approaching_on_previous_section(self):
        from merge_behavior import merge_has_gap
        target = ('lane', 'shared')
        connection = SimpleNamespace(merge_target=target)
        joining = SimpleNamespace(distance=80, speed=15, length=14)
        circulating = SimpleNamespace(distance=90, speed=20, length=14,
            controlled_movements=(), route_segments=(
                (0, 100, ('lane', 'previous'), 0), (100, 200, target, 0)))
        self.assertFalse(merge_has_gap(joining, (85, 105, connection), [joining, circulating]))
        circulating.distance = 0
        circulating.speed = 5
        self.assertTrue(merge_has_gap(joining, (85, 105, connection), [joining, circulating]))

    def test_opposing_straight_movements_can_share_uncontrolled_intersection(self):
        city = cross_city()
        junction = city.standard_intersections[0]
        movements = [m for m in junction.lane_connections if m.maneuver.kind is ManeuverType.THROUGH]
        first = movements[0]
        reverse = next(m for m in movements if m.source_output.road is first.destination_input.road)
        coordinator = AllWayStopCoordinator()
        coordinator.observe_approach('a', first, 0)
        self.assertTrue(coordinator.claim('a', first))
        coordinator.observe_approach('b', reverse, 1)
        self.assertTrue(coordinator.claim('b', reverse))

    def test_inspector_can_convert_roundabout_and_back(self):
        from ui_tools.tools.inspect_tool import inspection_rows
        city = cross_city()
        junction = city.standard_intersections[0]
        host = SimpleNamespace(city_map=city, unit_system='imperial',
                               test_traffic=TestTrafficSimulation())
        _, rows = inspection_rows(host, junction)
        row = next((r for r in rows if r.label == 'Junction type'), None)
        self.assertIsNotNone(row)
        row.apply('roundabout')
        self.assertEqual(junction.kind.value, 'roundabout')
        _, rows = inspection_rows(host, junction)
        next(r for r in rows if r.label == 'Junction type').apply('standard')
        self.assertEqual(junction.kind.value, 'standard')

    def test_roundabout_traffic_does_not_overlap_and_keeps_finishing(self):
        import random
        from math import dist
        city = cross_city()
        city.standard_intersections[0].kind = IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network()
        traffic = TestTrafficSimulation(spawn_interval=2.5, rng=random.Random(42))
        for junction in city.cul_de_sacs:
            traffic.toggle_junction(junction)
        finished = 0
        for tick in range(1600):
            finished += len(traffic.update(city, 0.05))
            for i, a in enumerate(traffic.cars):
                for b in traffic.cars[i+1:]:
                    if dist(a.position, b.position) < 20:
                        self.assertFalse(cars_overlap(a, b), f'Overlapping cars at tick {tick}')
        self.assertGreater(finished, 10)



    def test_blocked_exit_keeps_waiting_car_outside(self):
        city = cross_city()
        ends = {j.position: j for j in city.cul_de_sacs}
        traffic = TestTrafficSimulation()
        leader = traffic.spawn_car(city, ends[(0, 300)], ends[(600, 300)])
        end = leader.controlled_movements[0][1]
        leader.distance = end + 1
        leader.speed = 0
        leader.advance(0)
        follower = traffic.spawn_car(city, ends[(0, 300)], ends[(600, 300)])
        follower.distance = follower.controlled_movements[0][0] - follower.length/2 - 1
        follower.advance(0)
        traffic.update(city, 0)
        self.assertIsNone(follower.claimed_movement)
        self.assertEqual(follower.brain.wait_reason, 'waiting for room beyond the junction')

    def test_roundabout_slows_cars_and_signals_only_at_their_exit(self):
        from car_brain import SignalIntent
        city = cross_city()
        city.standard_intersections[0].kind = IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network()
        ends = {j.position: j for j in city.cul_de_sacs}
        traffic = TestTrafficSimulation()
        car = traffic.spawn_car(city, ends[(0, 300)], ends[(300, 0)])
        entry, exit = car.controlled_movements
        car.distance = entry[1] + 8
        car.advance(0)
        traffic.update(city, 0)
        self.assertLess(car.brain.desired_speed, 25)
        self.assertEqual(car.brain.signal_intent, SignalIntent.NONE)
        last_arc = [segment for segment in car.route_segments
                    if segment[2][0] == 'lane' and 'roundabout:' in segment[2][1]][-1]
        car.distance = last_arc[0] + 1
        car.advance(0)
        traffic.update(city, 0)
        self.assertEqual(car.brain.signal_intent, SignalIntent.RIGHT)

    def test_inspector_layout_changes_when_junction_kind_changes(self):
        from ui_tools.tools.inspect_tool import InspectTool
        host = SimpleNamespace()
        tool = InspectTool(host)
        tool.selected = cross_city().standard_intersections[0]
        before = tool._selection_key()
        tool.selected.kind = IntersectionKind.ROUNDABOUT
        self.assertNotEqual(tool._selection_key(), before)


class IntersectionTieTests(unittest.TestCase):
    def test_four_simultaneous_through_arrivals_do_not_deadlock(self):
        city = cross_city()
        movements = [m for m in city.standard_intersections[0].lane_connections
                     if m.maneuver.kind is ManeuverType.THROUGH]
        coordinator = AllWayStopCoordinator()
        for i, movement in enumerate(movements):
            coordinator.observe_approach(str(i), movement, 0)
        self.assertTrue(any(coordinator.can_claim(str(i), m) for i, m in enumerate(movements)))


def cars_overlap(a, b):
    """Compare the actual car rectangles; adjacent opposing lanes are safe."""
    for heading in (a.heading, b.heading):
        for axis in (heading, (-heading[1], heading[0])):
            separation = abs(sum((b.position[k]-a.position[k])*axis[k] for k in (0, 1)))
            def radius(car):
                along = abs(sum(car.heading[k]*axis[k] for k in (0, 1)))
                across = abs(-car.heading[1]*axis[0] + car.heading[0]*axis[1])
                return along*car.length/2 + across*car.width/2
            if separation >= radius(a) + radius(b) - 0.01:
                return False
    return True
