"""Reusable dropdown-menu tools for the main toolbar."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass

from .base import CanvasTool, ToolbarTool


ACTIVE_MENU_COLOR = "#1976d2"
ACTIVE_MENU_TEXT_COLOR = "#ffffff"


@dataclass(frozen=True)
class ToolAction:
    """One menu item rendered by a :class:`DropdownTool`."""

    label: str | None = None
    command: Callable[[], None] | None = None

    @classmethod
    def separator(cls) -> "ToolAction":
        """Return a visual grouping separator for a dropdown menu."""
        return cls()


class DropdownTool(ToolbarTool):
    """A toolbar tool whose actions appear in Tkinter's standard dropdown menu."""

    def actions(self) -> list[ToolAction]:
        """Return the ordered menu items displayed by this dropdown."""
        return []

    def build(self, toolbar: tk.Misc) -> tk.Menubutton:
        button = tk.Menubutton(toolbar, text=self.name, relief="raised", bg="#e8edf2")
        menu = self._build_menu(button)
        button.config(menu=menu)
        self.button = button
        return button

    def _build_menu(self, parent: tk.Misc) -> tk.Menu:
        menu = tk.Menu(parent, tearoff=False)
        for action in self.actions():
            if action.label is None:
                menu.add_separator()
            else:
                assert action.command is not None
                menu.add_command(label=action.label, command=action.command)
        return menu


class CanvasToolDropdown(DropdownTool):
    """A dropdown that owns selectable, persistent canvas interaction modes."""

    def __init__(self, host: object) -> None:
        super().__init__(host)
        self.owned_canvas_tools = tuple(self.create_canvas_tools())
        self.active_button: tk.Menubutton | None = None
        self.active_menu: tk.Menu | None = None
        self._selected_tool: tk.StringVar | None = None

    def create_canvas_tools(self) -> list[CanvasTool]:
        """Construct the canvas modes listed by this dropdown."""
        return []

    def extra_actions(self) -> list[ToolAction]:
        """Return ordinary commands shown after the owned canvas modes."""
        return []

    def iter_canvas_tools(self) -> tuple[CanvasTool, ...]:
        return self.owned_canvas_tools

    def actions(self) -> list[ToolAction]:
        actions = [
            ToolAction(tool.name, lambda selected=tool: self.host.select_tool(selected))
            for tool in self.owned_canvas_tools
        ]
        extra = self.extra_actions()
        if extra:
            actions.extend((ToolAction.separator(), *extra))
        inspector = getattr(self.host, "inspector_tool", None)
        if inspector is not None and inspector not in self.owned_canvas_tools:
            actions.extend((ToolAction.separator(), ToolAction("Inspector…", inspector.show_panel)))
        return actions

    def _build_menu(self, parent: tk.Misc) -> tk.Menu:
        """Build a menu whose canvas entries visibly retain selection."""
        if self._selected_tool is None:
            self._selected_tool = tk.StringVar(master=parent, value="")
        menu = tk.Menu(parent, tearoff=False)
        for tool in self.owned_canvas_tools:
            menu.add_radiobutton(
                label=tool.name,
                variable=self._selected_tool,
                value=tool.name,
                command=lambda selected=tool: self.host.select_tool(selected),
            )
        extra = self.extra_actions()
        if extra:
            menu.add_separator()
            for action in extra:
                if action.label is None:
                    menu.add_separator()
                else:
                    assert action.command is not None
                    menu.add_command(label=action.label, command=action.command)
        return menu

    def set_active_tool(self, tool: CanvasTool | None) -> None:
        """Dock and persist this menu while one of its canvas modes is active."""
        owns_tool = tool in self.owned_canvas_tools
        if not owns_tool:
            self._remove_active_menu()
            return
        assert tool is not None
        if self._selected_tool is not None:
            self._selected_tool.set(tool.name)
        if self.active_button is None:
            assert self.button is not None
            self.button.grid_remove()
            active_area = self.host.active_menu_area
            active_area.config(bg=ACTIVE_MENU_COLOR)
            self.active_button = tk.Menubutton(
                active_area, text=self.name, relief="sunken",
                bg=ACTIVE_MENU_COLOR, fg=ACTIVE_MENU_TEXT_COLOR,
                activebackground=ACTIVE_MENU_COLOR,
                activeforeground=ACTIVE_MENU_TEXT_COLOR,
            )
            self.active_menu = self._build_menu(self.active_button)
            self.active_button.config(menu=self.active_menu)
            self.active_button.bind(
                "<Button-1>", self._deactivate_from_active_button,
            )
            self.active_button.pack(fill="both", expand=True)
            self.active_menu.bind("<Unmap>", self._restore_posted_menu, add="+")
        self.host.root.after_idle(self._post_active_menu)

    def _deactivate_from_active_button(self, _event: object) -> str:
        """Treat the docked blue menu button as the active mode's close toggle."""
        active_tool = self.host.active_tool
        if active_tool in self.owned_canvas_tools:
            self.host.deactivate_tool(active_tool)
        return "break"

    def _post_active_menu(self) -> None:
        if self.active_button is None or self.active_menu is None:
            return
        self.active_button.update_idletasks()
        self.active_menu.post(
            self.active_button.winfo_rootx(),
            self.active_button.winfo_rooty() + self.active_button.winfo_height(),
        )

    def _restore_posted_menu(self, _event: object) -> None:
        if self.host.active_tool in self.owned_canvas_tools:
            self.host.root.after_idle(self._post_active_menu)

    def _remove_active_menu(self) -> None:
        if self._selected_tool is not None:
            self._selected_tool.set("")
        if self.active_menu is not None:
            self.active_menu.unpost()
        if self.active_button is not None:
            self.active_button.destroy()
        self.active_button = None
        self.active_menu = None
        if self.button is not None:
            self.button.grid()
        active_area = getattr(self.host, "active_menu_area", None)
        if active_area is not None:
            active_area.config(bg="#e8edf2")
