"""Crew-driven road removal, material conservation, and junction cleanup."""

import json
from types import SimpleNamespace
import unittest

from city import CityMap, Terrain
from construction import ConstructionSimulation, UnlimitedConstructionProvider
from models import BuildablePhase, IntersectionKind
from persistence import world_from_dict, world_to_dict
from resources import ResourceSpec, TruckSpec


class RoadDeconstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.city = CityMap(width=600, height=300, terrain=Terrain(trees=[]))
        self.port_road = self.city.add_road([(0, 100), (20, 100)])
        self.road = self.city.add_road([(20, 100), (70, 100)])
        self.resources = {
            "deconstruction_materials": ResourceSpec(
                "deconstruction_materials", "Deconstruction materials", "ft²", 20, 0.01,
            ),
        }
        self.trucks = {
            "material": TruckSpec("material", 7500, 10, 0, 18, 8),
            "crew": TruckSpec("crew", 0, 0, 3, 20, 8),
        }
        self.sim = ConstructionSimulation(
            self.resources, self.trucks, UnlimitedConstructionProvider(), truck_speed=1000,
        )

    def test_order_converts_paved_area_to_salvage_without_instant_removal(self) -> None:
        self.sim.request_road_deconstruction(self.city, self.road)

        self.assertIs(self.road.phase, BuildablePhase.DEMOLISHING)
        self.assertIn(self.road, self.city.roads)
        self.assertEqual(self.road.inventory.amounts["deconstruction_materials"], 1200)
        self.sim.update(self.city, 0)
        self.assertEqual(self.road.active_work.completed_work, 0)

    def test_crew_work_and_exports_remove_road_only_after_all_salvage_arrives(self) -> None:
        from construction import ExportPayload, REGIONAL_EXPORT_SITE_ID

        self.sim.request_road_deconstruction(self.city, self.road)
        self.sim.update(self.city, 40)
        self.assertIn(self.road, self.city.roads)
        self.assertGreater(self.sim.exported_materials.get("deconstruction_materials", 0), 0)
        remaining = self.road.inventory.amounts["deconstruction_materials"]
        self.assertAlmostEqual(remaining + self.sim.exported_materials["deconstruction_materials"], 1200)
        completed = self.sim.update(self.city, 200)

        self.assertNotIn(self.road, self.city.roads)
        self.assertAlmostEqual(self.sim.exported_materials["deconstruction_materials"], 1200)
        self.assertFalse(self.sim.trips)
        self.assertFalse(self.sim.pending_trips)
        exports = [trip for trip in completed if isinstance(trip.payload, ExportPayload)]
        self.assertTrue(exports)
        self.assertTrue(all(t.road_vehicle.destination_id == REGIONAL_EXPORT_SITE_ID for t in exports))
        self.assertTrue(all(t.payload.amount <= 375 for t in exports))

    def test_single_remaining_road_gets_turnaround_and_orphan_junctions_disappear(self) -> None:
        revision = self.city.mobility_revision
        self.city.remove_road(self.road)
        junctions = [j for j in self.city.intersections if j.position == (20, 100)]
        self.assertEqual(len(junctions), 1)
        self.assertIs(junctions[0].kind, IntersectionKind.CUL_DE_SAC)
        self.assertGreater(self.city.mobility_revision, revision)
        self.city.remove_road(self.port_road)
        self.assertEqual(self.city.intersections, [])

    def test_removal_preserves_connections_between_two_remaining_roads(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 200), (400, 200)])
        branch = city.add_road([(200, 200), (200, 400)])
        city.remove_road(branch)
        junctions = [j for j in city.intersections if j.position == (200, 200)]
        self.assertEqual(len(junctions), 1)
        self.assertEqual(len(junctions[0].connected_roads), 2)
        self.assertTrue(junctions[0].lane_connections)

    def test_duplicate_and_port_orders_are_rejected_without_extra_salvage(self) -> None:
        with self.assertRaisesRegex(ValueError, "port"):
            self.sim.request_road_deconstruction(self.city, self.port_road)
        self.sim.request_road_deconstruction(self.city, self.road)
        with self.assertRaises(ValueError):
            self.sim.request_road_deconstruction(self.city, self.road)
        self.assertEqual(self.road.inventory.amounts["deconstruction_materials"], 1200)

    def test_unreachable_site_waits_without_work_or_export(self) -> None:
        road = self.city.add_road([(300, 200), (400, 200)])
        self.sim.request_road_deconstruction(self.city, road)
        self.sim.update(self.city, 100)
        self.assertEqual(road.active_work.completed_work, 0)
        self.assertIn(road, self.city.roads)
        self.assertFalse(self.sim.exported_materials)

    def test_save_load_resumes_unfinished_work_and_partial_exports(self) -> None:
        for duration in (0.1, 40):
            with self.subTest(duration=duration):
                self.setUp()
                self.sim.request_road_deconstruction(self.city, self.road)
                self.sim.update(self.city, duration)
                saved = world_to_dict(
                    self.city, unit_system="imperial", camera_x=0, camera_y=0, camera_zoom=1,
                )
                loaded = world_from_dict(json.loads(json.dumps(saved))).city_map
                road = next(r for r in loaded.roads if r.id == self.road.id)
                remaining = road.inventory.amounts["deconstruction_materials"]
                resumed = ConstructionSimulation(
                    self.resources, self.trucks, UnlimitedConstructionProvider(), truck_speed=1000,
                )
                resumed.update(loaded, 200)
                self.assertNotIn(road, loaded.roads)
                self.assertAlmostEqual(resumed.exported_materials["deconstruction_materials"], remaining)

    def test_first_completed_job_does_not_strand_other_jobs_trucks(self) -> None:
        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (100, 100)])
        roads = [city.add_road([(100, 100), (200, 100)]),
                 city.add_road([(100, 100), (100, 200)])]
        sim = ConstructionSimulation(
            self.resources,
            {**self.trucks, "material": TruckSpec("material", 1_000_000, 1000, 0, 18, 8)},
            UnlimitedConstructionProvider(), truck_speed=2,
        )
        for road in roads:
            sim.request_road_deconstruction(city, road)
        sim.update(city, 1000)
        self.assertTrue(all(r not in city.roads for r in roads))
        self.assertAlmostEqual(sim.exported_materials["deconstruction_materials"], 4800)
        self.assertFalse(sim.trips)
        self.assertFalse(sim.pending_trips)

    def test_new_roads_cannot_split_or_snap_into_active_demolition_sites(self) -> None:
        for points in (
            [(300, 0), (300, 200)],
            [(500, 100), (500, 300)],
            [(495, 110), (495, 300)],
        ):
            with self.subTest(points=points):
                city = CityMap(terrain=Terrain(trees=[]))
                city.add_road([(0, 100), (100, 100)])
                road = city.add_road([(100, 100), (500, 100)])
                self.sim.request_road_deconstruction(city, road)
                revision = city.mobility_revision
                with self.assertRaisesRegex(ValueError, "deconstruction"):
                    city.add_road(points)
                self.assertEqual(city.mobility_revision, revision)
                self.assertEqual(road.centerline, [(100, 100), (500, 100)])
                self.sim.clear_trips()

    def test_unrelated_network_edit_keeps_exports_resumable(self) -> None:
        self.sim.request_road_deconstruction(self.city, self.road)
        self.sim.update(self.city, 40)
        self.city.add_road([(300, 200), (500, 200)])
        self.sim.update(self.city, 200)
        self.assertNotIn(self.road, self.city.roads)
        self.assertAlmostEqual(self.sim.exported_materials["deconstruction_materials"], 1200)


