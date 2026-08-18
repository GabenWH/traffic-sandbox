"""The File dropdown toolbar tool."""

from __future__ import annotations

from ..dropdown_tool import DropdownTool, ToolAction


TOOL_ID = "file"


class FileTool(DropdownTool):
    """File/new-world/export actions, presented like the original File menu."""

    name = "File"

    def actions(self) -> list[ToolAction]:
        return [
            ToolAction("New world", self.host.new_world),
            ToolAction.separator(),
            ToolAction("Save…", self.host.save_state),
            ToolAction("Load…", self.host.load_state),
            ToolAction.separator(),
            ToolAction("Export graph CSV…", self.host.export_csv),
            ToolAction("Export graph SVG…", self.host.export_svg),
            ToolAction.separator(),
            ToolAction("Exit", self.host.exit_app),
        ]


TOOL_CLASS = FileTool
