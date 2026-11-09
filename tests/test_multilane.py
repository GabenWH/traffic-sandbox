"""Behavior tests for real constructed-road multilane traffic."""
import unittest
from city import CityMap, Terrain
from traffic_testbed import RoadVehicleSimulation
from intersection_controls import movements_conflict


def straight_city(lanes=3, reverse=3, length=3000):
    city = CityMap(terrain=Terrain(trees=[]))
    road = city.add_road([(0, 100), (length, 100)], forward_lane_count=lanes, reverse_lane_count=reverse)
    ends = sorted(city.cul_de_sacs, key=lambda j: j.position[0])
    return city, road, ends[0], ends[-1]


def first_lane(car):
    return next(e.value for e in car.route.edges if e.kind == 'lane')


class MultilaneTests(unittest.TestCase):
    def test_three_lanes_admit_outside_middle_inside_then_repeat(self):
        city, road, west, east = straight_city()
        sim = RoadVehicleSimulation(spawn_interval=1000)
        first = []
        for _ in range(3):
            car = sim.spawn_car(city, west, east)
            self.assertIsNotNone(car, 'each empty lane must accept a car')
            first.append(car)
        self.assertEqual([first_lane(c).lane_index for c in first], [2, 1, 0])
        for car in first:
            car.place(100)
        second = [sim.spawn_car(city, west, east) for _ in range(3)]
        self.assertTrue(all(c is not None for c in second))
        self.assertEqual([first_lane(c).lane_index for c in second], [2, 1, 0])

    def test_external_junction_trips_fill_all_lanes_but_exact_starts_stay_exact(self):
        from mobility import lane_position_at_distance
        city,road,west,east=straight_city()
        sim=RoadVehicleSimulation(spawn_interval=1000);sim._native_backend(city)
        route=city.find_vehicle_route_between(west,east)
        cars=[sim.admit_route(route,vehicle_id=f'external-{i}',source_id=west.id,destination_id=east.id)
              for i in range(3)]
        self.assertTrue(all(c is not None for c in cars))
        self.assertEqual([first_lane(c).lane_index for c in cars],[2,1,0])
        for car in cars:car.place(150)
        lane=next(l for l in city.roads[0].lanes if l.direction=='forward' and l.lane_index==0)
        exact=city.find_vehicle_route_between(lane_position_at_distance(lane,10),east)
        car=sim.admit_route(exact,vehicle_id='exact-start',source_id='point',destination_id=east.id)
        self.assertIsNotNone(car)
        self.assertAlmostEqual(car.position[1],lane.points[0][1])

    def test_three_through_lanes_do_not_funnel_at_junction(self):
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (1000, 100)], forward_lane_count=3, reverse_lane_count=0)
        city.add_road([(500, 0), (500, 200)])
        layer = city.mobility.layers['vehicles']
        through = [t.edge.value for n in layer.graph.nodes for t in layer.graph.transitions_from(n)
                   if t.edge.kind == 'lane_connection' and t.edge.value.maneuver.kind.value == 'through'
                   and t.edge.value.source_output.heading[0] > .9]
        self.assertEqual(len(through), 3)
        self.assertEqual(len({c.path[0] for c in through}), 3)
        self.assertEqual(len({c.path[-1] for c in through}), 3)
        for i, a in enumerate(through):
            for b in through[i+1:]:
                self.assertFalse(movements_conflict(a, b))

