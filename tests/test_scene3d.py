"""Scene registration and road mesh checks without a display."""

import importlib.util
import unittest
from math import hypot
from types import SimpleNamespace

from models import Road


@unittest.skipUnless(importlib.util.find_spec("panda3d"), "Panda3D is required")
class Scene3DTests(unittest.TestCase):
    def test_custom_roundabout_surfaces_and_car_use_shared_route_geometry(self) -> None:
        from panda3d.core import GeomVertexReader, NodePath
        from city import CityMap, Terrain
        from mobility import VEHICLE_LAYER
        from models import IntersectionKind
        from ui.scene3d import SceneRegistry, draw_intersection, update_road_vehicle_layer
        from vehicle import VehicleAppearance

        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (200, 100)])
        city.add_road([(100, 0), (100, 200)])
        junction = city.standard_intersections[0]
        junction.kind = IntersectionKind.ROUNDABOUT
        junction.roundabout_ring_radius = 42.0
        junction.roundabout_island_radius = 25.0
        junction.roundabout_outer_band_width = 5.0
        city.rebuild_mobility_network()

        root = NodePath("scene")
        registry = SceneRegistry(root)
        registry.register(type(junction), draw_intersection)
        registry.replace([junction])

        def surface_radii(name: str) -> set[float]:
            surface = root.find(f"**/{name}")
            self.assertFalse(surface.isEmpty())
            data = surface.node().getGeom(0).getVertexData()
            reader = GeomVertexReader(data, "vertex")
            return {
                round(hypot((vertex := reader.getData3()).x - 100, vertex.y - 100), 3)
                for _ in range(data.getNumRows())
            }

        self.assertEqual(surface_radii("roundabout-island"), {0.0, 25.0})
        self.assertEqual(surface_radii("roundabout-outer-band"), {60.0, 65.0})

        graph = city.mobility.layers[VEHICLE_LAYER].graph
        arc = next(
            transition.edge.value
            for node in graph.nodes
            for transition in graph.transitions_from(node)
            if transition.edge.kind == "lane"
            and transition.edge.value.road_id == f"roundabout:{junction.id}"
        )
        position = arc.points[len(arc.points) // 2]
        car = type("Car", (), {
            "id": "ring-car", "position": position, "heading": (1.0, 0.0),
            "color": "#ff0000", "length": 14.0, "width": 6.0,
            "speed": 10.0, "appearance": VehicleAppearance(),
        })()
        vehicles = {}
        update_road_vehicle_layer([car], city, root, vehicles, 0.0)

        self.assertAlmostEqual(vehicles["ring-car"].getX(), position[0], delta=1e-4)
        self.assertAlmostEqual(vehicles["ring-car"].getY(), position[1], delta=1e-4)

    def test_car_layer_tracks_position_heading_and_removes_finished_cars(self) -> None:
        from panda3d.core import NodePath
        from city import CityMap, Terrain
        from ui.scene3d import update_road_vehicle_layer
        from vehicle import VehicleAppearance

        root = NodePath("vehicles")
        city = CityMap(terrain=Terrain(trees=[]))
        car = type("Car", (), {
            "id": "car-1", "position": (12.0, 34.0),
            "heading": (1.0, 0.0), "color": "#ff0000",
            "length": 14.0, "width": 6.0,
            "speed": 10.0, "appearance": VehicleAppearance(),
        })()
        vehicles = {}

        update_road_vehicle_layer([car], city, root, vehicles, 2.0)

        self.assertEqual(len(vehicles), 1)
        node = vehicles["car-1"]
        self.assertEqual((node.getX(), node.getY(), node.getZ()), (12.0, 34.0, 0.0))
        self.assertAlmostEqual(node.getH(), -90.0)
        self.assertEqual(node.findAllMatches("**/+GeomNode").getNumPaths(), 9)

        update_road_vehicle_layer([], city, root, vehicles, 2.1)
        self.assertTrue(node.isEmpty())
        self.assertEqual(vehicles, {})

    def test_shared_vehicle_layer_draws_loaded_material_and_crew_trucks(self) -> None:
        from panda3d.core import NodePath
        from city import CityMap, Terrain
        from ui.scene3d import update_road_vehicle_layer
        from vehicle import VehicleAppearance

        city = CityMap(terrain=Terrain(trees=[]))
        city.add_road([(0, 20), (120, 20)])
        material = SimpleNamespace(
            id="material-1", position=(35, 20), heading=(1, 0),
            length=18, width=8, speed=10, color="#37e6ff",
            appearance=VehicleAppearance(
                kind="construction_truck", shape="material_truck",
                cargo_key="stone", load_fraction=0.5,
            ),
        )
        crew = SimpleNamespace(
            id="crew-1", position=(55, 20), heading=(1, 0),
            length=20, width=8, speed=10, color="#ffb000",
            appearance=VehicleAppearance(
                kind="construction_truck", shape="crew_truck", workers=2,
            ),
        )
        root = NodePath("vehicles")
        nodes = {}

        update_road_vehicle_layer([material, crew], city, root, nodes, 0.0)

        material_node = nodes["material-1"]
        self.assertAlmostEqual(material_node.getX(), 35.0)
        self.assertAlmostEqual(material_node.getH(), -90.0)
        self.assertFalse(material_node.find("**/flatbed").isEmpty())
        self.assertFalse(material_node.find("**/cargo-stone-0").isEmpty())
        crew_node = nodes["crew-1"]
        self.assertFalse(crew_node.find("**/crew-compartment").isEmpty())
        self.assertFalse(crew_node.find("**/crew-roof-marker-1").isEmpty())

        update_road_vehicle_layer([], city, root, nodes, 0.0)
        self.assertTrue(material_node.isEmpty())
        self.assertTrue(crew_node.isEmpty())
        self.assertEqual(nodes, {})

    def test_city_trees_appear_at_existing_positions_in_3d(self) -> None:
        from panda3d.core import NodePath
        from city import CityMap, Terrain
        from ui.scene3d import SceneRegistry, TerrainFeature, TreeFeature, draw_terrain, draw_tree
        from ui.view3d import PandaWorldView

        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(setBackgroundColor=lambda *_color: None)
        view.city = None
        view.orbit = type("Orbit", (), {"target": (0, 0, 0)})()
        view.scene = SceneRegistry(NodePath("city"))
        view.scene.register(TerrainFeature, draw_terrain)
        view.scene.register(TreeFeature, draw_tree)
        view._apply_camera = lambda: None
        city = CityMap(terrain=Terrain(trees=[
            (100, 200), (300, 400), (500, 600), (700, 800),
        ]))

        view.show_city(city)

        trees = view.scene.root.findAllMatches("**/tree:*")
        self.assertEqual(trees.getNumPaths(), 4)
        by_position = {
            (tree.getX(), tree.getY()): (
                tree.getName(), tree.findAllMatches("**/+GeomNode").getNumPaths(),
            )
            for tree in trees
        }
        self.assertEqual(by_position, {
            (100, 200): ("tree:redwood", 10),
            (300, 400): ("tree:pine", 2),
            (500, 600): ("tree:pine", 2),
            (700, 800): ("tree:pine", 2),
        })
        city.terrain.trees.pop()
        view.show_city(city)
        self.assertEqual(view.scene.root.findAllMatches("**/tree:*").getNumPaths(), 3)

    def test_registered_road_produces_visible_mesh_node(self) -> None:
        from panda3d.core import NodePath
        from ui.scene3d import SceneRegistry, draw_road

        root = NodePath("test scene")
        registry = SceneRegistry(root)
        registry.register(Road, draw_road)
        road = Road("r1", "Ramp", [(0, 0), (100, 0)], elevations=[0, 20])

        registry.replace([road])

        node = root.find("**/road:r1")
        self.assertFalse(node.isEmpty())
        self.assertGreater(node.findAllMatches("**/+GeomNode").getNumPaths(), 0)

    def test_city_scene_draws_a_marker_for_each_regional_land_port(self) -> None:
        from panda3d.core import NodePath
        from city import CityMap, Terrain
        from ui.scene3d import (
            RegionalLandPortFeature, SceneRegistry, TerrainFeature,
            draw_regional_land_port, draw_terrain,
        )
        from ui.view3d import PandaWorldView

        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(setBackgroundColor=lambda *_color: None)
        view.city = None
        view.orbit = type("Orbit", (), {"target": (0, 0, 0)})()
        view.scene = SceneRegistry(NodePath("city"))
        view.scene.register(TerrainFeature, draw_terrain)
        view.scene.register(RegionalLandPortFeature, draw_regional_land_port)
        view._apply_camera = lambda: None
        city = CityMap(width=500, height=300, terrain=Terrain(trees=[]))
        city.add_road([(0, 100), (300, 100)])

        view.show_city(city)

        marker = view.scene.root.find("**/regional-land-port:0")
        self.assertFalse(marker.isEmpty())
        self.assertEqual((marker.getX(), marker.getY()), (0, 100))
        self.assertGreater(marker.findAllMatches("**/+GeomNode").getNumPaths(), 0)

    def test_new_world_3d_camera_targets_the_regional_connector(self) -> None:
        from panda3d.core import NodePath
        from city import CityMap, Terrain
        from land_ports import ensure_western_land_port
        from ui.scene3d import SceneRegistry, TerrainFeature, draw_terrain
        from ui.view3d import PandaWorldView

        city = CityMap(terrain=Terrain(trees=[]))
        ensure_western_land_port(city)
        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(setBackgroundColor=lambda *_color: None)
        view.city = None
        view.orbit = type("Orbit", (), {"target": (0, 0, 0)})()
        view.scene = SceneRegistry(NodePath("city"))
        view.scene.register(TerrainFeature, draw_terrain)
        view._apply_camera = lambda: None

        view.show_city(city)

        self.assertEqual(view.orbit.target, (250.0, 1750.0, 0))

    def test_city_scene_draws_buildings_with_construction_scaffolding(self) -> None:
        from panda3d.core import NodePath
        from city import Building, CityMap, Parcel, Terrain
        from models import BuildablePhase, WorkType
        from ui.scene3d import (
            SceneRegistry, TerrainFeature, draw_building, draw_terrain,
        )
        from ui.view3d import PandaWorldView

        view = PandaWorldView.__new__(PandaWorldView)
        view.base = SimpleNamespace(setBackgroundColor=lambda *_color: None)
        view.city = None
        view.orbit = type("Orbit", (), {"target": (0, 0, 0)})()
        view.scene = SceneRegistry(NodePath("city"))
        view.scene.register(TerrainFeature, draw_terrain)
        view.scene.register(Building, draw_building)
        view._apply_camera = lambda: None
        city = CityMap(terrain=Terrain(trees=[]))
        building = Building(
            "House", Parcel(100, 120, 40, 30),
            phase=BuildablePhase.UNDER_CONSTRUCTION,
        )
        building.begin_work(WorkType.CONSTRUCTION, 100)
        building.perform_work(40)
        city.buildings.append(building)

        view.show_city(city)

        node = view.scene.root.find(f"**/building:{building.id}")
        self.assertFalse(node.isEmpty())
        self.assertFalse(node.find("**/building-body").isEmpty())
        self.assertFalse(node.find("**/construction-scaffold").isEmpty())

        building.perform_work(60)
        view.show_city(city)
        completed = view.scene.root.find(f"**/building:{building.id}")
        self.assertTrue(completed.find("**/construction-scaffold").isEmpty())
        self.assertFalse(completed.find("**/building-roof").isEmpty())
        self.assertFalse(completed.find("**/building-windows").isEmpty())

    def test_roundabout_draws_colored_outer_band(self) -> None:
        from panda3d.core import NodePath
        from models import Intersection, IntersectionKind
        from ui.scene3d import draw_intersection

        root = NodePath("scene")
        junction = Intersection(
            "r", (100, 100), radius=24, kind=IntersectionKind.ROUNDABOUT,
        )

        draw_intersection(junction, root)

        band = root.find("**/roundabout-outer-band")
        self.assertFalse(band.isEmpty())
        color = band.getColor()
        self.assertAlmostEqual(color.x, 0.776, delta=0.002)
        self.assertAlmostEqual(color.y, 0.663, delta=0.002)
        self.assertAlmostEqual(color.z, 0.420, delta=0.002)

    def test_new_feature_type_uses_registry_without_camera_changes(self) -> None:
        from panda3d.core import NodePath
        from ui.scene3d import SceneRegistry

        class Pipe:
            id = "future-pipe"

        root = NodePath("test scene")
        registry = SceneRegistry(root)
        registry.register(Pipe, lambda item, parent: parent.attachNewNode(f"pipe:{item.id}"))

        registry.replace([Pipe()])

        self.assertFalse(root.find("**/pipe:future-pipe").isEmpty())

    def test_elevated_road_has_supports_but_ground_road_does_not(self) -> None:
        from panda3d.core import NodePath
        from ui.scene3d import draw_road

        root = NodePath("test scene")
        bridge = Road("bridge", "Bridge", [(0, 0), (100, 0)], elevations=[20, 20])
        ground = Road("ground", "Ground", [(0, 30), (100, 30)])

        bridge_node = draw_road(bridge, root)
        ground_node = draw_road(ground, root)

        self.assertGreater(bridge_node.findAllMatches("**/support-*").getNumPaths(), 0)
        self.assertEqual(ground_node.findAllMatches("**/support-*").getNumPaths(), 0)


if __name__ == "__main__":
    unittest.main()
