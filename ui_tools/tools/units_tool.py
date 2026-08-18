"""The toolbar menu for choosing Imperial or Metric presentation."""

from __future__ import annotations

from ..dropdown_tool import DropdownTool, ToolAction


TOOL_ID = "units"


class UnitsTool(DropdownTool):
    """Switch display/input units without changing canonical simulation data."""

    name = "Units"

    def actions(self) -> list[ToolAction]:
        return [
            ToolAction("Imperial (mph, feet)", lambda: self.host.set_unit_system("imperial")),
            ToolAction("Metric (km/h, metres)", lambda: self.host.set_unit_system("metric")),
        ]


TOOL_CLASS = UnitsTool