class PassingTests(unittest.TestCase):
    def scene(self, mode='copy'):
        city, road, west, east = straight_city(lanes=2, reverse=2, length=5000)
        sim = RoadVehicleSimulation(spawn_interval=1000, speed_mph=60, native_output_mode=mode)
        sim._native_backend(city)
        lanes = sorted((l for l in city.roads[0].lanes if l.direction == 'forward'),
                       key=lambda l: l.lane_index, reverse=True)
        return city, sim, lanes, east

    def admit(self, city, sim, lane, end, name, x, speed):
        from mobility import nearest_lane_position
        start = nearest_lane_position(lane, (x, lane.points[0][1]))[0]
        route = city.find_vehicle_route_between(start, end)
        car = sim.admit_route(route, vehicle_id=name, source_id='source', destination_id=end.id,
                              speed_cap_mph=speed)
        self.assertIsNotNone(car)
        return car

    def test_faster_car_passes_left_then_returns_right_smoothly(self):
        for mode in ('copy', 'shared'):
            with self.subTest(mode=mode):
                city, sim, lanes, end = self.scene(mode)
                slow = self.admit(city, sim, lanes[0], end, 'slow', 700, 20)
                fast = self.admit(city, sim, lanes[0], end, 'fast', 550, 60)
                outside_y = fast.position[1]
                reached_left = passed = returned = False
                previous = fast.position
                for _ in range(800):
                    sim.update(city, .05)
                    p = fast.position
                    self.assertLess(abs(p[1]-previous[1]), 1, 'lane changes must not teleport sideways')
                    self.assertGreaterEqual(p[0], previous[0]-.01, 'lane changes cannot reset world progress')
                    reached_left |= p[1] < outside_y-9
                    passed |= reached_left and p[0] > slow.position[0]+30
                    returned |= passed and abs(p[1]-outside_y)<.1
                    previous=p
                    if returned: break
                self.assertTrue(reached_left, 'faster follower must use the left lane')
                self.assertTrue(passed, 'passing car must get ahead')
                self.assertTrue(returned, 'return right once there is room')
                self.assertEqual(fast.occupancy_position()[0], ('lane', lanes[0].id))

    def test_fast_rear_vehicle_blocks_lane_change(self):
        city, sim, lanes, end = self.scene()
        self.admit(city, sim, lanes[0], end, 'slow', 700, 20)
        follower = self.admit(city, sim, lanes[0], end, 'follower', 550, 40)
        self.admit(city, sim, lanes[1], end, 'rear', 480, 60)
        initial_y=follower.position[1]
        for _ in range(10):
            sim.update(city,.05)
            self.assertAlmostEqual(follower.position[1],initial_y)

    def test_transition_survives_backend_recreation(self):
        city, sim, lanes, end = self.scene('shared')
        self.admit(city, sim, lanes[0], end, 'slow', 700, 20)
        car = self.admit(city, sim, lanes[0], end, 'fast', 550, 60)
        for _ in range(50):
            sim.update(city, .05)
            if getattr(car, '_lane_change_occupancy', None):
                break
        self.assertIsNotNone(getattr(car, '_lane_change_occupancy', None))
        before=car.position
        car.speed_cap_mph=55
        sim.update(city, .05)
        self.assertLess(abs(car.position[1]-before[1]), 1)
        self.assertGreaterEqual(car.position[0], before[0])
        sim._ensure_occupancy()
        source_entries=sim.occupancy._sections[('lane', lanes[0].id)]
        self.assertIn(car.id, [e.car.id for e in source_entries])
        self.assertNotEqual(car.occupancy_position()[0], ('lane', lanes[0].id))
        for _ in range(800):
            sim.update(city,.05)
            if car.position[0]>900 and car.occupancy_position()[0]==('lane', lanes[0].id):
                break
        self.assertEqual(car.occupancy_position()[0], ('lane', lanes[0].id))

    def test_lane_change_uses_target_lane_phantom_leader(self):
        city, sim, lanes, end = self.scene()
        self.admit(city, sim, lanes[0], end, 'slow', 700, 20)
        car=self.admit(city, sim, lanes[0], end, 'fast', 550, 60)
        self.admit(city, sim, lanes[1], end, 'target-leader', 1100, 35)
        phantoms=[]
        for _ in range(100):
            sim.update(city,.05)
            phantoms.append(car.brain.phantom_target)
        self.assertIn('target-leader', phantoms)


