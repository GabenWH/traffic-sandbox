"""The Simulation dropdown toolbar tool."""

from __future__ import annotations

from ..dropdown_tool import DropdownTool, ToolAction


TOOL_ID = "simulation"


class SimulationTool(DropdownTool):
    """Simulation commands, presented like the original Simulation menu."""

    name = "Simulation"

    def actions(self) -> list[ToolAction]:
        return [
            ToolAction("Pause / resume", self.host.toggle_running),
            ToolAction("Add car", self.host.add_car),
            ToolAction("Clear traffic", self.host.clear_cars),
            ToolAction.separator(),
            ToolAction("Analytics graph", self.host.show_analytics),
            ToolAction("Recent changes", self.host.create_recent_changes_window),
            ToolAction.separator(),
            ToolAction("Imperial (mph, feet)", lambda: self.host.set_unit_system("imperial")),
            ToolAction("Metric (km/h, metres)", lambda: self.host.set_unit_system("metric")),
        ]


TOOL_CLASS = SimulationTool
