"""Toolbar-tool and canvas-tool foundations."""

from __future__ import annotations

from typing import Any
import tkinter as tk


class ToolbarTool:
    """A reusable item that knows how to add itself to the main toolbar."""

    name = "Tool"

    def __init__(self, host: Any) -> None:
        self.host = host
        self.button: tk.Widget | None = None

    def build(self, toolbar: tk.Misc) -> tk.Widget:
        """Create and return this tool's toolbar widget."""
        raise NotImplementedError


class CommandTool(ToolbarTool):
    """A one-click toolbar command, such as Reset view."""

    def __init__(self, host: Any, name: str, command: Any) -> None:
        super().__init__(host)
        self.name = name
        self.command = command

    def build(self, toolbar: tk.Misc) -> tk.Button:
        button = tk.Button(toolbar, text=self.name, command=self.command, bg="#e8edf2")
        self.button = button
        return button


class CanvasTool(ToolbarTool):
    """Base class for a selectable tool that handles main-canvas clicks.

    Subclasses override only the hooks they need. ``host`` is the main UI
    object; keeping it here lets a first tool stay simple while still making
    the activate/click/refresh/deactivate pattern reusable.
    """

    def build(self, toolbar: tk.Misc) -> tk.Button:
        """Create a toggle button that selects this canvas interaction mode."""
        button = tk.Button(
            toolbar, text=self.name,
            command=lambda: self.host.select_tool(self), bg="#e8edf2",
        )
        self.button = button
        return button

    def set_active(self, active: bool) -> None:
        """Reflect selection in the toolbar button's relief."""
        if self.button is not None:
            self.button.config(relief="sunken" if active else "raised")

    def activate(self) -> None:
        """Start the tool or raise its existing UI."""

    def deactivate(self) -> None:
        """Stop the tool and close any UI it owns."""

    def on_canvas_click(self, event: Any) -> None:
        """Handle a left click delegated by the main world canvas."""

    def refresh(self) -> None:
        """Update live information while the tool is active."""

    def reset(self) -> None:
        """Discard references to objects from a replaced world."""
