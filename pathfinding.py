"""Transport-agnostic weighted graphs and A* pathfinding."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import count
from math import isfinite
from typing import Generic, TypeVar


NodeT = TypeVar("NodeT", bound=Hashable)
EdgeT = TypeVar("EdgeT")


@dataclass(frozen=True)
class Transition(Generic[NodeT, EdgeT]):
    """One directed, weighted transition exposed to a pathfinder."""

    destination: NodeT
    cost: float
    edge: EdgeT


@dataclass(frozen=True)
class Path(Generic[NodeT, EdgeT]):
    """A found sequence of nodes and the edges joining them."""

    nodes: tuple[NodeT, ...]
    edges: tuple[EdgeT, ...]
    cost: float


@dataclass
class DirectedGraph(Generic[NodeT, EdgeT]):
    """A small adjacency-list graph usable by any routing domain."""

    _adjacency: dict[NodeT, list[Transition[NodeT, EdgeT]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @property
    def nodes(self) -> tuple[NodeT, ...]:
        return tuple(self._adjacency)

    def add_node(self, node: NodeT) -> None:
        self._adjacency.setdefault(node, [])

    def add_edge(self, source: NodeT, destination: NodeT, cost: float, edge: EdgeT) -> None:
        _validate_cost(cost, "Edge cost")
        self.add_node(source)
        self.add_node(destination)
        self._adjacency[source].append(Transition(destination, float(cost), edge))

    def transitions_from(self, node: NodeT) -> tuple[Transition[NodeT, EdgeT], ...]:
        return tuple(self._adjacency.get(node, ()))

    def extend(self, other: DirectedGraph[NodeT, EdgeT]) -> None:
        """Append another graph, retaining parallel edges between the same nodes."""
        for node in other.nodes:
            self.add_node(node)
            for transition in other.transitions_from(node):
                self.add_edge(node, transition.destination, transition.cost, transition.edge)

    def find_path(
        self,
        start: NodeT,
        goal: NodeT,
        heuristic: Callable[[NodeT], float] | None = None,
    ) -> Path[NodeT, EdgeT] | None:
        estimate = heuristic or (lambda _node: 0.0)
        return astar(
            start,
            lambda node: node == goal,
            lambda node, _cost: self.transitions_from(node),
            estimate,
        )


def astar(
    start: NodeT,
    is_goal: Callable[[NodeT], bool],
    expand: Callable[[NodeT, float], Iterable[Transition[NodeT, EdgeT]]],
    heuristic: Callable[[NodeT], float],
) -> Path[NodeT, EdgeT] | None:
    """Find a minimum-cost path through arbitrary states and transitions.

    ``expand`` receives the node and its accumulated cost. Domains with
    time-dependent costs should encode any state that affects future
    transitions in the node itself.
    """
    start_estimate = float(heuristic(start))
    _validate_cost(start_estimate, "Heuristic")

    sequence = count()
    frontier: list[tuple[float, int, float, NodeT]] = []
    heappush(frontier, (start_estimate, next(sequence), 0.0, start))
    best_cost: dict[NodeT, float] = {start: 0.0}
    previous: dict[NodeT, tuple[NodeT, EdgeT]] = {}

    while frontier:
        _priority, _order, current_cost, current = heappop(frontier)
        if current_cost != best_cost.get(current):
            continue
        if is_goal(current):
            return _reconstruct_path(start, current, current_cost, previous)

        for transition in expand(current, current_cost):
            step_cost = float(transition.cost)
            _validate_cost(step_cost, "Transition cost")
            candidate_cost = current_cost + step_cost
            if candidate_cost >= best_cost.get(transition.destination, float("inf")):
                continue
            estimate = float(heuristic(transition.destination))
            _validate_cost(estimate, "Heuristic")
            best_cost[transition.destination] = candidate_cost
            previous[transition.destination] = (current, transition.edge)
            heappush(
                frontier,
                (candidate_cost + estimate, next(sequence), candidate_cost, transition.destination),
            )

    return None


def _reconstruct_path(
    start: NodeT,
    goal: NodeT,
    cost: float,
    previous: dict[NodeT, tuple[NodeT, EdgeT]],
) -> Path[NodeT, EdgeT]:
    nodes = [goal]
    edges: list[EdgeT] = []
    current = goal
    while current != start:
        parent, edge = previous[current]
        nodes.append(parent)
        edges.append(edge)
        current = parent
    nodes.reverse()
    edges.reverse()
    return Path(tuple(nodes), tuple(edges), cost)


def _validate_cost(value: float, label: str) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a finite, nonnegative number")
