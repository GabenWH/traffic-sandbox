"""Explicit terminal-style colors for macOS tool surfaces."""

import sys


def style_panel(widget):
    """Style only a supplied tool subtree, never the world canvas."""
    if sys.platform != "darwin" or widget is None:
        return
    available = widget.keys()
    colors = {
        "background": "#000000", "foreground": "#39ff14",
        "activebackground": "#39ff14", "activeforeground": "#000000",
        "selectbackground": "#39ff14", "selectforeground": "#000000",
        "insertbackground": "#39ff14", "disabledforeground": "#76a66d",
        "highlightbackground": "#248c18", "highlightcolor": "#39ff14",
        "troughcolor": "#163312",
    }
    widget.configure(**{key: value for key, value in colors.items() if key in available})
    for child in widget.winfo_children():
        style_panel(child)
