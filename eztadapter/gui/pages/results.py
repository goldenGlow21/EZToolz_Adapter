"""Results: every analysis, its tasks grouped by the question they answer, and their output files.

A run in progress is shown live from the runner's events; finished runs are
read back from their run.json, so the history survives restarts.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ...fsutil import long_path
from ...history import RunRecord, group_by_task, list_runs
from ...planner import Job
from ...runner import JOB_LOG_NAME, JobFinished, JobStarted, LogText, RunFinished
from .. import theme
from ..theme import ACCENT, ACCENT_SOFT, SURFACE
from ..widgets import FILL, plural, Card, PageHeader, ScrollArea, empty_state, human_size, icon, open_path, run_time, separator, status_pill, text
from .base import Page
from .preview import PREVIEWABLE

_SHOWN_OUTPUTS = 6
_LOG_LINES = 4000


class ResultsPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        px = app.theme.px
        self.runs: list[RunRecord] = []
        self.current: str | None = None
        self.live: dict | None = None
        self.selected_job: int | None = None
        self.expanded: set[int] = set()
        self._rendered: str | None = None

        header = PageHeader(self.content, "Results", "Each analysis with its tasks, statuses and output files.")
        header.pack(fill="x")
        header.button("Open output folder", lambda: open_path(app.workspace.output_dir))
        header.button("Refresh", self.runs_changed)

        split = tk.Frame(self.content, bg=self.content.cget("bg"))
        split.pack(fill="both", expand=True, pady=(px(18), 0))
        self.list_card = Card(split, padding=0, width=px(300))
        self.list_card.pack(side="left", fill="y")
        self.list_card.pack_propagate(False)
        text(self.list_card.body, "Analyses", "h3").pack(anchor="w", padx=px(16), pady=(px(14), px(8)))
        self.run_list = ScrollArea(self.list_card.body, bg=SURFACE)
        self.run_list.pack(fill="both", expand=True)

        right = tk.Frame(split, bg=self.content.cget("bg"))
        right.pack(side="left", fill="both", expand=True, padx=(px(16), 0))
        self.report = ScrollArea(right)
        self.report.pack(fill="both", expand=True)

        self.log_card = Card(right, padding=0)
        self.log_card.pack(fill="x", pady=(px(12), 0))
        log_head = tk.Frame(self.log_card.body, bg=SURFACE)
        log_head.pack(fill="x", padx=px(14), pady=px(8))
        self.log_title = text(log_head, "Log", "strong")
        self.log_title.pack(side="left")
        self.log_toggle = text(log_head, "Show", "link")
        self.log_toggle.pack(side="right")
        self.log_toggle.bind("<Button-1>", lambda _: self._toggle_log())
        self.log = ScrolledText(self.log_card.body, height=12, wrap="none", font=app.theme.fonts.mono, relief="flat",
                                borderwidth=0, background=theme.SURFACE_ALT, foreground=theme.TEXT, state="disabled")
        self.log_visible = False

    # ----- hooks -----

    def shown(self) -> None:
        if not self.runs and self.live is None:
            self.runs_changed()

    def runs_changed(self) -> None:
        self.runs = list_runs(self.app.workspace.output_dir)
        if self.live and self.live.get("finished"):
            self.live = None
        if self.current is None and self.runs:
            self.current = self.runs[0].name
        self._fill_list()
        self._render()

    def folders_changed(self) -> None:
        self.current = None
        self.runs_changed()

    def select_run(self, name: str) -> None:
        self.current = name
        self.selected_job = None
        self.expanded = set()
        self.runs_changed()

    # ----- live run -----

    def begin_run(self, folder: Path, jobs: list[Job], task_ids: list[str]) -> None:
        self.live = {
            "name": folder.name,
            "folder": folder,
            "tasks": list(task_ids),
            "jobs": [{"title": job.title, "action": job.action.id, "status": "queued", "message": "", "outputs": [],
                      "warnings": [], "folder": None} for job in jobs],
            "logs": {},
            "running": None,
            "finished": False,
        }
        self.current = folder.name
        self.selected_job = None
        self.expanded = set()
        self._fill_list()
        self._render()

    def on_run_event(self, event) -> None:
        live = self.live
        if live is None:
            return
        if isinstance(event, JobStarted):
            live["jobs"][event.index]["status"] = "running"
            live["running"] = event.index
            live["logs"][event.index] = []
            following = self.current == live["name"]
            if following and (self.selected_job is None or live["jobs"][self.selected_job]["status"] != "running"):
                self.selected_job = event.index
                self._show_log()
            self.app.set_progress(event.index / event.total, f"Task {event.index + 1} of {event.total}: {event.title}")
            self._render()
            self._fill_list()
        elif isinstance(event, LogText):
            live["logs"].setdefault(event.index, []).append(event.text)
            if self.current == live["name"] and self.selected_job == event.index and self.log_visible:
                self._append_log(event.text)
        elif isinstance(event, JobFinished):
            live["jobs"][event.index] = event.result.to_json(live["folder"])
            live["running"] = None
            self._render()
        elif isinstance(event, RunFinished):
            live["finished"] = True
            self.runs_changed()

    # ----- run list -----

    def _fill_list(self) -> None:
        self.run_list.clear()
        px = self.app.theme.px
        entries = []
        if self.live and not self.live["finished"]:
            entries.append((self.live["name"], None))
        entries += [(record.name, record) for record in self.runs if not (self.live and record.name == self.live["name"] and not self.live["finished"])]
        if not entries:
            text(self.run_list.body, "No analyses yet.", "muted").pack(anchor="w", padx=px(16), pady=px(6))
            return
        for name, record in entries:
            selected = name == self.current
            background = ACCENT_SOFT if selected else SURFACE
            row = tk.Frame(self.run_list.body, bg=background, cursor="hand2")
            row.pack(fill="x")
            tk.Frame(row, bg=ACCENT if selected else background, width=px(3)).pack(side="left", fill="y")
            inner = tk.Frame(row, bg=background)
            inner.pack(side="left", fill="x", expand=True, padx=px(13), pady=px(9))
            text(inner, run_time(name), "strong", bg=background).pack(anchor="w")
            line = tk.Frame(inner, bg=background)
            line.pack(anchor="w", pady=(px(3), 0))
            if record is None:
                done = sum(1 for job in self.live["jobs"] if job["status"] not in ("queued", "running"))
                status_pill(line, "running").pack(side="left")
                text(line, f"{done}/{len(self.live['jobs'])}", "small", bg=background).pack(side="left", padx=(px(6), 0))
            elif record.error:
                status_pill(line, "failed").pack(side="left")
            else:
                for status, count in sorted(record.counts.items()):
                    status_pill(line, status).pack(side="left")
                    text(line, str(count), "small", bg=background).pack(side="left", padx=(px(4), px(8)))
            for widget in (row, inner, line, *inner.winfo_children(), *line.winfo_children()):
                widget.bind("<Button-1>", lambda _, name=name: self.select_run(name))
            separator(self.run_list.body).pack(fill="x")

    # ----- report -----

    def _model(self) -> dict | None:
        if self.live and self.current == self.live["name"]:
            return self.live
        for record in self.runs:
            if record.name == self.current:
                return {"name": record.name, "folder": record.folder, "tasks": record.manifest.get("tasks", []),
                        "jobs": record.jobs, "error": record.error, "finished": record.finished, "running": None,
                        "evidence": record.manifest.get("evidence_folder", "")}
        return None

    def _render(self) -> None:
        # A run in progress re-renders after every task; keep the reader's place in it.
        position = self.report.canvas.yview()[0] if self._rendered == self.current else 0.0
        self._rendered = self.current
        self.report.clear()
        self._draw()
        if position:
            self.report.canvas.update_idletasks()
            self.report.canvas.yview_moveto(position)

    def _draw(self) -> None:
        body = self.report.body
        px = self.app.theme.px
        model = self._model()
        if model is None:
            empty_state(body, "results", "No analysis selected",
                        "Run an analysis from the Analyze page; its results appear here.",
                        "Go to Analyze", lambda: self.app.navigate("analyze")).pack(fill="x")
            return
        jobs = model["jobs"]
        head = tk.Frame(body, bg=body.cget("bg"))
        head.pack(fill="x", pady=(0, px(12)))
        text(head, f"Analysis {run_time(model['name'])}", "h2").pack(side="left")
        ttk.Button(head, text="Open folder", style="Secondary.TButton", command=lambda: open_path(model["folder"])).pack(side="right")
        if model.get("error"):
            text(body, model["error"], "body", fg=theme.DANGER).pack(anchor="w")
            return
        counts = {}
        for job in jobs:
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        chips = tk.Frame(body, bg=body.cget("bg"))
        chips.pack(fill="x", pady=(0, px(12)))
        for status in ("ok", "warning", "empty", "failed", "skipped", "cancelled", "running", "queued"):
            if counts.get(status):
                status_pill(chips, status).pack(side="left")
                text(chips, str(counts[status]), "small").pack(side="left", padx=(px(4), px(12)))
        if model is self.live and not model["finished"]:
            progress = ttk.Progressbar(chips, length=px(220), mode="determinate", maximum=max(len(jobs), 1),
                                       value=sum(1 for job in jobs if job["status"] not in ("queued", "running")),
                                       style="Accent.Horizontal.TProgressbar")
            progress.pack(side="right")

        for task, indexes in group_by_task(self.app.catalog, model["tasks"], jobs):
            section = Card(body, padding=0)
            section.pack(fill="x", pady=(0, px(14)))
            top = tk.Frame(section.body, bg=SURFACE)
            top.pack(fill="x", padx=px(16), pady=(px(14), px(4)))
            icon(top, task.icon if task else "wrench", fg=ACCENT).pack(side="left", padx=(0, px(8)))
            text(top, task.title if task else "Individual tools", "h3").pack(side="left")
            if task:
                text(section.body, task.reading, "muted", wrap=FILL).pack(anchor="w", fill="x", padx=px(16), pady=(0, px(8)))
            for index in indexes:
                separator(section.body).pack(fill="x")
                self._job_row(section.body, model, index)

    def _job_row(self, parent: tk.Frame, model: dict, index: int) -> None:
        px = self.app.theme.px
        job = model["jobs"][index]
        selected = index == self.selected_job
        background = theme.SURFACE_ALT if selected else SURFACE
        row = tk.Frame(parent, bg=background)
        row.pack(fill="x")
        line = tk.Frame(row, bg=background, cursor="hand2")
        line.pack(fill="x", padx=px(16), pady=(px(10), px(4)))
        status_pill(line, job["status"]).pack(side="left")
        title = text(line, job["title"], "strong", bg=background)
        title.pack(side="left", padx=(px(10), 0))
        if job["outputs"]:
            text(line, plural(len(job["outputs"]), "file"), "faint", bg=background).pack(side="right")
        for widget in (line, title):
            widget.bind("<Button-1>", lambda _, index=index: self._select_job(index))
        if job["message"] and job["status"] != "ok":
            text(row, job["message"], "small", bg=background, wrap=FILL).pack(anchor="w", fill="x", padx=px(16 + 70))
        for warning in job.get("warnings", []):
            text(row, warning, "small", fg=theme.WARN, bg=background, wrap=FILL).pack(anchor="w", fill="x", padx=px(16 + 70))
        if job["folder"]:
            folder = model["folder"] / job["folder"]
            outputs = job["outputs"]
            shown = outputs if index in self.expanded else outputs[:_SHOWN_OUTPUTS]
            for relative in shown:
                self._output_row(row, folder / relative, background)
            if len(outputs) > len(shown):
                more = text(row, f"Show all {len(outputs)} files", "link", bg=background)
                more.pack(anchor="w", padx=px(16 + 70), pady=(px(2), 0))
                more.bind("<Button-1>", lambda _, index=index: self._expand(index))
        tk.Frame(row, bg=background, height=px(8)).pack(fill="x")

    def _output_row(self, parent: tk.Frame, path: Path, background: str) -> None:
        px = self.app.theme.px
        row = tk.Frame(parent, bg=background)
        row.pack(fill="x", padx=(px(16 + 70), px(16)), pady=px(1))
        # Links first, so a long file name is clipped rather than the links.
        viewer = self.app.toolbox.viewer_for(path)
        label = f"Open in {viewer.tool.id}" if viewer else "Open"
        open_link = text(row, label, "link", bg=background)
        open_link.pack(side="right")
        open_link.bind("<Button-1>", lambda _: self.app.open_output(path))
        if path.suffix.lower() in PREVIEWABLE:
            preview = text(row, "Preview", "link", bg=background)
            preview.pack(side="right", padx=(0, px(14)))
            preview.bind("<Button-1>", lambda _: self.app.preview(path))
        size = os.path.getsize(long_path(path)) if os.path.exists(long_path(path)) else 0
        text(row, human_size(size), "faint", bg=background).pack(side="right", padx=(px(8), px(14)))
        icon(row, "document", size="icon_small", fg=theme.FAINT, bg=background).pack(side="left")
        name = text(row, path.name, "body", bg=background, cursor="hand2")
        name.pack(side="left", padx=(px(6), 0))
        name.bind("<Button-1>", lambda _: self._preview_or_open(path))

    def _preview_or_open(self, path: Path) -> None:
        if path.suffix.lower() in PREVIEWABLE:
            self.app.preview(path)
        else:
            self.app.open_output(path)

    def _expand(self, index: int) -> None:
        self.expanded.add(index)
        self._render()

    def _select_job(self, index: int) -> None:
        self.selected_job = index
        self._render()
        self._show_log()

    # ----- log -----

    def _toggle_log(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log.pack(fill="both", expand=True, padx=1, pady=(0, 1))
            self.log_toggle.configure(text="Hide")
            self._show_log()
        else:
            self.log.pack_forget()
            self.log_toggle.configure(text="Show")

    def _show_log(self) -> None:
        model = self._model()
        if model is None or self.selected_job is None or self.selected_job >= len(model["jobs"]):
            self.log_title.configure(text="Log")
            self._set_log("")
            return
        job = model["jobs"][self.selected_job]
        self.log_title.configure(text=f"Log: {job['title']}")
        if not self.log_visible:
            return
        if model is self.live and self.selected_job in self.live["logs"] and job["folder"] is None:
            self._set_log("\n".join(self.live["logs"][self.selected_job][-_LOG_LINES:]))
        elif job["folder"]:
            self._set_log(_tail(model["folder"] / job["folder"] / JOB_LOG_NAME))
        else:
            self._set_log("Waiting for earlier tasks.")

    def _set_log(self, content: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", content)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", ("\n" if self.log.index("end-1c") != "1.0" else "") + line)
        excess = int(self.log.index("end-1c").split(".")[0]) - _LOG_LINES
        if excess > 0:
            self.log.delete("1.0", f"{excess + 1}.0")
        self.log.see("end")
        self.log.configure(state="disabled")


def _tail(path: Path, limit: int = 2_000_000) -> str:
    try:
        with open(long_path(path), "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            handle.seek(max(0, size - limit))
            data = handle.read()
    except FileNotFoundError:
        return "(no log was written for this task)"
    content = data.decode("utf-8", errors="replace")
    return ("... (earlier lines are in job.log)\n" + content.split("\n", 1)[-1]) if size > limit else content