class JunctionMultilaneTests(unittest.TestCase):
    def test_six_cars_queue_in_two_rows_and_all_clear_green(self):
        from models import ControlDefinition, ControlType
        from intersection_controls import FixedTimeSignalController, SignalPlan, SignalPhase
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,100), (1200,100)], forward_lane_count=3, reverse_lane_count=3)
        city.add_road([(600,-200),(600,400)])
        west=next(j for j in city.cul_de_sacs if j.position==(0,100))
        east=next(j for j in city.cul_de_sacs if j.position==(1200,100))
        policies=city.standard_intersections[0].lane_connections
        for c in policies: c.control=ControlDefinition(ControlType.SIGNAL,'test')
        sim=RoadVehicleSimulation(spawn_interval=1000)
        cars=[]
        for row in range(2):
            batch=[sim.spawn_car(city,west,east) for _ in range(3)]
            self.assertTrue(all(c is not None for c in batch))
            for car in batch: car.place(250-row*70)
            cars.extend(batch)
        for _ in range(400): sim.update(city,.05)
        lanes={}
        for car in cars:
            lanes.setdefault(car.occupancy_position()[0],[]).append(car)
            self.assertLess(car.speed,.1)
            self.assertLess(car.position[0],600)
        self.assertEqual(sorted(map(len,lanes.values())),[2,2,2])
        for group in lanes.values():
            front=max(group,key=lambda c:c.position[0])
            stop=front.controlled_movements[0][0]-front.length/2
            self.assertLess(abs(front.distance-stop),.1)
        sim.signal_controllers['test']=FixedTimeSignalController(SignalPlan((
            SignalPhase(120,{c.id for c in policies if c.source_output.heading[0]>.9 and c.maneuver.kind.value=='through'},0,0),)))
        completed=[]
        for _ in range(900): completed.extend(sim.update(city,.05))
        self.assertEqual({c.id for c in completed},{c.id for c in cars})

    def test_exact_outer_lane_origin_can_still_route_to_a_left_turn(self):
        from mobility import lane_position_at_distance
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,100),(1200,100)],forward_lane_count=3,reverse_lane_count=3)
        city.add_road([(600,-300),(600,500)])
        road=min((r for r in city.roads if r.centerline[0][1]==100),key=lambda r:r.centerline[0][0])
        lane=next(l for l in road.lanes if l.direction=='forward' and l.lane_index==2)
        destination=next(j for j in city.cul_de_sacs if j.position==(600,-300))
        route=city.find_vehicle_route_between(lane_position_at_distance(lane,100),destination)
        self.assertIsNotNone(route)
        turns=[e.value for e in route.edges if e.kind=='lane_connection']
        self.assertEqual(len(turns),1,'lane expansion must not create a detour for existing legal turns')
        self.assertEqual(turns[0].maneuver.kind.value,'left_turn')

    def test_reverse_direction_fills_rightmost_first(self):
        city, road, west, east=straight_city()
        sim=RoadVehicleSimulation(spawn_interval=1000)
        cars=[sim.spawn_car(city,east,west) for _ in range(3)]
        self.assertTrue(all(c is not None for c in cars))
        self.assertEqual([first_lane(c).lane_index for c in cars],[0,1,2])

    def test_lane_drop_uses_shared_merge_and_finishes_without_overlap(self):
        from itertools import combinations
        from traffic_testbed import vehicle_footprints_overlap
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,100),(600,100)],forward_lane_count=3,reverse_lane_count=3)
        city.add_road([(600,100),(1800,100)],forward_lane_count=2,reverse_lane_count=2)
        west=min(city.cul_de_sacs,key=lambda j:j.position[0]);east=max(city.cul_de_sacs,key=lambda j:j.position[0])
        sim=RoadVehicleSimulation(spawn_interval=1000,speed_mph=45)
        cars=[]
        for row in range(3):
            batch=[sim.spawn_car(city,west,east) for _ in range(3)]
            self.assertTrue(all(c is not None for c in batch))
            for car in batch: car.place(250-row*70)
            cars.extend(batch)
        self.assertTrue(any(m[2].merge_target is not None for c in cars for m in c.controlled_movements))
        completed=[]
        for _ in range(1400):
            completed.extend(sim.update(city,.05))
            for a,b in combinations(sim.cars,2):
                self.assertFalse(vehicle_footprints_overlap(a,b),(a.id,b.id,a.position,b.position))
        self.assertEqual(len(completed),len(cars))

    def test_roundabout_multilane_paths_have_no_unmeasured_geometry_gaps(self):
        from models import IntersectionKind, polyline_length
        from mobility import vehicle_route_points, vehicle_link_points
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,300),(1600,300)],forward_lane_count=3,reverse_lane_count=3)
        city.add_road([(800,-500),(800,1100)],forward_lane_count=3,reverse_lane_count=3)
        city.standard_intersections[0].kind=IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network()
        west=next(j for j in city.cul_de_sacs if j.position==(0,300))
        east=next(j for j in city.cul_de_sacs if j.position==(1600,300))
        route=city.find_vehicle_route_between(west,east)
        self.assertAlmostEqual(polyline_length(vehicle_route_points(route)),
                               sum(polyline_length(vehicle_link_points(e)) for e in route.edges))

    def test_signal_accepts_a_derived_lane_movement_id(self):
        from models import ControlDefinition, ControlType
        from intersection_controls import FixedTimeSignalController, SignalPlan, SignalPhase
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,100),(1200,100)],forward_lane_count=3,reverse_lane_count=3)
        city.add_road([(600,-200),(600,400)])
        west=next(j for j in city.cul_de_sacs if j.position==(0,100));east=next(j for j in city.cul_de_sacs if j.position==(1200,100))
        for c in city.standard_intersections[0].lane_connections:c.control=ControlDefinition(ControlType.SIGNAL,'test')
        sim=RoadVehicleSimulation(spawn_interval=1000)
        car=sim.spawn_car(city,west,east)
        start,_,movement=car.controlled_movements[0]
        car.place(start-car.length/2-1);car.speed=0
        sim.signal_controllers['test']=FixedTimeSignalController(SignalPlan((SignalPhase(120,{movement.id},0,0),)))
        for _ in range(200):sim.update(city,.05)
        self.assertGreater(car.position[0],650)

