"""Overview: where the case stands, the three steps to a result, and recent analyses."""

from __future__ import annotations

import tkinter as tk
from collections import Counter
from tkinter import ttk

from ...history import list_runs
from .. import theme
from ..theme import ACCENT, ACCENT_SOFT, OK, OK_SOFT, SURFACE
from ..widgets import FILL, Card, PageHeader, icon, pill, plural, run_time, separator, status_pill, text
from .base import Page


class OverviewPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        px = app.theme.px
        PageHeader(self.content, "Overview", "Collect the tools, drop in evidence, choose what to find out.").pack(fill="x")

        self.stats = tk.Frame(self.content, bg=self.content.cget("bg"))
        self.stats.pack(fill="x", pady=(px(20), px(16)))
        for column in range(4):
            self.stats.columnconfigure(column, weight=1, uniform="stats")

        lower = tk.Frame(self.content, bg=self.content.cget("bg"))
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=3, uniform="lower")
        lower.columnconfigure(1, weight=2, uniform="lower")
        lower.rowconfigure(1, weight=1)
        self.steps = Card(lower)
        self.steps.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)), pady=(0, px(16)))
        self.found = Card(lower)
        self.found.grid(row=1, column=0, sticky="nsew", padx=(0, px(16)))
        self.recent = Card(lower)
        self.recent.grid(row=0, column=1, rowspan=2, sticky="nsew")

    def shown(self) -> None:
        self._refresh()

    def evidence_changed(self) -> None:
        self._refresh()

    def tools_changed(self) -> None:
        self._refresh()

    def runs_changed(self) -> None:
        self._refresh()

    def folders_changed(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        if self.app.current_page != "overview":
            return
        app = self.app
        items = app.items
        recognised = [item for item in items if item.artifact]
        types = Counter(item.artifact.label for item in recognised)
        recommended = [tool for tool in app.catalog.tools if tool.recommended]
        ready = sum(1 for tool in recommended if app.toolbox.status(tool).installed)
        runs = list_runs(app.workspace.output_dir)

        for child in self.stats.winfo_children():
            child.destroy()
        self._stat(0, "evidence", "Evidence files", str(len(items)), f"{len(recognised)} recognised")
        self._stat(1, "search", "Artifact types", str(len(types)), "found in the evidence folder")
        self._stat(2, "tools", "Recommended tools", f"{ready}/{len(recommended)}", "installed")
        last = f"last {run_time(runs[0].name)}" if runs else "none yet"
        self._stat(3, "results", "Analyses", str(len(runs)), last)

        self._fill_steps(ready, len(recommended), len(items), bool(runs))
        self._fill_found(types)
        self._fill_recent(runs[:6])

    def _stat(self, column: int, glyph: str, label: str, value: str, note: str) -> None:
        px = self.app.theme.px
        card = Card(self.stats, padding=16)
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else px(8), 0 if column == 3 else px(8)))
        top = tk.Frame(card.body, bg=SURFACE)
        top.pack(fill="x")
        text(top, label, "small").pack(side="left")
        icon(top, glyph, size="icon_small", fg=ACCENT).pack(side="right")
        text(card.body, value, "stat").pack(anchor="w", pady=(px(4), 0))
        text(card.body, note, "faint").pack(anchor="w")

    def _fill_steps(self, ready: int, recommended: int, evidence: int, has_runs: bool) -> None:
        body = self.steps.body
        for child in body.winfo_children():
            child.destroy()
        px = self.app.theme.px
        text(body, "Get started", "h2").pack(anchor="w", pady=(0, px(10)))
        steps = (
            ("Install the tools", f"{ready} of {recommended} recommended tools are installed.",
             ready == recommended, "Install recommended", self._install_recommended),
            ("Add evidence", f"{plural(evidence, 'file')} in the evidence folder. Copy collected files into it to analyse them.",
             evidence > 0, "Open evidence page", lambda: self.app.navigate("evidence")),
            ("Choose analyses", "Pick questions to answer; the right tools run on the matching files.",
             has_runs, "Start an analysis", lambda: self.app.navigate("analyze")),
        )
        for number, (title, detail, done, action, command) in enumerate(steps, start=1):
            if number > 1:
                separator(body).pack(fill="x", pady=px(10))
            row = tk.Frame(body, bg=SURFACE)
            row.pack(fill="x")
            badge = tk.Canvas(row, width=px(30), height=px(30), bg=SURFACE, highlightthickness=0)
            badge.pack(side="left", anchor="n")
            badge.create_oval(1, 1, px(29), px(29), fill=OK_SOFT if done else ACCENT_SOFT, outline="")
            badge.create_text(px(15), px(15), text=str(number), fill=OK if done else ACCENT, font=self.app.theme.fonts.strong)
            ttk.Button(row, text=action, style="Secondary.TButton" if done else "Primary.TButton", command=command).pack(side="right")
            words = tk.Frame(row, bg=SURFACE)
            words.pack(side="left", fill="x", expand=True, padx=(px(12), px(12)))
            heading = tk.Frame(words, bg=SURFACE)
            heading.pack(anchor="w")
            text(heading, title, "h3").pack(side="left")
            if done:
                pill(heading, "Done", OK, OK_SOFT).pack(side="left", padx=(px(8), 0))
            text(words, detail, "muted", wrap=FILL).pack(anchor="w", fill="x")

    def _fill_found(self, types: Counter) -> None:
        body = self.found.body
        for child in body.winfo_children():
            child.destroy()
        px = self.app.theme.px
        text(body, "Evidence found", "h2").pack(anchor="w", pady=(0, px(10)))
        if not types:
            text(body, "Nothing recognised yet. Copy collected files into the evidence folder.", "muted").pack(anchor="w")
            return
        largest = max(types.values())
        for label, count in types.most_common(5):
            row = tk.Frame(body, bg=SURFACE)
            row.pack(fill="x", pady=px(2))
            text(row, str(count), "strong", width=5, anchor="e").pack(side="right")
            text(row, label, "body", width=24).pack(side="left")
            bar = tk.Canvas(row, height=px(8), bg=SURFACE, highlightthickness=0)
            bar.pack(side="left", fill="x", expand=True, padx=px(10))
            bar.bind("<Configure>", lambda event, share=count / largest, canvas=bar: self._bar(canvas, event.width, share))
        if len(types) > 5:
            more = text(body, f"and {len(types) - 5} more types on the Evidence page", "link")
            more.pack(anchor="w", pady=(px(6), 0))
            more.bind("<Button-1>", lambda _: self.app.navigate("evidence"))

    def _bar(self, canvas: tk.Canvas, width: int, share: float) -> None:
        canvas.delete("all")
        height = int(canvas.cget("height"))
        canvas.create_rectangle(0, 0, width, height, fill=theme.NEUTRAL_SOFT, outline="")
        canvas.create_rectangle(0, 0, max(4, width * share), height, fill=ACCENT, outline="")

    def _fill_recent(self, runs) -> None:
        body = self.recent.body
        for child in body.winfo_children():
            child.destroy()
        px = self.app.theme.px
        text(body, "Recent analyses", "h2").pack(anchor="w", pady=(0, px(10)))
        if not runs:
            text(body, "Results of each analysis appear here.", "muted").pack(anchor="w")
            return
        for record in runs:
            row = tk.Frame(body, bg=SURFACE, cursor="hand2")
            row.pack(fill="x", pady=px(4))
            text(row, run_time(record.name), "strong").pack(anchor="w")
            line = tk.Frame(row, bg=SURFACE)
            line.pack(anchor="w", pady=(px(2), 0))
            if record.error:
                text(line, record.error, "faint").pack(side="left")
            for status, count in sorted(record.counts.items()):
                status_pill(line, status).pack(side="left", padx=(0, px(4)))
                text(line, str(count), "small").pack(side="left", padx=(0, px(8)))
            for widget in (row, *row.winfo_children()):
                widget.bind("<Button-1>", lambda _, name=record.name: self._open_run(name))
            separator(body).pack(fill="x", pady=(px(4), 0))
        text(body, "All results", "link").pack(anchor="w", pady=(px(10), 0))
        body.winfo_children()[-1].bind("<Button-1>", lambda _: self.app.navigate("results"))

    def _open_run(self, name: str) -> None:
        self.app.pages["results"].select_run(name)
        self.app.navigate("results")

    def _install_recommended(self) -> None:
        wanted = [tool for tool in self.app.catalog.tools if tool.recommended and not self.app.toolbox.status(tool).installed]
        if wanted:
            self.app.install_tools(wanted)
        else:
            self.app.navigate("tools")
