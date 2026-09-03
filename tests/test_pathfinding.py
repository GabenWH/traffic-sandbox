"""Tests for domain-independent A* pathfinding."""

import unittest

from pathfinding import DirectedGraph, Transition, astar


class AStarTests(unittest.TestCase):
    def test_finds_the_lowest_cost_path_with_opaque_edge_values(self) -> None:
        graph: DirectedGraph[str, object] = DirectedGraph()
        walking_edge = {"kind": "walk"}
        transit_edge = {"kind": "ride"}
        graph.add_edge("home", "stop", 4, walking_edge)
        graph.add_edge("stop", "work", 3, transit_edge)
        graph.add_edge("home", "work", 10, {"kind": "drive"})

        path = graph.find_path("home", "work", lambda node: {"home": 6, "stop": 2, "work": 0}[node])

        assert path is not None
        self.assertEqual(path.nodes, ("home", "stop", "work"))
        self.assertEqual(path.edges, (walking_edge, transit_edge))
        self.assertEqual(path.cost, 7)

    def test_accepts_a_goal_predicate_and_accumulated_cost_expander(self) -> None:
        seen_costs: list[float] = []

        def expand(node: int, cost: float) -> list[Transition[int, str]]:
            seen_costs.append(cost)
            return [] if node >= 2 else [Transition(node + 1, 1, "step")]

        path = astar(0, lambda node: node >= 2, expand, lambda node: 2 - node)

        assert path is not None
        self.assertEqual(path.nodes, (0, 1, 2))
        self.assertEqual(seen_costs, [0.0, 1.0])

    def test_returns_none_when_no_path_exists(self) -> None:
        graph: DirectedGraph[str, str] = DirectedGraph()
        graph.add_node("start")
        graph.add_node("goal")

        self.assertIsNone(graph.find_path("start", "goal"))

    def test_rejects_negative_costs(self) -> None:
        graph: DirectedGraph[str, str] = DirectedGraph()

        with self.assertRaisesRegex(ValueError, "nonnegative"):
            graph.add_edge("a", "b", -1, "bad")


if __name__ == "__main__":
    unittest.main()