class MultilaneSafetyTests(unittest.TestCase):
    def test_dense_multilane_traffic_has_no_body_overlaps(self):
        from itertools import combinations
        from traffic_testbed import vehicle_footprints_overlap
        helper=PassingTests()
        city,sim,lanes,end=helper.scene()
        cars=[]
        for rank,lane in enumerate(lanes):
            for i in range(6 if rank == 0 else 3):
                cars.append(helper.admit(city,sim,lane,end,f'lane-{rank}-car-{i}',
                                         (300+i*170 if rank == 0 else 200+i*700), (20 if i%3==2 else 55) if rank == 0 else 40))
        changed=set();completed=[]
        for _ in range(1400):
            completed.extend(sim.update(city,.05))
            for car in sim.cars:
                if getattr(car,'_lane_change_occupancy',None): changed.add(car.id)
            for a,b in combinations(sim.cars,2):
                self.assertFalse(vehicle_footprints_overlap(a,b),(a.id,b.id,a.position,b.position))
        self.assertTrue(changed,'scenario must exercise actual lateral merges')
        self.assertTrue(completed,'dense traffic must make progress')

    def test_multilane_roundabout_traffic_keeps_physical_clearance(self):
        from itertools import combinations
        from models import IntersectionKind
        from traffic_testbed import vehicle_footprints_overlap
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,300),(1600,300)],forward_lane_count=3,reverse_lane_count=3)
        city.add_road([(800,-500),(800,1100)],forward_lane_count=3,reverse_lane_count=3)
        city.standard_intersections[0].kind=IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network()
        sim=RoadVehicleSimulation(spawn_interval=2,max_cars=32)
        for end in city.cul_de_sacs: sim.toggle_junction(end)
        completed=[]
        for _ in range(1800):
            completed.extend(sim.update(city,.05))
            for a,b in combinations(sim.cars,2):
                self.assertFalse(vehicle_footprints_overlap(a,b),(a.id,b.id,a.position,b.position))
        self.assertGreater(len(completed),5)

    def test_explicit_placement_cancels_an_active_lane_change(self):
        helper=PassingTests()
        city,sim,lanes,end=helper.scene('shared')
        helper.admit(city,sim,lanes[0],end,'slow',700,20)
        car=helper.admit(city,sim,lanes[0],end,'fast',550,60)
        for _ in range(50):
            sim.update(city,.05)
            if getattr(car,'_lane_change_occupancy',None): break
        self.assertIsNotNone(getattr(car,'_lane_change_occupancy',None))
        sim.place_vehicle(car.id,1500)
        before=car.position
        placed_lane=car.occupancy_position()[0]
        self.assertIsNone(getattr(car,'_lane_change_occupancy',None))
        sim.update(city,.05)
        self.assertGreaterEqual(car.position[0],before[0])
        self.assertLess(car.position[0]-before[0],5)
        lateral=getattr(car,'_lane_change_occupancy',None)
        if lateral is not None:
            self.assertEqual(lateral[0],placed_lane)

    def test_generated_route_cannot_change_an_exact_destination(self):
        from mobility import lane_position_at_distance
        from models import polyline_length
        city=CityMap(terrain=Terrain(trees=[]))
        for a,b,count in ((0,1000,2),(1000,1500,1),(1500,5000,2)):
            city.add_road([(a,100),(b,100)],forward_lane_count=count,reverse_lane_count=count)
        roads=sorted(city.roads,key=lambda r:r.centerline[0][0])
        source=next(l for l in roads[0].lanes if l.direction=='forward' and l.lane_index==1)
        final=next(l for l in roads[-1].lanes if l.direction=='forward' and l.lane_index==0)
        destination=lane_position_at_distance(final,polyline_length(final.points))
        west=min(city.cul_de_sacs,key=lambda j:j.position[0]);east=max(city.cul_de_sacs,key=lambda j:j.position[0])
        sim=RoadVehicleSimulation(spawn_interval=1000,speed_mph=60)
        sim._native_backend(city)
        for name,distance,speed in (('slow',650,20),('fast',500,60)):
            route=city.find_vehicle_route_between(lane_position_at_distance(source,distance),destination)
            car=sim.admit_route(route,vehicle_id=name,source_id=west.id,destination_id='exact',speed_cap_mph=speed)
            self.assertIsNotNone(car)
        for _ in range(100):
            sim.update(city,.05)
            if getattr(car,'_lane_change_occupancy',None):break
        self.assertIsNotNone(getattr(car,'_lane_change_occupancy',None))
        self.assertIsNotNone(sim.spawn_car(city,west,east))
        finished=False
        for _ in range(3000):
            if car in sim.update(city,.05):
                finished=True;break
        self.assertTrue(finished)
        self.assertAlmostEqual(car.position[0],destination.point[0])
        self.assertAlmostEqual(car.position[1],destination.point[1])

    def test_reverse_direction_passing_uses_drivers_left(self):
        helper=PassingTests()
        city,sim,_,_=helper.scene()
        west=min(city.cul_de_sacs,key=lambda j:j.position[0])
        lane=next(l for l in city.roads[0].lanes if l.direction=='reverse' and l.lane_index==0)
        slow=helper.admit(city,sim,lane,west,'slow',4050,20)
        fast=helper.admit(city,sim,lane,west,'fast',4200,60)
        outside_y=fast.position[1];left=False;returned=False
        for _ in range(800):
            sim.update(city,.05)
            left |= fast.position[1]>outside_y+9
            returned |= left and fast.position[0]<slow.position[0]-30 and abs(fast.position[1]-outside_y)<.1
            if returned:break
        self.assertTrue(returned)

    def test_passing_on_curved_road_has_continuous_motion_and_no_overlap(self):
        from math import dist
        from traffic_testbed import vehicle_footprints_overlap
        from mobility import lane_position_at_distance
        city=CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0,100),(1000,100),(1600,400),(4000,400)],forward_lane_count=2,reverse_lane_count=2)
        end=max(city.cul_de_sacs,key=lambda j:j.position[0])
        lane=next(l for l in city.roads[0].lanes if l.direction=='forward' and l.lane_index==1)
        sim=RoadVehicleSimulation(spawn_interval=1000,speed_mph=60);sim._native_backend(city)
        cars=[]
        for name,progress,speed in (('slow',950,20),('fast',800,60)):
            route=city.find_vehicle_route_between(lane_position_at_distance(lane,progress),end)
            cars.append(sim.admit_route(route,vehicle_id=name,source_id='source',destination_id=end.id,speed_cap_mph=speed))
        slow,fast=cars;previous=fast.position;changed=False
        for _ in range(500):
            sim.update(city,.05)
            changed |= getattr(fast,'_lane_change_occupancy',None) is not None
            self.assertLess(dist(previous,fast.position),6)
            self.assertFalse(vehicle_footprints_overlap(slow,fast))
            previous=fast.position
        self.assertTrue(changed)
        self.assertGreater(fast.position[0],slow.position[0])


if __name__ == '__main__':
    unittest.main()
