"""Physical construction resources and truck specifications supplied as data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Iterable, Mapping

from ui_tools.buildables import BuildableSpec


CONSTRUCTION_CATALOG_PATH = (
    Path(__file__).with_name("ui_tools") / "construction_resources.json"
)


class ConstructionCatalogError(ValueError):
    """Raised when construction resource or truck data is invalid."""


@dataclass(frozen=True)
class ResourceSpec:
    id: str
    name: str
    unit: str
    mass_kg_per_unit: float
    volume_m3_per_unit: float
    visual_key: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "unit"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ConstructionCatalogError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())
        if self.visual_key is not None:
            if not isinstance(self.visual_key, str) or not self.visual_key.strip():
                raise ConstructionCatalogError("visual_key must be a non-empty string or null")
            object.__setattr__(self, "visual_key", self.visual_key.strip())
        object.__setattr__(
            self,
            "mass_kg_per_unit",
            _positive_finite_number(self.mass_kg_per_unit, "mass_kg_per_unit"),
        )
        object.__setattr__(
            self,
            "volume_m3_per_unit",
            _positive_finite_number(self.volume_m3_per_unit, "volume_m3_per_unit"),
        )


@dataclass(frozen=True)
class TruckSpec:
    id: str
    payload_kg: float
    cargo_m3: float
    crew_capacity: int
    length: float
    width: float
    visual_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ConstructionCatalogError("id must be a non-empty string")
        object.__setattr__(self, "id", self.id.strip())
        if self.visual_key is not None:
            if not isinstance(self.visual_key, str) or not self.visual_key.strip():
                raise ConstructionCatalogError("visual_key must be a non-empty string or null")
            object.__setattr__(self, "visual_key", self.visual_key.strip())
        for field_name in ("payload_kg", "cargo_m3"):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_finite_number(getattr(self, field_name), field_name),
            )
        if (
            isinstance(self.crew_capacity, bool)
            or not isinstance(self.crew_capacity, int)
            or self.crew_capacity < 0
        ):
            raise ConstructionCatalogError("crew_capacity must be a nonnegative integer")
        for field_name in ("length", "width"):
            object.__setattr__(
                self,
                field_name,
                _positive_finite_number(getattr(self, field_name), field_name),
            )
        has_material_capacity = self.payload_kg > 0 and self.cargo_m3 > 0
        if not has_material_capacity and self.crew_capacity == 0:
            raise ConstructionCatalogError(
                "truck must support at least one payload type (material or crew)"
            )


def load_construction_catalog(
    path: str | Path | None = None,
) -> tuple[dict[str, ResourceSpec], dict[str, TruckSpec]]:
    """Load resource and truck specifications keyed by their stable IDs."""
    source = Path(path) if path is not None else CONSTRUCTION_CATALOG_PATH
    try:
        root = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConstructionCatalogError(
            f"Construction catalog not found: {source}"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise ConstructionCatalogError(f"Could not read construction catalog: {error}") from error
    if not isinstance(root, dict):
        raise ConstructionCatalogError("Construction catalog must be a JSON object")
    version = root.get("version")
    if isinstance(version, bool) or version != 1:
        raise ConstructionCatalogError(f"Unsupported construction catalog version: {version!r}")
    resources = _load_specs(root.get("resources"), "resources", ResourceSpec)
    trucks = _load_specs(root.get("trucks"), "trucks", TruckSpec)
    return resources, trucks


def validate_resource_references(
    buildables: Iterable[BuildableSpec],
    resources: Mapping[str, ResourceSpec],
) -> None:
    """Reject building templates that request materials absent from the catalog."""
    for buildable in buildables:
        if buildable.kind != "building":
            continue
        needs = buildable.specs.get("construction_needs", {})
        if not isinstance(needs, Mapping):
            raise ConstructionCatalogError(
                f"Building {buildable.id!r} construction_needs must be an object"
            )
        for resource_id in needs:
            if resource_id not in resources:
                raise ConstructionCatalogError(
                    f"Building {buildable.id!r} references unknown construction resource "
                    f"{resource_id!r}"
                )


def _load_specs(
    entries: object,
    field_name: str,
    spec_type: type[ResourceSpec] | type[TruckSpec],
) -> dict[str, ResourceSpec] | dict[str, TruckSpec]:
    if not isinstance(entries, list):
        raise ConstructionCatalogError(f"{field_name} must be an array")
    result: dict[str, ResourceSpec] | dict[str, TruckSpec] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConstructionCatalogError(f"{field_name}[{index}] must be an object")
        try:
            spec = spec_type(**entry)
        except ConstructionCatalogError:
            raise
        except TypeError as error:
            raise ConstructionCatalogError(
                f"{field_name}[{index}] has invalid fields: {error}"
            ) from error
        if spec.id in result:
            raise ConstructionCatalogError(f"Duplicate {field_name} ID: {spec.id!r}")
        result[spec.id] = spec
    return result


def _positive_finite_number(value: object, field_name: str) -> float:
    result = _finite_number(value, field_name)
    if result <= 0:
        raise ConstructionCatalogError(f"{field_name} must be positive and finite")
    return result


def _nonnegative_finite_number(value: object, field_name: str) -> float:
    result = _finite_number(value, field_name)
    if result < 0:
        raise ConstructionCatalogError(f"{field_name} must be nonnegative and finite")
    return result


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConstructionCatalogError(f"{field_name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as error:
        raise ConstructionCatalogError(f"{field_name} must be finite") from error
    if not isfinite(result):
        raise ConstructionCatalogError(f"{field_name} must be finite")
    return result
