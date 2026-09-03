"""JSON-backed buildable templates shared by city-construction tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from city import ZoneType


BUILDABLES_PATH = Path(__file__).with_name("buildables.json")
BuildableKind = Literal["road", "building"]


class BuildableCatalogError(ValueError):
    """Raised when the editable buildables catalog is malformed."""


@dataclass(frozen=True)
class BuildableSpec:
    """One named construction template loaded from the catalog."""

    id: str
    kind: BuildableKind
    name: str
    description: str
    specs: dict[str, object]

    def detail_rows(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (key.replace("_", " ").title(), str(value))
            for key, value in self.specs.items()
        )


def load_buildables(path: Path = BUILDABLES_PATH) -> tuple[BuildableSpec, ...]:
    """Load and validate road/building templates from an editable JSON file."""
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BuildableCatalogError(f"Buildables catalog not found: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise BuildableCatalogError(f"Could not read buildables catalog: {error}") from error
    if not isinstance(root, dict):
        raise BuildableCatalogError("Buildables catalog must be a JSON object")
    if root.get("version") != 1:
        raise BuildableCatalogError(f"Unsupported buildables version: {root.get('version')!r}")
    raw_buildables = root.get("buildables")
    if not isinstance(raw_buildables, list):
        raise BuildableCatalogError("buildables must be an array")

    result: list[BuildableSpec] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_buildables):
        path_label = f"buildables[{index}]"
        if not isinstance(raw, dict):
            raise BuildableCatalogError(f"{path_label} must be an object")
        buildable_id = _required_string(raw.get("id"), f"{path_label}.id")
        if buildable_id in seen_ids:
            raise BuildableCatalogError(f"Duplicate buildable id: {buildable_id!r}")
        seen_ids.add(buildable_id)
        kind = _required_string(raw.get("kind"), f"{path_label}.kind")
        if kind not in ("road", "building"):
            raise BuildableCatalogError(f"{path_label}.kind must be 'road' or 'building'")
        specs = raw.get("specs")
        if not isinstance(specs, dict):
            raise BuildableCatalogError(f"{path_label}.specs must be an object")
        if kind == "road":
            _validate_road_specs(specs, path_label)
        else:
            _validate_building_specs(specs, path_label)
        result.append(BuildableSpec(
            id=buildable_id,
            kind=kind,
            name=_required_string(raw.get("name"), f"{path_label}.name"),
            description=_required_string(
                raw.get("description"), f"{path_label}.description"
            ),
            specs=dict(specs),
        ))
    return tuple(result)


def buildables_of_kind(
    kind: BuildableKind,
    path: Path = BUILDABLES_PATH,
) -> tuple[BuildableSpec, ...]:
    specs = tuple(spec for spec in load_buildables(path) if spec.kind == kind)
    if not specs:
        raise BuildableCatalogError(f"Buildables catalog contains no {kind} templates")
    return specs


def _validate_road_specs(specs: dict[str, object], path: str) -> None:
    lane_width = _positive_number(specs.get("lane_width"), f"{path}.specs.lane_width")
    forward = _nonnegative_int(
        specs.get("forward_lane_count"), f"{path}.specs.forward_lane_count"
    )
    reverse = _nonnegative_int(
        specs.get("reverse_lane_count"), f"{path}.specs.reverse_lane_count"
    )
    if forward + reverse < 1:
        raise BuildableCatalogError(f"{path} must define at least one road lane")
    specs["lane_width"] = lane_width
    specs["forward_lane_count"] = forward
    specs["reverse_lane_count"] = reverse


def _validate_building_specs(specs: dict[str, object], path: str) -> None:
    specs["width"] = _positive_number(specs.get("width"), f"{path}.specs.width")
    specs["height"] = _positive_number(specs.get("height"), f"{path}.specs.height")
    specs["residents"] = _nonnegative_int(
        specs.get("residents", 0), f"{path}.specs.residents"
    )
    specs["jobs"] = _nonnegative_int(specs.get("jobs", 0), f"{path}.specs.jobs")
    zone = _required_string(specs.get("zone"), f"{path}.specs.zone")
    try:
        ZoneType(zone)
    except ValueError as error:
        raise BuildableCatalogError(f"{path}.specs.zone is unknown: {zone!r}") from error
    color = _required_string(specs.get("color"), f"{path}.specs.color")
    if not color.startswith("#") or len(color) not in (4, 7):
        raise BuildableCatalogError(f"{path}.specs.color must be a hex color")
    try:
        int(color[1:], 16)
    except ValueError as error:
        raise BuildableCatalogError(f"{path}.specs.color must be a hex color") from error


def _required_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuildableCatalogError(f"{path} must be a non-empty string")
    return value.strip()


def _positive_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise BuildableCatalogError(f"{path} must be a positive number")
    return float(value)


def _nonnegative_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BuildableCatalogError(f"{path} must be a nonnegative integer")
    return value
