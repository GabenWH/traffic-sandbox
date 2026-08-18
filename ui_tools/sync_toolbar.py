"""Append newly discovered tools to the editable toolbar manifest.

Run ``python -m ui_tools.sync_toolbar`` after creating a tool module, or let
``scripts/watch_toolbar_tools.sh`` run it whenever the folder changes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .toolbar_registry import MANIFEST_PATH, discover_tool_definitions


def sync_manifest(path: Path = MANIFEST_PATH) -> list[str]:
    """Append absent discovered IDs while preserving every existing entry."""
    definitions = discover_tool_definitions()
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = []
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot safely update {path}: {error}") from error
    if not isinstance(data, list):
        raise ValueError(f"Cannot safely update {path}: the root must be a JSON array")

    configured_ids = {
        entry.get("id") for entry in data
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    missing_ids = [tool_id for tool_id in definitions if tool_id not in configured_ids]
    if missing_ids:
        data.extend({"id": tool_id, "enabled": True} for tool_id in missing_ids)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return missing_ids


def main() -> int:
    """Run the synchronizer as a small, dependency-free command-line tool."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report additions without writing JSON")
    arguments = parser.parse_args()
    if arguments.check:
        definitions = discover_tool_definitions()
        try:
            data: Any = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"Cannot check {MANIFEST_PATH}: {error}")
            return 1
        configured_ids = {
            entry.get("id") for entry in data
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
        missing_ids = [tool_id for tool_id in definitions if tool_id not in configured_ids]
        print("Toolbar manifest is current." if not missing_ids else f"Missing: {', '.join(missing_ids)}")
        return 0 if not missing_ids else 1
    try:
        missing_ids = sync_manifest()
    except ValueError as error:
        print(error)
        return 1
    print("Toolbar manifest is current." if not missing_ids else f"Added: {', '.join(missing_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
