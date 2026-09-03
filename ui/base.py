"""Shared constants and helpers for the simulator UI package."""

from __future__ import annotations

import tkinter as tk


STATIC_TAG = "static"
SPEED_LIMIT_TAG = "speed_limit"


def window_exists(window: tk.Misc | None) -> bool:
    """Return whether an optional Tk widget still exists."""
    return window is not None and bool(window.winfo_exists())
