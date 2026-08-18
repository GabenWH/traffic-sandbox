"""The one-click Reset view toolbar tool."""

from __future__ import annotations

from typing import Any

from ..base import CommandTool


TOOL_ID = "reset_view"


class ResetViewTool(CommandTool):
    """Reset the map camera without changing the selected canvas tool."""

    def __init__(self, host: Any) -> None:
        super().__init__(host, "Reset view", host.reset_camera)


TOOL_CLASS = ResetViewTool
