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
            ToolAction("Move in household (selected home)", self.host.invite_household_selected),
            ToolAction("Assign worker (selected workplace)", self.host.assign_selected_workplace),
            ToolAction("Commission truck (selected building)", self.host.commission_truck_selected),
            ToolAction("Import supplies (selected building)", self.host.supply_selected_building),
            ToolAction("Refuel (selected building/stop)", self.host.refuel_selected_building),
            ToolAction.separator(),
            ToolAction("Analytics graph", self.host.show_analytics),
            ToolAction("Performance graph", self.host.show_performance_graph),
            ToolAction("Recent changes", self.host.create_recent_changes_window),
            ToolAction.separator(),
            ToolAction("Imperial (mph, feet)", lambda: self.host.set_unit_system("imperial")),
            ToolAction("Metric (km/h, metres)", lambda: self.host.set_unit_system("metric")),
        ]


TOOL_CLASS = SimulationTool
