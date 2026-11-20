"""Opt-in prototype for finite resources, recipes, and road-freight handoffs.

This is an economy/event layer, not a vehicle mover. Call process() at coarse
scheduled intervals, reserve_delivery() when deciding transport, pickup() when
a truck loads, and deliver() only after the existing road engine reports arrival.
Nodes may reuse the Building.inventory ResourceInventory object directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from math import isfinite
from pathlib import Path
from typing import Mapping

from models import ResourceInventory

CATALOG_PATH = Path(__file__).with_name("ui_tools") / "economy_resources.json"
KINDS = frozenset({"cargo", "utility", "emission"})
EPS = 1e-9


class EconomyError(ValueError):
    """Invalid resource definitions or impossible economy operations."""


def _amount(value: object, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        raise EconomyError("Amounts must be finite numbers")
    if value < 0 or (value == 0 and not allow_zero):
        raise EconomyError("Amounts must be positive")
    return float(value)


def _quantities(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        raise EconomyError("Resource quantities must be an object")
    if any(not isinstance(k, str) or not k.strip() for k in value):
        raise EconomyError("Resource IDs must be nonempty strings")
    return {k: _amount(v) for k, v in value.items()}


@dataclass(frozen=True)
class EconomyResource:
    id: str
    name: str
    unit: str
    kind: str
    mass_kg_per_unit: float | None = None
    volume_m3_per_unit: float | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(x, str) or not x.strip() for x in (self.id, self.name, self.unit)):
            raise EconomyError("Resource identity, name, and unit must be nonempty")
        if self.kind not in KINDS:
            raise EconomyError(f"Invalid resource kind: {self.kind!r}")
        if self.kind == "cargo":
            _amount(self.mass_kg_per_unit)
            _amount(self.volume_m3_per_unit)
        elif self.mass_kg_per_unit is not None or self.volume_m3_per_unit is not None:
            raise EconomyError("Only cargo has truck weight and volume")


@dataclass(frozen=True)
class Recipe:
    id: str
    inputs: Mapping[str, float]
    outputs: Mapping[str, float]


@dataclass
class ResourceNode:
    id: str
    inventory: ResourceInventory = field(default_factory=ResourceInventory)
    recipes: tuple[str, ...] = ()
    unlimited_imports: frozenset[str] = frozenset()


@dataclass
class FreightOrder:
    id: int
    source_id: str
    destination_id: str
    resource_id: str
    amount: float
    state: str = "reserved"  # reserved -> in_transit -> delivered, or cancelled
    from_external: bool = False


class ResourceEconomy:
    """Coarse-grained resource economy; independent of simulation frame rate.

    External ports are infinite sources for explicitly allowed cargo; regular
    nodes have finite inventory. All inventories remain ResourceInventory,
    matching existing buildings. Trucks receive one cargo type per order,
    consistent with existing construction shipments.
    """

    def __init__(self, resources: Mapping[str, EconomyResource], recipes: Mapping[str, Recipe]):
        self.resources = dict(resources)
        self.recipes = dict(recipes)
        self.nodes: dict[str, ResourceNode] = {}
        self.orders: dict[int, FreightOrder] = {}
        self._reserved: dict[tuple[str, str], float] = {}
        self._next_order_id = 1
        self.emissions: dict[str, float] = {}
        for recipe in self.recipes.values():
            if not recipe.id or not recipe.outputs:
                raise EconomyError("Recipes require IDs and at least one output")
            for resource_id, quantity in (*recipe.inputs.items(), *recipe.outputs.items()):
                if resource_id not in self.resources:
                    raise EconomyError(f"Recipe {recipe.id} references unknown resource {resource_id}")
                _amount(quantity)
                if resource_id in recipe.inputs and self.resources[resource_id].kind == "emission":
                    raise EconomyError("Emissions cannot be recipe inputs")

    @classmethod
    def load(cls, path: str | Path = CATALOG_PATH) -> ResourceEconomy:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise EconomyError(f"Cannot load economy catalog: {error}") from error
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise EconomyError("Economy catalog must have version 1")
        resources: dict[str, EconomyResource] = {}
        recipes: dict[str, Recipe] = {}
        for entry in data.get("resources", []):
            resource = EconomyResource(**entry)
            if resource.id in resources:
                raise EconomyError(f"Duplicate resource {resource.id}")
            resources[resource.id] = resource
        for entry in data.get("recipes", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise EconomyError("Recipe needs a string ID")
            recipe = Recipe(entry["id"], _quantities(entry.get("inputs", {})), _quantities(entry.get("outputs", {})))
            if recipe.id in recipes:
                raise EconomyError(f"Duplicate recipe {recipe.id}")
            recipes[recipe.id] = recipe
        return cls(resources, recipes)

    def add_node(self, node: ResourceNode) -> None:
        if not node.id or node.id in self.nodes:
            raise EconomyError("Node ID must be unique and nonempty")
        if set(node.recipes) - set(self.recipes):
            raise EconomyError("Node references an unknown recipe")
        if any(r not in self.resources or self.resources[r].kind != "cargo" for r in node.unlimited_imports):
            raise EconomyError("External imports must name known physical cargo")
        for r, quantity in node.inventory.amounts.items():
            if r not in self.resources or self.resources[r].kind == "emission":
                raise EconomyError("Inventory contains unknown or emission resource")
            _amount(quantity, allow_zero=True)
        self.nodes[node.id] = node

    def available(self, node_id: str, resource_id: str) -> float:
        node = self.nodes[node_id]
        if resource_id not in self.resources:
            raise EconomyError("Unknown resource")
        if resource_id in node.unlimited_imports:
            return float("inf")
        return max(0.0, node.inventory.amounts.get(resource_id, 0.0) -
                   self._reserved.get((node_id, resource_id), 0.0))

    def process(self, node_id: str, recipe_id: str, batches: float = 1) -> bool:
        """Execute one scheduled production event, atomically if inputs suffice.

        Utility inputs temporarily use the same inventory ledger, allowing
        later power/water network adapters without inventing truck deliveries.
        Emission outputs accumulate separately and never become physical stock.
        """
        node = self.nodes[node_id]
        if recipe_id not in node.recipes:
            raise EconomyError("Recipe is not enabled at this node")
        batches = _amount(batches)
        recipe = self.recipes[recipe_id]
        if any(self.available(node_id, r) + EPS < qty * batches
               for r, qty in recipe.inputs.items()):
            return False
        for r, qty in recipe.inputs.items():
            state, consumed = node.inventory.consume(r, qty * batches)
            if consumed + EPS < qty * batches:
                raise RuntimeError(f"Unexpected inventory shortage for {r}")
        for r, qty in recipe.outputs.items():
            amount = qty * batches
            if self.resources[r].kind == "emission":
                self.emissions[r] = self.emissions.get(r, 0.0) + amount
            else:
                node.inventory.add(r, amount)
        return True

    def reserve_delivery(self, source_id: str, destination_id: str, resource_id: str,
                         requested: float, *, max_payload_kg: float,
                         max_cargo_m3: float) -> FreightOrder | None:
        """Reserve one partial truckload. This does not teleport or route a truck."""
        if source_id not in self.nodes or destination_id not in self.nodes or source_id == destination_id:
            raise EconomyError("Freight needs two distinct known nodes")
        resource = self.resources.get(resource_id)
        if resource is None or resource.kind != "cargo":
            raise EconomyError("Only physical cargo travels on trucks")
        requested = _amount(requested)
        payload = _amount(max_payload_kg)
        volume = _amount(max_cargo_m3)
        amount = min(requested, payload / resource.mass_kg_per_unit,
                     volume / resource.volume_m3_per_unit,
                     self.available(source_id, resource_id))
        if amount <= EPS:
            return None
        external = resource_id in self.nodes[source_id].unlimited_imports
        order = FreightOrder(self._next_order_id, source_id, destination_id,
                             resource_id, amount, from_external=external)
        self.orders[order.id] = order
        self._next_order_id += 1
        if not external:
            key = (source_id, resource_id)
            self._reserved[key] = self._reserved.get(key, 0.0) + amount
        return order

    def pickup(self, order_id: int) -> FreightOrder:
        """Call when a truck is loaded and begins its routed journey."""
        order = self.orders[order_id]
        if order.state != "reserved":
            raise EconomyError("Only reserved freight can be picked up")
        if not order.from_external:
            node = self.nodes[order.source_id]
            if node.inventory.amounts.get(order.resource_id, 0.0) + EPS < order.amount:
                raise EconomyError("Reserved stock was externally modified")
            _, taken = node.inventory.consume(order.resource_id, order.amount)
            if taken + EPS < order.amount:
                raise RuntimeError("Reserved stock disappeared")
            key = (order.source_id, order.resource_id)
            self._reserved[key] -= order.amount
        order.state = "in_transit"
        return order

    def deliver(self, order_id: int) -> FreightOrder:
        """Call only after the existing road engine reports truck arrival."""
        order = self.orders[order_id]
        if order.state != "in_transit":
            raise EconomyError("Freight must be picked up before delivery")
        self.nodes[order.destination_id].inventory.add(order.resource_id, order.amount)
        order.state = "delivered"
        return order

    def cancel(self, order_id: int) -> FreightOrder:
        """Release a reservation or restore undelivered finite stock."""
        order = self.orders[order_id]
        if order.state not in ("reserved", "in_transit"):
            raise EconomyError("Freight is already closed")
        if not order.from_external:
            if order.state == "reserved":
                key = (order.source_id, order.resource_id)
                self._reserved[key] -= order.amount
            else:
                self.nodes[order.source_id].inventory.add(order.resource_id, order.amount)
        order.state = "cancelled"
        return order
