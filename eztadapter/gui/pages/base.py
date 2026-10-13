"""The page base class: layout margins and the hooks the window calls."""

from __future__ import annotations

import tkinter as tk

from ..theme import BG


class Page(tk.Frame):
    """A full-size page. Subclasses build into `content` and override the hooks they need."""

    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent, bg=BG)
        self.app = app
        px = app.theme.px
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True, padx=px(30), pady=(px(24), px(18)))

    def shown(self) -> None:
        """The page was brought to the front."""

    def evidence_changed(self) -> None:
        """The evidence folder was rescanned or the analysis scope changed."""

    def tools_changed(self) -> None:
        """Tools were installed, updated or removed."""

    def runs_changed(self) -> None:
        """A run finished."""

    def folders_changed(self) -> None:
        """The evidence or output folder was moved."""
