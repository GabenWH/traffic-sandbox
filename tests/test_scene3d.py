"""Scene registration and road mesh checks without a display."""

import importlib.util
import unittest

from models import Road


@unittest.skipUnless(importlib.util.find_spec("panda3d"), "Panda3D is required")
class Scene3DTests(unittest.TestCase):
    def test_car_layer_tracks_position_heading_and_removes_finished_cars(self) -> None:
        from panda3d.core import NodePath
        from ui.scene3d import update_car_layer

        root = NodePath("vehicles")
        car = type("Car", (), {
            "id": "car-1", "position": (12.0, 34.0),
            "heading": (1.0, 0.0), "color": "#ff0000",
            "length": 14.0, "width": 6.0,
        })()
        vehicles = {}

        update_car_layer([car], root, vehicles, 2.0)

        self.assertEqual(len(vehicles), 1)
        node = vehicles["car-1"]
        self.assertEqual((node.getX(), node.getY(), node.getZ()), (12.0, 34.0, 0.0))
        self.assertAlmostEqual(node.getH(), -90.0)
        self.assertEqual(node.findAllMatches("**/+GeomNode").getNumPaths(), 9)

        update_car_layer([], root, vehicles, 2.1)
        self.assertTrue(node.isEmpty())
        self.assertEqual(vehicles, {})

    def test_city_trees_appear_at_existing_positions_in_3d(self) -> None:
        from panda3d.core import NodePath
        from city import CityMap, Terrain
        from ui.scene3d import SceneRegistry, TerrainFeature, TreeFeature, draw_terrain, draw_tree
        from ui.view3d import PandaWorldView

        view = PandaWorldView.__new__(PandaWorldView)
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
