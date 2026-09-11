"""Regressions isolated by the roundabout audit."""
import unittest
from merge_behavior import MergeObservation, MergeVehicle, RollingMerge

class MergeSafetyTests(unittest.TestCase):
    def test_zero_phantom_influence_preserves_free_acceleration(self):
        obs=MergeObservation(203.58,14,(MergeVehicle('ahead',40,17.6,14),))
        self.assertEqual(RollingMerge().decide(obs,0,17.6).desired_speed,17.6)

    def test_entry_is_not_approved_using_a_slower_plan_than_execution(self):
        import json
        from pathlib import Path
        record=json.loads((Path(__file__).parents[1]/'docs/analysis/roundabout_audit.json').read_text())['approval']
        raw=record['obs']['merge']
        obs=MergeObservation(raw['distance_to_join'],raw['length'],tuple(MergeVehicle(**v) for v in raw['vehicles']))
        self.assertFalse(RollingMerge().decide(obs,record['speed'],17.6).can_enter)

    def test_waiting_other_entrance_is_not_circulating_priority(self):
        from test_junction_traffic import cross_city
        from models import IntersectionKind
        from traffic_testbed import TestTrafficSimulation
        from merge_behavior import observe_merge
        city=cross_city();city.standard_intersections[0].kind=IntersectionKind.ROUNDABOUT
        city.rebuild_mobility_network();traffic=TestTrafficSimulation()
        ends=city.cul_de_sacs
        a=traffic.spawn_car(city,ends[0],ends[1]);b=traffic.spawn_car(city,ends[2],ends[3])
        movement=a.controlled_movements[0]
        for car in (a,b):
            car.distance=car.controlled_movements[0][0]-car.length/2-1
            car.speed=0;car.advance(0)
        self.assertEqual(observe_merge(a,movement,[a,b]).vehicles,())

    def test_rear_gap_accounts_for_queued_car_accelerating_to_road_speed(self):
        from merge_behavior import _gap_at_arrival
        slow=MergeObservation(37.45,14,(MergeVehicle('rear',-100,3,14),))
        accelerating=MergeObservation(37.45,14,(MergeVehicle('rear',-100,3,14,17.6),))
        self.assertTrue(_gap_at_arrival(slow,0,6,.8))
        self.assertFalse(_gap_at_arrival(accelerating,0,6,.8))

    def test_yield_line_is_inside_entry_but_clear_of_circulating_bodies(self):
        import json,math
        from pathlib import Path
        from types import SimpleNamespace
        from persistence import world_from_dict
        from traffic_testbed import TestTrafficSimulation
        from test_junction_traffic import cars_overlap
        from roundabouts import ring_radius
        city=world_from_dict(json.loads((Path(__file__).parent/'fixtures/roundabout_test.json').read_text())).city_map
        junction=city.standard_intersections[0];cx,cy=junction.position;r=ring_radius(junction)
        for i,source in enumerate(city.cul_de_sacs):
            traffic=TestTrafficSimulation()
            car=traffic.spawn_car(city,source,city.cul_de_sacs[(i+1)%4])
            entry=car.controlled_movements[0]
            self.assertGreater(getattr(entry[2],'control_offset',0),2)
            car.distance=entry[0]-car.length/2;car.advance(0)
            for step in range(360):
                angle=math.radians(step)
                circulating=SimpleNamespace(position=(cx+r*math.cos(angle),cy+r*math.sin(angle)),
                    heading=(-math.sin(angle),math.cos(angle)),length=14,width=6)
                self.assertFalse(cars_overlap(car,circulating))

    def test_new_entry_respects_committed_downstream_merge(self):
        from merge_behavior import MergeReservation,_gap_at_arrival
        blocked=MergeObservation(30,14,(),(MergeReservation(40,8),))
        cleared=MergeObservation(30,14,(),(MergeReservation(40,1),))
        self.assertFalse(_gap_at_arrival(blocked,17.6,17.6,.8))
        self.assertTrue(_gap_at_arrival(cleared,17.6,17.6,.8))

    def test_uploaded_roundabout_collision_and_freeze_regression(self):
        import importlib.util
        from pathlib import Path
        from types import SimpleNamespace
        root=Path(__file__).parents[1]
        spec=importlib.util.spec_from_file_location('roundabout_audit',root/'tools/analyze_roundabouts.py')
        audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
        result=audit.run(SimpleNamespace(map=root/'tests/fixtures/roundabout_test.json',
            seed=42,dt=.05,seconds=80,experiment='baseline'))
        self.assertEqual(result['overlap_pair_ticks'],0,result['first_collision'])
        self.assertGreater(result['completed'],10)
        stop=result['longest_stop_without_indexed_leader']
        self.assertTrue(stop is None or stop['nose_before_line']<1,stop)

    def test_downstream_reservation_allows_for_acceleration_after_own_merge(self):
        from merge_behavior import MergeReservation,_gap_at_arrival
        observation=MergeObservation(20,14,(),(MergeReservation(60,9.2),),17.6)
        self.assertFalse(_gap_at_arrival(observation,6,6,.8))
