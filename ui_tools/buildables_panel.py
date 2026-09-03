"""Inspector-style catalog panel used by buildable canvas tools."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Any

from .buildables import BuildableSpec


class BuildablesPanel:
    """Display JSON buildable choices and the selected template's specs."""

    def __init__(
        self,
        host: Any,
        owner: object,
        title: str,
        specs: Sequence[BuildableSpec],
        selected: BuildableSpec,
        on_select: Callable[[BuildableSpec], None],
    ) -> None:
        self.host = host
        self.owner = owner
        self.title = title
        self.specs = tuple(specs)
        self.selected = selected
        self.on_select = on_select
        self.panel: tk.Frame | None = None
        self.listbox: tk.Listbox | None = None
        self.details_frame: tk.Frame | None = None
        self.message_label: tk.Label | None = None

    def show(self) -> None:
        inspector = getattr(self.host, "inspector_tool", None)
        if inspector is not None:
            inspector.hide_panel()
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.lift()
            self._render_selection()
            return

        self.panel = tk.Frame(
            self.host.canvas,
            bg="#e8edf2",
            highlightthickness=1,
            highlightbackground="#7b8792",
        )
        self.panel.place(x=12, rely=1.0, y=-12, anchor="sw", width=480, height=365)
        header = tk.Frame(self.panel, bg="#e8edf2")
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(
            header,
            text=self.title,
            anchor="w",
            bg="#e8edf2",
            font=("Arial", 13, "bold"),
        ).pack(side="left", fill="x", expand=True)
        tk.Button(
            header,
            text="×",
            width=2,
            relief="flat",
            bg="#e8edf2",
            command=self.close,
        ).pack(side="right")

        body = tk.Frame(self.panel, bg="#ffffff", relief="sunken", borderwidth=1)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        list_shell = tk.Frame(body, bg="#f3f6f8", width=165)
        list_shell.pack(side="left", fill="y")
        list_shell.pack_propagate(False)
        list_scrollbar = tk.Scrollbar(list_shell, orient="vertical")
        list_scrollbar.pack(side="right", fill="y")
        self.listbox = tk.Listbox(
            list_shell,
            bg="#f3f6f8",
            fg="#20252a",
            selectbackground="#d8eafa",
            selectforeground="#125da8",
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            exportselection=False,
            yscrollcommand=list_scrollbar.set,
        )
        self.listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        list_scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._select_from_list)
        self.details_frame = tk.Frame(body, bg="#ffffff")
        self.details_frame.pack(side="left", fill="both", expand=True)
        for spec in self.specs:
            self.listbox.insert("end", spec.name)

        self.message_label = tk.Label(
            self.panel,
            anchor="w",
            bg="#e8edf2",
            font=("Arial", 9),
            wraplength=440,
        )
        self.message_label.pack(fill="x", padx=12, pady=(0, 10))
        self._render_selection()

    def select(self, spec: BuildableSpec) -> None:
        self.selected = spec
        self.on_select(spec)
        self._render_selection()

    def _select_from_list(self, _event: object) -> None:
        if self.listbox is None or not self.listbox.curselection():
            return
        self.select(self.specs[self.listbox.curselection()[0]])

    def set_message(self, message: str, error: bool = False) -> None:
        if self.message_label is not None:
            self.message_label.config(
                text=message,
                fg="#b00020" if error else "#285c2f",
            )

    def _render_selection(self) -> None:
        if self.details_frame is None:
            return
        if self.listbox is not None:
            selected_index = next(
                index for index, spec in enumerate(self.specs) if spec.id == self.selected.id
            )
            if self.listbox.curselection() != (selected_index,):
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(selected_index)
                self.listbox.see(selected_index)
        for child in self.details_frame.winfo_children():
            child.destroy()
        tk.Label(
            self.details_frame,
            text=self.selected.name,
            anchor="w",
            bg="#ffffff",
            font=("Arial", 11, "bold"),
        ).pack(fill="x", padx=10, pady=(10, 3))
        tk.Label(
            self.details_frame,
            text=self.selected.description,
            anchor="nw",
            justify="left",
            bg="#ffffff",
            wraplength=265,
        ).pack(fill="x", padx=10, pady=(0, 8))
        for label, value in self.selected.detail_rows():
            row = tk.Frame(self.details_frame, bg="#ffffff")
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=label, width=17, anchor="w", bg="#ffffff").pack(side="left")
            tk.Label(
                row,
                text=value,
                anchor="w",
                bg="#ffffff",
                font=("Courier", 10),
            ).pack(side="left", fill="x", expand=True)

    def close(self) -> None:
        if getattr(self.host, "active_tool", None) is self.owner:
            self.host.deactivate_tool(self.owner)
        else:
            self.hide()

    def hide(self) -> None:
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.destroy()
        self.panel = None
        self.listbox = None
        self.details_frame = None
        self.message_label = None
