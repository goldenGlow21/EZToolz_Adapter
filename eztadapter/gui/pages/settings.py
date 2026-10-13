"""Settings: where evidence, results and tools live, accepted licences, and how evidence is protected."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import __version__
from ..theme import SURFACE
from ..widgets import FILL, Card, PageHeader, open_path, open_url, separator, text
from .base import Page

_PROTECTION = (
    "Evidence files are only opened for reading. Before a tool runs, its files are copied into a working folder "
    "inside the run, keeping their created, modified and accessed times; the tool only sees the copy, which is "
    "deleted afterwards. Each copy is hashed while it is written, and run.json records the SHA-256 of every input "
    "with the exact commands, exit codes and output files. Viewers also get a copy, never the evidence itself."
)


class SettingsPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        PageHeader(self.content, "Settings", "Folders, licences and how the adapter treats evidence.").pack(fill="x")
        self.body = tk.Frame(self.content, bg=self.content.cget("bg"))
        self.body.pack(fill="both", expand=True, pady=(app.theme.px(18), 0))
        self.body.columnconfigure(0, weight=3, uniform="settings")
        self.body.columnconfigure(1, weight=2, uniform="settings")

    def shown(self) -> None:
        self._build()

    def folders_changed(self) -> None:
        if self.app.current_page == "settings":
            self._build()

    def _build(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        px = self.app.theme.px
        workspace = self.app.workspace

        folders = Card(self.body)
        folders.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)), pady=(0, px(16)))
        text(folders.body, "Folders", "h2").pack(anchor="w", pady=(0, px(10)))
        rows = (
            ("Evidence", workspace.evidence_dir, "Files to analyse. Drop a collection here or point it at one.", "evidence"),
            ("Output", workspace.output_dir, "One folder per analysis, with every tool's results and run.json.", "output"),
            ("Tools", workspace.tools_dir, "Downloaded tools, one folder each.", None),
            ("Home", workspace.home, "Holds the folders above and settings.json; copy it to move the whole kit.", None),
        )
        for index, (name, path, note, key) in enumerate(rows):
            if index:
                separator(folders.body).pack(fill="x", pady=px(10))
            row = tk.Frame(folders.body, bg=SURFACE)
            row.pack(fill="x")
            ttk.Button(row, text="Open", style="Secondary.TButton", command=lambda path=path: open_path(path)).pack(side="right")
            if key:
                ttk.Button(row, text="Change", style="Secondary.TButton",
                           command=lambda key=key: self.app.change_folder(key)).pack(side="right", padx=(0, px(8)))
            words = tk.Frame(row, bg=SURFACE)
            words.pack(side="left", fill="x", expand=True, padx=(0, px(12)))
            text(words, name, "strong").pack(anchor="w")
            text(words, str(path), "body", wrap=FILL).pack(anchor="w", fill="x")
            text(words, note, "faint", wrap=FILL).pack(anchor="w", fill="x")

        protection = Card(self.body)
        protection.grid(row=1, column=0, sticky="nsew", padx=(0, px(16)))
        text(protection.body, "How evidence is protected", "h2").pack(anchor="w", pady=(0, px(8)))
        text(protection.body, _PROTECTION, "body", wrap=FILL).pack(anchor="w", fill="x")

        licences = Card(self.body)
        licences.grid(row=0, column=1, sticky="nsew", pady=(0, px(16)))
        text(licences.body, "Accepted licences", "h2").pack(anchor="w", pady=(0, px(8)))
        if not workspace.accepted_licenses:
            text(licences.body, "None yet. Tools whose terms need accepting ask before their first download.",
                 "muted", wrap=FILL).pack(anchor="w", fill="x")
        for url in sorted(workspace.accepted_licenses):
            tools = ", ".join(tool.id for tool in self.app.catalog.tools if tool.license == url)
            link = text(licences.body, url, "link", wrap=FILL)
            link.pack(anchor="w", fill="x", pady=(px(4), 0))
            link.bind("<Button-1>", lambda _, url=url: open_url(url))
            text(licences.body, f"Accepted for {tools}", "faint", wrap=FILL).pack(anchor="w", fill="x")

        about = Card(self.body)
        about.grid(row=1, column=1, sticky="nsew")
        text(about.body, "About", "h2").pack(anchor="w", pady=(0, px(8)))
        text(about.body, f"EZToolz Adapter {__version__}", "strong").pack(anchor="w")
        text(about.body, "Runs free and open-source forensic tools on evidence through one window. Each tool keeps its own "
                         "licence and is downloaded from its publisher.", "muted", wrap=FILL).pack(anchor="w", fill="x", pady=(px(4), px(10)))
        text(about.body, "Shortcuts", "faint").pack(anchor="w")
        text(about.body, "Ctrl+1 to Ctrl+6 switch pages; F5 rescans the evidence folder.", "body", wrap=FILL).pack(anchor="w", fill="x")
