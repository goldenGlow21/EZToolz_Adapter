"""Analyze: the menu of investigation tasks, grouped by what they answer.

Each card is one question ("Which programs ran?"). Choosing it runs the tools
that answer it on the matching evidence in scope; the details panel shows
which tools those are and lets the analyst add or drop any of them.
"""

from __future__ import annotations

import tkinter as tk
from collections import Counter
from tkinter import ttk

from ...catalog import ANY_ARTIFACT, InvestigationTask
from ...planner import coverage, merge_choices, plan, step_choice
from .. import theme
from ..theme import ACCENT, ACCENT_SOFT, BORDER, MUTED, SURFACE
from ..widgets import FILL, plural, Card, CheckBox, PageHeader, ScrollArea, icon, pill, separator, text
from .base import Page


class AnalyzePage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        px = app.theme.px
        self.selected: set[str] = set()
        self.ticked = {task.id: {step.action_id for step in task.steps if step.default} for task in app.catalog.tasks}
        self.focused: str | None = None
        self.cards: dict[str, _TaskCard] = {}
        self.available: dict[str, int] = {}
        self.columns = 0

        PageHeader(self.content, "Analyze", "Choose what you want to find out. Each analysis runs the right tools on the matching evidence.").pack(fill="x")
        self.scope_bar = tk.Frame(self.content, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        self.scope_bar.pack(fill="x", pady=(px(16), px(14)))

        split = tk.Frame(self.content, bg=self.content.cget("bg"))
        split.pack(fill="both", expand=True)
        self.menu = ScrollArea(split)
        self.menu.pack(side="left", fill="both", expand=True)
        self.menu.body.bind("<Configure>", lambda event: self._reflow(event.width), add="+")
        self.side = Card(split, padding=0, width=px(380))
        self.side.pack(side="right", fill="y", padx=(px(16), 0))
        self.side.pack_propagate(False)
        self.details = ScrollArea(self.side.body, bg=SURFACE)
        self.details.pack(fill="both", expand=True)
        footer = tk.Frame(self.side.body, bg=theme.SURFACE_ALT)
        footer.pack(fill="x", side="bottom")
        separator(self.side.body).pack(fill="x", side="bottom")
        inner = tk.Frame(footer, bg=theme.SURFACE_ALT)
        inner.pack(fill="x", padx=px(18), pady=px(14))
        self.summary = text(inner, "", "body", wrap=330, bg=theme.SURFACE_ALT)
        self.summary.pack(anchor="w")
        self.run_button = ttk.Button(inner, text="Run analysis", style="Large.Primary.TButton", command=self._run)
        self.run_button.pack(fill="x", pady=(px(10), px(6)))
        links = tk.Frame(inner, bg=theme.SURFACE_ALT)
        links.pack(fill="x")
        select_all = text(links, "Select all available", "link", bg=theme.SURFACE_ALT)
        select_all.pack(side="left")
        select_all.bind("<Button-1>", lambda _: self._select_all())
        clear = text(links, "Clear", "link", bg=theme.SURFACE_ALT)
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda _: self._set_selected(set()))

        self._build_menu()

    # ----- hooks -----

    def shown(self) -> None:
        self.evidence_changed()

    def evidence_changed(self) -> None:
        items = self.app.scope_items()
        for task in self.app.catalog.tasks:
            every_step = merge_choices(self.app.catalog, [(task, [step.action_id for step in task.steps])])
            self.available[task.id] = len(coverage(every_step, items))
        self.selected = {task_id for task_id in self.selected if self.available.get(task_id)}
        self._show_scope(items)
        self._refresh_cards()
        self._show_details()
        self._update_summary()

    def tools_changed(self) -> None:
        self._show_details()
        self._refresh_cards()

    # ----- layout -----

    def _show_scope(self, items) -> None:
        for child in self.scope_bar.winfo_children():
            child.destroy()
        px = self.app.theme.px
        row = tk.Frame(self.scope_bar, bg=SURFACE)
        row.pack(fill="x", padx=px(16), pady=px(10))
        icon(row, "filter", fg=ACCENT).pack(side="left", padx=(0, px(10)))
        if self.app.scope is None:
            text(row, "Scope", "faint").pack(side="left", padx=(0, px(8)))
            text(row, f"All evidence, {plural(len(items), 'file')}", "strong").pack(side="left")
            link = text(row, "Narrow it down on the Evidence page", "link")
            link.pack(side="right")
            link.bind("<Button-1>", lambda _: self.app.navigate("evidence"))
        else:
            text(row, "Scope", "faint").pack(side="left", padx=(0, px(8)))
            text(row, f"{plural(len(items), 'file')} selected on the Evidence page", "strong").pack(side="left")
            link = text(row, "Use all evidence", "link")
            link.pack(side="right")
            link.bind("<Button-1>", lambda _: self.app.set_scope(None))

    def _build_menu(self) -> None:
        px = self.app.theme.px
        self.section_grids = {}
        for section in self.app.catalog.sections:
            head = tk.Frame(self.menu.body, bg=self.menu.body.cget("bg"))
            head.pack(fill="x", pady=(px(4), px(8)))
            text(head, section.title, "h2").pack(side="left")
            text(head, section.about, "muted").pack(side="left", padx=(px(12), 0))
            grid = tk.Frame(self.menu.body, bg=self.menu.body.cget("bg"))
            grid.pack(fill="x", pady=(0, px(18)))
            self.section_grids[section.id] = grid
            for task in self.app.catalog.tasks:
                if task.section == section.id:
                    self.cards[task.id] = _TaskCard(grid, self, task)
        self._reflow(self.menu.body.winfo_width())

    def _reflow(self, width: int) -> None:
        columns = 3 if width >= self.app.theme.px(1000) else 2
        if columns == self.columns:
            return
        self.columns = columns
        px = self.app.theme.px
        for section_id, grid in self.section_grids.items():
            cards = [card for card in self.cards.values() if card.task.section == section_id]
            for column in range(3):
                grid.columnconfigure(column, weight=1 if column < columns else 0, uniform="cards" if column < columns else "")
            for index, card in enumerate(cards):
                card.grid(row=index // columns, column=index % columns, sticky="nsew",
                          padx=(0, px(12)), pady=(0, px(12)))

    def _refresh_cards(self) -> None:
        for task_id, card in self.cards.items():
            card.paint(self.available.get(task_id, 0), task_id in self.selected, task_id == self.focused)

    # ----- selection -----

    def toggle(self, task: InvestigationTask) -> None:
        if not self.available.get(task.id):
            self.focus_task(task)
            return
        self._set_selected(self.selected ^ {task.id}, focus=task.id)

    def focus_task(self, task: InvestigationTask) -> None:
        self.focused = task.id
        self._refresh_cards()
        self._show_details()

    def _set_selected(self, selected: set[str], focus: str | None = None) -> None:
        self.selected = selected
        if focus:
            self.focused = focus
        self._refresh_cards()
        self._show_details()
        self._update_summary()

    def _select_all(self) -> None:
        # String extraction runs once per file, so it is left for the analyst to add on purpose.
        self._set_selected({task_id for task_id, count in self.available.items() if count and task_id != "strings"})

    def _picks(self):
        return [(task, self.ticked[task.id]) for task in self.app.catalog.tasks if task.id in self.selected]

    def _update_summary(self) -> None:
        picks = self._picks()
        if not picks:
            self.summary.configure(text="Choose one or more analyses on the left.")
            self.run_button.configure(state="disabled", text="Run analysis")
            return
        items = self.app.scope_items()
        choices = merge_choices(self.app.catalog, picks)
        jobs = plan(self.app.catalog, choices, items, self.app.items)
        files = len(coverage(choices, items))
        tools = {job.action.tool_id for job in jobs}
        missing = [tool for tool in tools if not self.app.toolbox.status(self.app.catalog.tool(tool)).installed]
        message = f"{plural(len(picks), 'analysis', 'analyses')}: {plural(len(jobs), 'tool task')} on {plural(files, 'file')}."
        if missing:
            message += f" {plural(len(missing), 'tool')} will be downloaded first."
        self.summary.configure(text=message)
        self.run_button.configure(state="normal" if jobs else "disabled",
                                  text=f"Run {len(picks)} analysis" if len(picks) == 1 else f"Run {len(picks)} analyses")

    def _run(self) -> None:
        picks = self._picks()
        if picks:
            self.app.start_run(merge_choices(self.app.catalog, picks), [task.id for task, _ in picks], self.app.scope_items())

    # ----- details panel -----

    def _show_details(self) -> None:
        self.details.clear()
        body = self.details.body
        px = self.app.theme.px
        pad = tk.Frame(body, bg=SURFACE)
        pad.pack(fill="both", expand=True, padx=px(18), pady=px(18))
        if self.focused is None:
            text(pad, "Analysis details", "h2").pack(anchor="w")
            text(pad, "Select a card to see which tools it runs, which evidence it uses, and how to read the results.",
                 "muted", wrap=FILL).pack(anchor="w", fill="x", pady=(px(6), 0))
            return
        task = self.app.catalog.task(self.focused)
        head = tk.Frame(pad, bg=SURFACE)
        head.pack(fill="x")
        icon(head, task.icon, size="icon_large", fg=ACCENT).pack(side="left", padx=(0, px(10)))
        text(head, task.title, "h2", wrap=260).pack(side="left")
        text(pad, task.question, "strong", wrap=FILL).pack(anchor="w", fill="x", pady=(px(10), px(6)))
        text(pad, task.about, "muted", wrap=FILL).pack(anchor="w", fill="x")

        items = self.app.scope_items()
        separator(pad).pack(fill="x", pady=px(14))
        text(pad, "Evidence in scope", "faint").pack(anchor="w", pady=(0, px(6)))
        every_step = merge_choices(self.app.catalog, [(task, [step.action_id for step in task.steps])])
        found = Counter(item.artifact.label for item in coverage(every_step, items) if item.artifact)
        if found:
            chips = tk.Frame(pad, bg=SURFACE)
            chips.pack(fill="x")
            for index, (label, count) in enumerate(found.most_common()):
                pill(chips, f"{label}  {count}", ACCENT, ACCENT_SOFT).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, px(6)), pady=px(2))
        else:
            text(pad, f"None of the files in scope fit this analysis. It reads {self._inputs_of(task)}.", "body", wrap=FILL).pack(anchor="w", fill="x")

        separator(pad).pack(fill="x", pady=px(14))
        text(pad, "Tools", "faint").pack(anchor="w", pady=(0, px(6)))
        for step in task.steps:
            action = self.app.catalog.action(step.action_id)
            count = len(coverage([step_choice(self.app.catalog, step)], items))
            installed = self.app.toolbox.status(self.app.catalog.tool(action.tool_id)).installed
            row = tk.Frame(pad, bg=SURFACE)
            row.pack(fill="x", pady=px(4))
            box = CheckBox(row, selected=step.action_id in self.ticked[task.id],
                           command=lambda value, action_id=step.action_id: self._tick(task, action_id, value))
            box.pack(side="left", anchor="n", pady=(px(2), 0))
            words = tk.Frame(row, bg=SURFACE)
            words.pack(side="left", fill="x", expand=True, padx=(px(10), 0))
            text(words, f"{action.tool_id}: {action.label}", "body", wrap=FILL).pack(anchor="w", fill="x")
            detail = plural(count, "file") if count else "no matching files"
            detail += "" if installed else "; the tool is downloaded when you run it"
            text(words, detail, "faint").pack(anchor="w")

        separator(pad).pack(fill="x", pady=px(14))
        text(pad, "Reading the results", "faint").pack(anchor="w", pady=(0, px(4)))
        text(pad, task.reading, "body", wrap=FILL).pack(anchor="w", fill="x")

    def _inputs_of(self, task: InvestigationTask) -> str:
        """The artifact types a task reads, as words."""
        catalog = self.app.catalog
        labels = set()
        for step in task.steps:
            for artifact_id in step.artifacts or catalog.action(step.action_id).artifacts:
                labels.add("any file" if artifact_id == ANY_ARTIFACT else catalog.artifact(artifact_id).label)
        return ", ".join(sorted(labels))

    def _tick(self, task: InvestigationTask, action_id: str, value: bool) -> None:
        if value:
            self.ticked[task.id].add(action_id)
        else:
            self.ticked[task.id].discard(action_id)
        if value and self.available.get(task.id):
            self.selected.add(task.id)
        self._refresh_cards()
        self._update_summary()