class DeconstructRoadToolTests(unittest.TestCase):
    """Exercise the actual tool against a real construction simulation."""

    setUp = RoadDeconstructionTests.setUp

    def test_click_schedules_work_and_duplicate_click_reports_reason(self) -> None:
        from ui_tools.tools.deconstruct_road_tool import DeconstructRoadTool

        messages, redraws = [], []
        canvas = SimpleNamespace(
            configure=lambda **kw: None, delete=lambda tag: None,
            create_text=lambda *a, **kw: messages.append(kw["text"]),
            tag_raise=lambda tag: None,
        )
        host = SimpleNamespace(
            canvas=canvas, city_map=self.city, construction_simulation=self.sim,
            camera_zoom=1, screen_to_world=lambda point: point,
            redraw_world=lambda: redraws.append(True),
        )
        tool = DeconstructRoadTool(host)
        tool.activate()
        tool.on_canvas_click(SimpleNamespace(x=50, y=100))
        self.assertIs(self.road.phase, BuildablePhase.DEMOLISHING)
        self.assertEqual(len(redraws), 1)
        tool.on_canvas_click(SimpleNamespace(x=50, y=100))
        self.assertEqual(len(redraws), 1)
        self.assertIn("already", tool.message)
        tool.on_canvas_click(SimpleNamespace(x=500, y=250))
        self.assertIn("No road", tool.message)
        tool.deactivate()

    def test_road_tool_keeps_draft_and_reports_conflicting_work(self) -> None:
        from ui_tools.tools.road_tool import RoadTool

        self.sim.request_road_deconstruction(self.city, self.road)
        messages, redraws = [], []
        host = SimpleNamespace(city_map=self.city, redraw_world=lambda: redraws.append(True))
        tool = RoadTool(host)
        tool.panel = SimpleNamespace(set_message=messages.append)
        tool.points = [(50, 0), (50, 200)]
        tool.finish()
        self.assertEqual(len(tool.points), 2)
        self.assertFalse(redraws)
        self.assertIn("deconstruction", messages[-1])
