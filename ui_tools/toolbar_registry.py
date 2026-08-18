"""Discover toolbar-tool modules and construct the configured toolbar.

Only Python files found in :mod:`ui_tools.tools` may be imported.  The JSON
manifest selects their IDs; it never supplies an import path, so editing the
manifest cannot make the application import arbitrary code.
"""

from __future__ import annotations

import ast
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ToolbarTool


TOOLS_DIRECTORY = Path(__file__).with_name("tools")
MANIFEST_PATH = Path(__file__).with_name("toolbar.json")
MODULE_PREFIX = "ui_tools.tools"


@dataclass(frozen=True)
class ToolDefinition:
    """A tool ID found without importing its module."""

    tool_id: str
    module_name: str
    path: Path


def _static_tool_id(path: Path) -> str | None:
    """Read a literal ``TOOL_ID`` assignment from one module, if present."""
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        print(f"Toolbar: could not read {path.name}: {error}")
        return None
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "TOOL_ID"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def discover_tool_definitions(
    tools_directory: Path = TOOLS_DIRECTORY,
    module_prefix: str = MODULE_PREFIX,
) -> dict[str, ToolDefinition]:
    """Return valid ``*_tool.py`` modules, keyed by their stable tool IDs.

    Discovery is alphabetic by file name solely to make diagnostics and the
    default fallback deterministic.  Normal toolbar order always comes from
    ``toolbar.json``.
    """
    definitions: dict[str, ToolDefinition] = {}
    for path in sorted(tools_directory.glob("*_tool.py")):
        tool_id = _static_tool_id(path)
        if not tool_id:
            print(f"Toolbar: {path.name} has no literal TOOL_ID; skipped")
            continue
        if tool_id in definitions:
            print(f"Toolbar: duplicate TOOL_ID {tool_id!r} in {path.name}; skipped")
            continue
        definitions[tool_id] = ToolDefinition(
            tool_id=tool_id,
            module_name=f"{module_prefix}.{path.stem}",
            path=path,
        )
    return definitions


def read_manifest(path: Path = MANIFEST_PATH) -> list[dict[str, Any]] | None:
    """Read the editable toolbar array, returning ``None`` when unusable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Toolbar: {path.name} is missing; using discovered tools")
        return None
    except (OSError, json.JSONDecodeError) as error:
        print(f"Toolbar: could not read {path.name}: {error}; using discovered tools")
        return None
    if not isinstance(data, list):
        print(f"Toolbar: {path.name} must contain a JSON array; using discovered tools")
        return None
    return [entry for entry in data if isinstance(entry, dict)]


def configured_tool_ids(
    definitions: dict[str, ToolDefinition],
    manifest: list[dict[str, Any]] | None,
) -> list[str]:
    """Filter configured entries and retain their manifest order."""
    if manifest is None:
        return list(definitions)
    result: list[str] = []
    for entry in manifest:
        tool_id = entry.get("id")
        if not isinstance(tool_id, str):
            print("Toolbar: an entry without a string id was skipped")
            continue
        if tool_id not in definitions:
            print(f"Toolbar: unknown tool id {tool_id!r}; skipped")
            continue
        if tool_id in result:
            print(f"Toolbar: duplicate configured tool id {tool_id!r}; skipped")
            continue
        if entry.get("enabled", True) is False:
            continue
        result.append(tool_id)
    return result


def load_toolbar_tools(host: Any) -> list[ToolbarTool]:
    """Instantiate the enabled tools, in the order written in toolbar.json."""
    definitions = discover_tool_definitions()
    manifest = read_manifest()
    tools: list[ToolbarTool] = []
    for tool_id in configured_tool_ids(definitions, manifest):
        definition = definitions[tool_id]
        try:
            module = importlib.import_module(definition.module_name)
            tool_class = module.TOOL_CLASS
            if not isinstance(tool_class, type) or not issubclass(tool_class, ToolbarTool):
                raise TypeError("TOOL_CLASS must be a ToolbarTool subclass")
            tools.append(tool_class(host))
        except Exception as error:
            print(f"Toolbar: could not load {tool_id!r}: {error}")
    return tools
