"""Tests for automatic toolbar-manifest synchronization."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ui_tools.sync_toolbar import sync_manifest
from ui_tools.toolbar_registry import discover_tool_definitions


class SyncToolbarTests(unittest.TestCase):
    def test_sync_appends_discovered_tools_without_changing_existing_entries(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            manifest = Path(temporary_directory) / "toolbar.json"
            original_entry = {"id": "file", "enabled": False}
            manifest.write_text(json.dumps([original_entry]), encoding="utf-8")

            added = sync_manifest(manifest)
            entries = json.loads(manifest.read_text(encoding="utf-8"))

        definitions = discover_tool_definitions()
        self.assertEqual(entries[0], original_entry)
        self.assertEqual(added, [tool_id for tool_id in definitions if tool_id != "file"])
        self.assertEqual([entry["id"] for entry in entries], list(definitions))


if __name__ == "__main__":
    unittest.main()
