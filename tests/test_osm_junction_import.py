"""OSM topology and controls through the public city import/save/runtime path."""
import json
import math
from pathlib import Path
import tempfile
import unittest

from intersection_controls import FixedTimeSignalController, SignalPhase, SignalPlan, SignalAspect, movements_conflict
from mobility import VEHICLE_LAYER
from models import ControlType, IntersectionKind
from persistence import world_from_dict, world_to_dict
from tools.run_arcata_scale_test import build_city
from traffic_testbed import RoadVehicleSimulation


class OSMJunctionImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.boundary = self.root / 'boundary.osm'
        self.boundary.write_text('''<osm>
          <node id="1" lon="-124.08" lat="40.86"/>
          <node id="2" lon="-124.07" lat="40.86"/>
          <node id="3" lon="-124.07" lat="40.87"/>
          <node id="4" lon="-124.08" lat="40.87"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
          <relation id="42"><member type="way" ref="10" role="outer"/>
            <tag k="name" v="Arcata"/><tag k="boundary" v="administrative"/>
          </relation></osm>''')

    def node(self, ident, x, y, **tags):
        # Feet around an origin comfortably inside the boundary.
        return dict(type='node', id=ident, lon=-124.075 + x / 276000,
                    lat=40.865 + y / 364000, tags=tags)

    def way(self, ident, nodes, **tags):
        return dict(type='way', id=ident, nodes=nodes,
                    tags=dict(highway='residential', **tags))

    def build(self, elements, supplemental=()):
        path = self.root / 'roads.json'
        path.write_text(json.dumps(dict(elements=elements)))
        return build_city([path, *supplemental], self.boundary)

    def cross(self, **center_tags):
        return [self.node(1, 0, 0, **center_tags), self.node(2, -400, 0),
                self.node(3, 400, 0), self.node(4, 0, -400), self.node(5, 0, 400),
                self.way(20, [2, 1, 3]), self.way(21, [4, 1, 5])]

    def junction(self, city):
        return next(j for j in city.intersections if len(j.connected_roads) == 4)

    def ring(self, split=False, complete=True):
        points = [(1, 70, 0), (2, 0, 70), (3, -70, 0), (4, 0, -70),
                  (5, 400, 0), (6, 0, 400), (7, -400, 0), (8, 0, -400)]
        elements = [self.node(*point) for point in points]
        if split:
            elements += [self.way(10, [1, 2, 3], junction='roundabout'),
                         self.way(11, [3, 4, 1] if complete else [3, 4], junction='roundabout')]
        else:
            elements += [self.way(10, [1, 2, 3, 4, 1], junction='roundabout')]
        return elements + [self.way(20+i, [5+i, 1+i]) for i in range(4)]

    def test_closed_ring_is_one_dedicated_roundabout_with_shared_yield_routes(self):
        city, _, _ = self.build(self.ring())
        rings = [j for j in city.intersections if j.kind is IntersectionKind.ROUNDABOUT]
        self.assertEqual(len(rings), 1)
        self.assertEqual(len(city.roads), 4)
        self.assertEqual(len(rings[0].connected_roads), 4)
        graph = city.mobility.layers[VEHICLE_LAYER].graph
        links = [t.edge for node in graph.nodes for t in graph.transitions_from(node)]
        entries = [e.value for e in links if e.kind == 'lane_connection'
                   and e.value.roundabout_role == 'entry']
        self.assertEqual(len(entries), 4)
        self.assertTrue(all(c.control.kind is ControlType.YIELD and c.merge_target for c in entries))
        route = city.find_vehicle_route(city.roads[0].lanes[0], city.roads[1].lanes[1])
        self.assertIsNotNone(route)
        self.assertTrue(any(e.kind == 'lane' and str(e.value.road_id).startswith('roundabout:')
                            for e in route.edges))

    def test_split_ways_form_one_roundabout(self):
        city, _, _ = self.build(self.ring(split=True))
        self.assertEqual(sum(j.kind is IntersectionKind.ROUNDABOUT for j in city.intersections), 1)
        self.assertEqual(len(city.roads), 4)

    def test_incomplete_ring_preserves_its_roads(self):
        city, _, meta = self.build(self.ring(split=True, complete=False))
        self.assertFalse(any(j.kind is IntersectionKind.ROUNDABOUT for j in city.intersections))
        self.assertGreater(len(city.roads), 4)
        self.assertEqual(meta['incomplete_roundabouts'], 1)

    def test_ring_crossing_boundary_hole_keeps_clipped_road_geometry(self):
        # A small administrative hole intersects an arc, between its OSM vertices.
        xml = self.boundary.read_text().replace('</relation>',
                    '<member type="way" ref="99" role="inner"/></relation>')
        corners = [(25, 25), (45, 25), (45, 45), (25, 45)]
        extra = ''.join(f'<node id="{90+i}" lon="{-124.075+x/276000}" '
                        f'lat="{40.865+y/364000}"/>' for i, (x, y) in enumerate(corners))
        extra += '<way id="99">' + ''.join(f'<nd ref="{i}"/>' for i in [90, 91, 92, 93, 90]) + '</way>'
        self.boundary.write_text(xml.replace('</osm>', extra + '</osm>'))
        city, _, meta = self.build(self.ring())
        self.assertFalse(any(j.kind is IntersectionKind.ROUNDABOUT for j in city.intersections))
        self.assertEqual(meta['incomplete_roundabouts'], 1)

    def test_mini_roundabout_node_uses_dedicated_type(self):
        city, _, _ = self.build(self.cross(highway='mini_roundabout'))
        self.assertIs(self.junction(city).kind, IntersectionKind.ROUNDABOUT)

    def test_center_stop_is_an_all_way_stop(self):
        city, _, _ = self.build(self.cross(highway='stop', stop='all'))
        self.assertTrue(self.junction(city).is_all_way_stop)

    def test_approach_stop_controls_only_downstream_travel(self):
        elements = self.cross()
        elements[5] = self.way(20, [2, 9, 1, 3])
        elements.append(self.node(9, -70, 0, highway='stop', direction='forward'))
        city, _, _ = self.build(elements)
        junction = self.junction(city)
        stopped = [c for c in junction.lane_connections if c.control.kind is ControlType.STOP]
        self.assertEqual(len(stopped), 3)
        self.assertTrue(all(c.source_output.position[0] < junction.position[0] for c in stopped))
        self.assertTrue(all(c.control.kind is not ControlType.STOP
                            for c in junction.lane_connections if c not in stopped))

    def test_backward_approach_yield_respects_way_direction(self):
        elements = self.cross()
        elements[5] = self.way(20, [2, 1, 9, 3])
        elements.append(self.node(9, 70, 0, highway='give_way', direction='backward'))
        city, _, _ = self.build(elements)
        junction = self.junction(city)
        yields = [c for c in junction.lane_connections if c.control.kind is ControlType.YIELD]
        self.assertEqual(len(yields), 3)
        self.assertTrue(all(c.source_output.position[0] > junction.position[0] for c in yields))

    def test_sign_at_way_split_controls_junction_instead_of_artificial_two_road_node(self):
        elements = self.cross()
        elements[5] = self.way(20, [2, 9])
        elements += [self.way(22, [9, 1, 3]),
                     self.node(9, -70, 0, highway='stop', direction='forward')]
        city, _, _ = self.build(elements)
        junction = self.junction(city)
        stopped = [c for c in junction.lane_connections if c.control.kind is ControlType.STOP]
        self.assertEqual(len(stopped), 3)
        self.assertTrue(all(c.source_output.position[0] < junction.position[0] for c in stopped))
        split = next(j for j in city.intersections if len(j.connected_roads) == 2)
        self.assertTrue(all(c.control.kind is not ControlType.STOP for c in split.lane_connections))

    def test_sign_cannot_propagate_backwards_against_its_one_way_road(self):
        elements = [self.node(1, -400, 0), self.node(2, -100, 0),
                    self.node(3, 0, 0, highway='stop'), self.node(4, 800, 0),
                    self.node(5, -400, 300), self.node(6, -400, -300),
                    self.node(7, 800, 300), self.node(8, 800, -300),
                    self.way(20, [1, 2]), self.way(21, [2, 3, 4], oneway='yes'),
                    self.way(22, [5, 1, 6]), self.way(23, [7, 4, 8])]
        city, _, _ = self.build(elements)
        a = next(j for j in city.intersections if j.id.endswith('["node","1"]'))
        b = next(j for j in city.intersections if j.id.endswith('["node","4"]'))
        self.assertTrue(a.is_all_way_stop)
        stopped = [c for c in b.lane_connections if c.control.kind is ControlType.STOP]
        self.assertEqual(len(stopped), 2)
        self.assertTrue(all(c.source_output.road.id.startswith('osm-way:21:') for c in stopped))

    def test_sign_cannot_cross_an_intermediate_road_against_one_way_flow(self):
        elements = [self.node(1, -400, 0), self.node(2, -100, 0),
                    self.node(3, -200, 0, highway='stop', direction='forward'),
                    self.node(4, 800, 0), self.node(5, -400, 300),
                    self.node(6, -400, -300), self.node(7, 800, 300),
                    self.node(8, 800, -300), self.node(9, 100, 0),
                    self.way(20, [1, 3, 2]), self.way(21, [9, 2], oneway='yes'),
                    self.way(24, [9, 4]), self.way(22, [5, 1, 6]), self.way(23, [7, 4, 8])]
        city, _, meta = self.build(elements)
        b = next(j for j in city.intersections if j.id.endswith('["node","4"]'))
        self.assertTrue(b.is_all_way_stop)
        self.assertEqual(meta['mapped_sign_intersections'], 0)

    def test_sign_before_two_approach_roundabout_does_not_control_farther_junction(self):
        elements = [self.node(1, 70, 0), self.node(2, 0, 70), self.node(3, -70, 0),
                    self.node(4, 0, -70), self.node(5, -600, 0),
                    self.node(6, -200, 0, highway='give_way', direction='forward'),
                    self.node(7, 600, 0), self.node(8, 600, 300), self.node(9, 600, -300),
                    self.way(10, [1, 2, 3, 4, 1], junction='roundabout'),
                    self.way(20, [5, 6, 3]), self.way(21, [1, 7]), self.way(22, [8, 7, 9])]
        city, _, _ = self.build(elements)
        farther = next(j for j in city.intersections if j.id.endswith('["node","7"]'))
        self.assertTrue(farther.is_all_way_stop)
        self.assertEqual(sum(j.kind is IntersectionKind.ROUNDABOUT for j in city.intersections), 1)

    def test_minor_road_stop_does_not_stop_priority_road(self):
        elements = self.cross(highway='stop', stop='minor')
        elements[5]['tags']['highway'] = 'secondary'
        city, _, _ = self.build(elements)
        stopped = [c for c in self.junction(city).lane_connections if c.control.kind is ControlType.STOP]
        self.assertEqual(len(stopped), 6)
        self.assertTrue(all(c.source_output.road.name.endswith('[residential]') for c in stopped))

    def test_true_dead_end_has_turnaround_and_boundary_portal_stays_open(self):
        elements = [self.node(1, 0, 0), self.node(2, 2500, 0), self.way(20, [1, 2])]
        city, portals, _ = self.build(elements)
        dead_end = next(j for j in city.intersections if j.id not in portals)
        self.assertIs(dead_end.kind, IntersectionKind.CUL_DE_SAC)
        self.assertTrue(dead_end.lane_connections)
        self.assertTrue(all(j.kind is IntersectionKind.STANDARD
                            for j in city.intersections if j.id in portals))

    def test_tagged_osm_xml_supplement_is_accepted(self):
        tags = self.root / 'controls.osm'
        tags.write_text('<osm><node id="1" lon="-124.075" lat="40.865">'
                        '<tag k="highway" v="traffic_signals"/></node></osm>')
        city, _, _ = self.build(self.cross(), [tags])
        self.assertTrue(all(c.control.kind is ControlType.SIGNAL
                            for c in self.junction(city).lane_connections))

    def test_untagged_local_junction_gets_inferred_stop_controls(self):
        city, _, meta = self.build(self.cross())
        self.assertTrue(self.junction(city).is_all_way_stop)
        self.assertEqual(meta['inferred_stop_intersections'], 1)

    def test_node_tags_survive_later_skeleton_extract(self):
        supplement = self.root / 'skeleton.json'
        supplement.write_text(json.dumps(dict(elements=[self.node(1, 0, 0)])))
        city, _, _ = self.build(self.cross(highway='traffic_signals'), [supplement])
        self.assertTrue(all(c.control.kind is ControlType.SIGNAL
                            for c in self.junction(city).lane_connections))

    def test_signals_have_working_conflict_safe_cycles_after_world_reload(self):
        city, _, _ = self.build(self.cross(highway='traffic_signals'))
        world = world_to_dict(city, unit_system='imperial', camera_x=0, camera_y=0, camera_zoom=1)
        city = world_from_dict(json.loads(json.dumps(world))).city_map
        junction = self.junction(city)
        self.assertTrue(all(c.control.kind is ControlType.SIGNAL for c in junction.lane_connections))
        traffic = RoadVehicleSimulation()
        traffic.sync_network(city)
        controllers = list(traffic.signal_controllers.values())
        self.assertEqual(len(controllers), 1)
        controller = controllers[0]
        covered = set()
        aspects = set()
        for tick in range(math.ceil(controller.plan.cycle_seconds * 2)):
            traffic.elapsed_time = tick
            green = [c for c in junction.lane_connections if traffic.signal_is_green(c)]
            covered.update(c.id for c in green)
            aspects.add(controller.state_at(tick).aspect)
            for i, movement in enumerate(green):
                for other in green[i+1:]:
                    if movement.source_output != other.source_output:
                        self.assertFalse(movements_conflict(movement, other))
        self.assertEqual(covered, {c.id for c in junction.lane_connections})
        self.assertEqual(aspects, {SignalAspect.GREEN, SignalAspect.YELLOW, SignalAspect.ALL_RED})

    def test_native_cars_stop_at_imported_red_then_finish_on_green(self):
        city, _, _ = self.build(self.cross(highway='traffic_signals'))
        junction = self.junction(city)
        traffic = RoadVehicleSimulation()
        traffic.sync_network(city)
        controller = traffic.signal_controllers[junction.id]
        movement = next(c for c in junction.lane_connections
                        if c.id not in controller.plan.phases[0].movement_ids)
        source = next(j for j in city.intersections if j is not junction
                      and movement.source_output.road in j.connected_roads)
        destination = next(j for j in city.intersections if j is not junction
                           and movement.destination_input.road in j.connected_roads)
        self.assertTrue(traffic.spawn_car(city, source, destination))
        car = traffic.cars[0]
        entry = next(start for start, _, c in car.controlled_movements if c.intersection_id == junction.id)
        for _ in range(300):
            traffic.update(city, .05)
        self.assertLessEqual(car.distance + car.length / 2, entry + .1)
        finished = []
        for _ in range(2000):
            finished.extend(traffic.update(city, .05))
        self.assertEqual(len(finished), 1)
        self.assertFalse(traffic.cars)

    def test_multilane_imported_signals_never_grant_conflicting_protected_permissions(self):
        elements = self.cross(highway='traffic_signals')
        elements[5]['tags']['lanes'] = '4'
        city, _, _ = self.build(elements)
        traffic = RoadVehicleSimulation()
        traffic.sync_network(city)
        controller = traffic.signal_controllers[self.junction(city).id]
        graph = city.mobility.layers[VEHICLE_LAYER].graph
        movements = {t.edge.value.id for node in graph.nodes for t in graph.transitions_from(node)
                     if t.edge.kind == 'lane_connection' and t.edge.value.control.kind is ControlType.SIGNAL}
        covered = set()
        for tick in range(math.ceil(controller.plan.cycle_seconds)):
            traffic.elapsed_time = tick
            traffic._prepare_signal_frame(city)
            covered.update(controller.state_at(tick).movement_ids)
        self.assertEqual(covered, movements)

    def test_custom_runtime_signal_plan_survives_network_rebuild(self):
        city, _, _ = self.build(self.cross(highway='traffic_signals'))
        junction = self.junction(city)
        custom = FixedTimeSignalController(SignalPlan((SignalPhase(5, frozenset()),)))
        traffic = RoadVehicleSimulation(signal_controllers={junction.id: custom})
        traffic.sync_network(city)
        city.rebuild_mobility_network()
        traffic.sync_network(city)
        self.assertIs(traffic.signal_controllers[junction.id], custom)


if __name__ == '__main__':
    unittest.main()
