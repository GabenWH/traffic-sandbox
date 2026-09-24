"""Construction status and map presentation tests."""

from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from city import Building, CityMap, Parcel, Terrain
from construction import (
    UnlimitedConstructionProvider,
)
from models import BuildablePhase, WorkType
from land_ports import LAND_PORT_CONNECTOR_NAME
from resources import ResourceSpec
from ui.app import FreewaySimulator
from ui.files import FileActionsMixin
from ui.renderer import RendererMixin
from ui.viewport import Viewport, city_builder_viewport_origin
from ui_tools.tools.inspect_tool import inspection_rows
from vehicle import VehicleAppearance


class ConstructionPresentationTests(unittest.TestCase):
    def test_empty_world_start_view_shows_the_western_connector(self) -> None:
        city = CityMap(width=5000, height=3500, terrain=Terrain(trees=[]))
        from land_ports import ensure_western_land_port
        ensure_western_land_port(city)
        connector = next(
            road for road in city.roads if road.name == LAND_PORT_CONNECTOR_NAME
        )
        camera_x, camera_y = city_builder_viewport_origin(city.height)
        viewport = Viewport(camera_x, camera_y)

        port_screen = viewport.world_to_screen(connector.centerline[0])
        road_end_screen = viewport.world_to_screen(connector.centerline[-1])

        self.assertGreaterEqual(port_screen[0], 0)
        self.assertLess(road_end_screen[0], 1000)
        self.assertAlmostEqual(port_screen[1], 320)

    def test_regional_land_port_is_drawn_as_a_boundary_marker(self) -> None:
        city = CityMap(width=500, height=300, terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (300, 100)])

        class Canvas:
            def __init__(self) -> None:
                self.items = []

            def create_line(self, *args, **kwargs):
                self.items.append(("line", args, kwargs))

            def create_oval(self, *args, **kwargs):
                self.items.append(("oval", args, kwargs))

            def create_text(self, *args, **kwargs):
                self.items.append(("text", args, kwargs))

        host = SimpleNamespace(
            city_map=city,
            canvas=Canvas(),
            camera_zoom=1.0,
            world_to_screen=lambda point: point,
        )

        RendererMixin._draw_regional_land_ports(host)

        self.assertTrue(any(
            kind == "text" and kwargs.get("text") == "REGIONAL LAND PORT"
            for kind, _args, kwargs in host.canvas.items
        ))

    def test_inspector_shows_cumulative_construction_status(self) -> None:
        building = Building(
            "House",
            Parcel(100, 100, 40, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
            construction_needs={"lumber": 10},
            construction_workers=2,
            construction_work=100,
        )
        building.record_construction_delivery("lumber", 4)
        building.assigned_workers = 1
        host = SimpleNamespace(
            unit_system="metric",
            construction_simulation=SimpleNamespace(
                resources={
                    "lumber": ResourceSpec("lumber", "Lumber", "m³", 500, 1),
                },
            ),
        )

        _title, rows = inspection_rows(host, building)
        rows_by_label = {row.label: row for row in rows}

        self.assertNotIn("Deliver resource", rows_by_label)
        self.assertTrue(all(row.editor is None for row in rows))
        self.assertEqual(
            rows_by_label["Lumber (required / delivered / remaining)"].value,
            "10 / 4 / 6 m³",
        )
        self.assertEqual(rows_by_label["Construction workers"].value, "1 / 2 assigned")
        self.assertEqual(rows_by_label["Construction work"].value, "0 / 100 worker-seconds")

        building.record_construction_delivery("lumber", 6)
        building.assigned_workers = 2
        building.begin_work(WorkType.CONSTRUCTION, 100)
        building.perform_work(25)
        _title, rows = inspection_rows(host, building)
        rows_by_label = {row.label: row for row in rows}
        self.assertEqual(
            rows_by_label["Lumber (required / delivered / remaining)"].value,
            "10 / 10 / 0 m³",
        )
        self.assertEqual(rows_by_label["Construction workers"].value, "2 / 2 assigned")
        self.assertEqual(rows_by_label["Construction work"].value, "25 / 100 worker-seconds")
        building.perform_work(75)
        building.assigned_workers = 0
        _title, rows = inspection_rows(host, building)
        rows_by_label = {row.label: row for row in rows}
        self.assertEqual(rows_by_label["Construction work"].value, "100 / 100 worker-seconds")

    def test_under_construction_building_has_a_distinct_outline(self) -> None:
        class Canvas:
            def __init__(self) -> None:
                self.rectangles = []

            def winfo_width(self):
                return 1000

            def winfo_height(self):
                return 700

            def create_rectangle(self, *args, **kwargs):
                self.rectangles.append((args, kwargs))

            def create_text(self, *_args, **_kwargs):
                pass

        class Host(RendererMixin):
            canvas = Canvas()
            city_map = CityMap(terrain=Terrain(trees=[]))
            camera_zoom = 1.0

            @staticmethod
            def world_to_screen(point):
                return point

        building = Building(
            "House",
            Parcel(100, 100, 40, 30),
            color="#447799",
            phase=BuildablePhase.UNDER_CONSTRUCTION,
        )
        Host.city_map.buildings.append(building)

        Host()._draw_buildings()

        footprint = Host.canvas.rectangles[-1][1]
        self.assertEqual(footprint["fill"], building.color)
        self.assertNotEqual(footprint["outline"], "#eee4d5")
        self.assertIn("dash", footprint)

    def test_shared_vehicle_renderer_draws_and_clears_crew_trucks(self) -> None:
        class Canvas:
            def __init__(self) -> None:
                self.deleted = []
                self.polygons = []

            def delete(self, tag):
                self.deleted.append(tag)

            def create_polygon(self, *args, **kwargs):
                self.polygons.append((args, kwargs))

        vehicle = SimpleNamespace(
            id="trip-1",
            position=(35, 20),
            heading=(1, 0),
            speed=10,
            length=20,
            width=8,
            color="#ffb000",
            appearance=VehicleAppearance(
                kind="construction_truck", shape="crew_truck",
                visual_key="crew_truck", workers=2,
            ),
        )

        class Host(RendererMixin):
            canvas = Canvas()
            road_vehicles = SimpleNamespace(vehicles=[vehicle])
            camera_zoom = 2.0

            @staticmethod
            def world_to_screen(point):
                return point

        host = Host()

        host.draw_road_vehicles()

        parts = {
            next(tag.split(":", 1)[1] for tag in options["tags"]
                 if tag.startswith("construction-truck-part:")): coords
            for coords, options in host.canvas.polygons
        }
        self.assertGreater(sum(parts["cab"][::2]) / 4,
                           sum(parts["crew-compartment"][::2]) / 4)
        self.assertIn("crew-roof-marker-1", parts)
        self.assertTrue(all(
            "construction_trucks" in options["tags"]
            for _coords, options in host.canvas.polygons
        ))
        host.road_vehicles.vehicles.clear()
        host.draw_road_vehicles()
        self.assertEqual(host.canvas.deleted, ["construction_trucks", "construction_trucks"])
        self.assertGreater(len(host.canvas.polygons), 1)

    def test_app_construction_tick_uses_speed_and_redraws_phase_changes(self) -> None:
        building = Building(
            "House",
            Parcel(100, 100, 40, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
        )
        city = CityMap(terrain=Terrain(trees=[]))
        city.buildings.append(building)

        class ConstructionSimulation:
            def __init__(self):
                self.elapsed = []

            def update(self, _city_map, elapsed_seconds):
                self.elapsed.append(elapsed_seconds)
                building.phase = BuildablePhase.OPERATIONAL

        class Host:
            running = True
            simulation_speed = 2.5
            city_map = city
            construction_simulation = ConstructionSimulation()

            def __init__(self):
                self.redraws = 0
                self.vehicle_draws = 0

            def redraw_world(self):
                self.redraws += 1

            def draw_road_vehicles(self):
                self.vehicle_draws += 1

        host = Host()

        FreewaySimulator._update_construction(host, 0.4)

        self.assertEqual(host.construction_simulation.elapsed, [1.0])
        self.assertEqual(host.redraws, 1)
        self.assertEqual(host.vehicle_draws, 1)

    def test_new_world_clears_runtime_construction_trips(self) -> None:
        class ConstructionSimulation:
            def __init__(self):
                self.cleared = 0

            def clear_trips(self):
                self.cleared += 1

        class Host:
            construction_simulation = ConstructionSimulation()
            tools = []

            def clear_cars(self):
                pass

            def restore_3d_camera(self, _state):
                pass

            def select_lane(self, _lane):
                pass

            def reset_camera(self):
                pass

        host = Host()
        with patch("ui.files.messagebox.askyesno", return_value=True):
            FileActionsMixin.new_world(host)

        self.assertEqual(host.construction_simulation.cleared, 1)
        self.assertTrue(any(
            road.name == LAND_PORT_CONNECTOR_NAME for road in host.city_map.roads
        ))

    def test_successful_load_clears_runtime_construction_trips(self) -> None:
        loaded_city = CityMap(terrain=Terrain(trees=[]))

        class ConstructionSimulation:
            def __init__(self):
                self.cleared = 0

            def clear_trips(self):
                self.cleared += 1

        class Host:
            construction_simulation = ConstructionSimulation()
            tools = []

            def clear_cars(self):
                pass

            def select_lane(self, _lane):
                pass

            def redraw_world(self):
                pass

            def restore_3d_camera(self, _state):
                pass

        host = Host()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "world.json"
            path.write_text("{}", encoding="utf-8")
            with (
                patch("ui.files.filedialog.askopenfilename", return_value=str(path)),
                patch(
                    "ui.files.world_from_dict",
                    return_value=SimpleNamespace(
                        city_map=loaded_city,
                        unit_system="metric",
                        camera_x=0,
                        camera_y=0,
                        camera_zoom=1,
                        camera_3d=None,
                    ),
                ),
            ):
                FileActionsMixin.load_state(host)

        self.assertEqual(host.construction_simulation.cleared, 1)
        self.assertIs(host.city_map, loaded_city)
        self.assertTrue(any(
            road.name == LAND_PORT_CONNECTOR_NAME for road in loaded_city.roads
        ))


if __name__ == "__main__":
    unittest.main()