class _TaskCard(tk.Frame):
    """One menu entry; clicking it selects the analysis and shows its details."""

    def __init__(self, parent: tk.Misc, page: AnalyzePage, task: InvestigationTask):
        super().__init__(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER, cursor="hand2")
        self.page = page
        self.task = task
        px = page.app.theme.px
        inner = tk.Frame(self, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=px(16), pady=px(14))
        top = tk.Frame(inner, bg=SURFACE)
        top.pack(fill="x")
        self.badge = icon(top, task.icon, fg=ACCENT, bg=ACCENT_SOFT, width=2, pady=px(4))
        self.badge.pack(side="left")
        self.check = CheckBox(top, command=lambda _: page.toggle(task))
        self.check.pack(side="right", anchor="n")
        self.title = text(inner, task.title, "h3", wrap=250)
        self.title.pack(anchor="w", pady=(px(10), px(2)))
        self.question = text(inner, task.question, "muted", wrap=250)
        self.question.pack(anchor="w", fill="x")
        self.footer = tk.Frame(inner, bg=SURFACE)
        self.footer.pack(fill="x", side="bottom", pady=(px(12), 0))
        self.count = pill(self.footer, "")
        self.count.pack(side="left")
        tools = sorted({page.app.catalog.action(step.action_id).tool_id for step in task.steps})
        self.tools = text(self.footer, plural(len(tools), "tool"), "faint")
        self.tools.pack(side="left", padx=(px(8), 0))
        self._widgets = [self, inner, top, self.badge, self.title, self.question, self.footer, self.count, self.tools]
        for widget in self._widgets:
            widget.bind("<Button-1>", lambda _: page.toggle(task))
        self.bind("<Configure>", self._wrap)

    def _wrap(self, event) -> None:
        width = max(event.width - self.page.app.theme.px(36), 120)
        self.title.configure(wraplength=width)
        self.question.configure(wraplength=width)

    def paint(self, available: int, selected: bool, focused: bool) -> None:
        background = theme.ACCENT_SOFT if selected else SURFACE
        border = ACCENT if selected or focused else BORDER
        self.configure(highlightbackground=border, highlightcolor=border, highlightthickness=2 if selected or focused else 1)
        for widget in self._widgets:
            if widget is not self.badge and widget is not self.count:
                widget.configure(bg=background)
        self.check.configure(bg=background)
        self.check.set(selected)
        if available:
            self.count.configure(text=plural(available, "file"), fg=ACCENT, bg=SURFACE if selected else ACCENT_SOFT)
            self.title.configure(fg=theme.TEXT)
            self.badge.configure(fg=ACCENT, bg=SURFACE if selected else ACCENT_SOFT)
        else:
            self.count.configure(text="No matching evidence", fg=MUTED, bg=theme.NEUTRAL_SOFT)
            self.title.configure(fg=MUTED)
            self.badge.configure(fg=theme.FAINT, bg=theme.NEUTRAL_SOFT)
