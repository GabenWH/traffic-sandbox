"""Reusable dropdown-menu tools for the main toolbar."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass

from .base import ToolbarTool


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
        menu = tk.Menu(button, tearoff=False)
        for action in self.actions():
            if action.label is None:
                menu.add_separator()
            else:
                assert action.command is not None
                menu.add_command(label=action.label, command=action.command)
        button.config(menu=menu)
        self.button = button
        return button
