"""Main window: navigation sidebar, the pages, a status bar, and the flows that span pages.

Pages follow the order of the work: Overview, Evidence, Analyze, Results,
then Tools and Settings. Flows that cross pages live here: installing missing
tools before a run, running jobs, and opening files in the right viewer.
"""

from __future__ import annotations

import subprocess
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from ..catalog import Catalog, Tool
from ..evidence import EvidenceItem, Scanner
from ..planner import Choice, plan
from ..runner import STATUS_OK, new_run_folder, run_jobs
from ..staging import copy_evidence
from ..toolbox import Toolbox
from ..workspace import Workspace
from . import theme
from .installing import InstallFinished, InstallProgress, UpdateFound, install_work
from .pages.analyze import AnalyzePage
from .pages.evidence import EvidencePage
from .pages.overview import OverviewPage
from .pages.preview import PreviewPage
from .pages.results import ResultsPage
from .pages.settings import SettingsPage
from .pages.tools import ToolsPage
from .theme import BG, SIDEBAR, SIDEBAR_ACTIVE, SIDEBAR_HOVER, SIDEBAR_TEXT, SURFACE
from .widgets import LicenceDialog, open_path, open_url, plural, reveal, text
from .worker import Worker

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Output types safe to hand to their default Windows application.
_DOCUMENT_EXTENSIONS = {".csv", ".tsv", ".txt", ".log", ".html", ".htm", ".json", ".jsonl", ".xml", ".md"}

NAVIGATION = (
    ("overview", "Overview", "home"),
    ("evidence", "Evidence", "evidence"),
    ("analyze", "Analyze", "analyze"),
    ("results", "Results", "results"),
    ("tools", "Tools", "tools"),
    ("settings", "Settings", "settings"),
)


class App(tk.Tk):
    def __init__(self, workspace: Workspace, catalog: Catalog):
        super().__init__()
        self.workspace = workspace
        self.catalog = catalog
        self.toolbox = Toolbox(catalog, workspace)
        self.scanner = Scanner(catalog)
        self.theme = theme.install(self)
        self.items: list[EvidenceItem] = []
        # Files chosen on the Evidence page to narrow an analysis; None means all evidence.
        self.scope: list[EvidenceItem] | None = None
        self._scanning = False
        self._scan_signature: tuple | None = None

        self.title("EZToolz Adapter")
        px = self.theme.px
        self.geometry(f"{px(1360)}x{px(860)}")
        self.minsize(px(1100), px(700))
        icon_file = ASSETS / "app.ico"
        if icon_file.is_file():
            self.iconbitmap(default=str(icon_file))
        self.worker = Worker(self, self._dispatch)

        self._build_sidebar()
        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self._build_status_bar(main)
        self.page_area = tk.Frame(main, bg=BG)
        self.page_area.pack(fill="both", expand=True)
        self.pages = {
            "overview": OverviewPage(self.page_area, self),
            "evidence": EvidencePage(self.page_area, self),
            "analyze": AnalyzePage(self.page_area, self),
            "results": ResultsPage(self.page_area, self),
            "preview": PreviewPage(self.page_area, self),
            "tools": ToolsPage(self.page_area, self),
            "settings": SettingsPage(self.page_area, self),
        }
        for page in self.pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.current_page = ""
        self.navigate("overview")
        self.rescan()

        self.bind("<FocusIn>", self._on_focus)
        self.bind("<F5>", lambda _: self.rescan())
        for number, (name, _, _) in enumerate(NAVIGATION, start=1):
            self.bind(f"<Control-Key-{number}>", lambda _, name=name: self.navigate(name))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def destroy(self) -> None:
        self.worker.stop()
        super().destroy()

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        # Tk would print this to stderr, which does not exist in the windowed exe.
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        messagebox.showerror("Unexpected error", f"{exc_value}\n\nDetails:\n{details[-1500:]}")

    # ----- layout -----

    def _build_sidebar(self) -> None:
        px = self.theme.px
        fonts = self.theme.fonts
        bar = tk.Frame(self, bg=SIDEBAR, width=px(230))
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        brand = tk.Frame(bar, bg=SIDEBAR)
        brand.pack(fill="x", padx=px(18), pady=(px(22), px(26)))
        logo = tk.Canvas(brand, width=px(36), height=px(36), bg=SIDEBAR, highlightthickness=0)
        logo.pack(side="left")
        _rounded_rectangle(logo, 0, 0, px(36), px(36), px(9), fill=theme.ACCENT)
        logo.create_text(px(18), px(18), text=fonts.glyph("search") or "EZ", fill="#ffffff", font=fonts.icon)
        names = tk.Frame(brand, bg=SIDEBAR)
        names.pack(side="left", padx=(px(10), 0))
        tk.Label(names, text="EZToolz Adapter", font=fonts.h3, fg="#ffffff", bg=SIDEBAR).pack(anchor="w")
        tk.Label(names, text="Forensic toolkit", font=fonts.small, fg=SIDEBAR_TEXT, bg=SIDEBAR).pack(anchor="w")

        tk.Label(bar, text="WORKSPACE", font=fonts.small, fg="#5d6880", bg=SIDEBAR).pack(anchor="w", padx=px(22), pady=(0, px(6)))
        self.nav_items = {}
        for name, label, glyph in NAVIGATION:
            self.nav_items[name] = _NavItem(bar, label, glyph, lambda name=name: self.navigate(name))
            self.nav_items[name].pack(fill="x", padx=px(10), pady=px(1))

        footer = tk.Frame(bar, bg=SIDEBAR)
        footer.pack(side="bottom", fill="x", padx=px(22), pady=px(18))
        self.sidebar_activity = tk.Label(footer, text="", font=fonts.small, fg="#8fb0ff", bg=SIDEBAR, anchor="w", justify="left", wraplength=px(190))
        self.sidebar_activity.pack(anchor="w", pady=(0, px(6)))
        tk.Label(footer, text=f"Version {__version__}", font=fonts.small, fg="#5d6880", bg=SIDEBAR).pack(anchor="w")

    def _build_status_bar(self, parent: tk.Frame) -> None:
        px = self.theme.px
        bar = tk.Frame(parent, bg=SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        bar.pack(side="bottom", fill="x")
        inner = tk.Frame(bar, bg=SURFACE)
        inner.pack(fill="x", padx=px(20), pady=px(7))
        self.status_text = text(inner, "Ready.", "small")
        self.status_text.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(inner, text="Cancel", style="Secondary.TButton", command=self._cancel)
        self.progress = ttk.Progressbar(inner, length=px(260), mode="determinate", maximum=1.0, style="Accent.Horizontal.TProgressbar")

    # ----- navigation and status -----

    def navigate(self, name: str) -> None:
        self.current_page = name
        page = self.pages[name]
        page.tkraise()
        for item_name, item in self.nav_items.items():
            item.set_active(item_name == name or (name == "preview" and item_name == "results"))
        page.shown()

    def set_status(self, message: str) -> None:
        self.status_text.configure(text=message)

    def begin_busy(self, message: str) -> None:
        self.set_status(message)
        self.progress.configure(value=0)
        self.cancel_button.pack(side="right")
        self.progress.pack(side="right", padx=(0, self.theme.px(10)))
        self.sidebar_activity.configure(text=message)

    def set_progress(self, fraction: float, message: str | None = None) -> None:
        self.progress.configure(value=fraction)
        if message:
            self.set_status(message)
            self.sidebar_activity.configure(text=message)

    def end_busy(self, message: str = "Ready.") -> None:
        self.progress.pack_forget()
        self.cancel_button.pack_forget()
        self.sidebar_activity.configure(text="")
        self.set_status(message)

    def _cancel(self) -> None:
        self.worker.cancel()
        self.set_status("Cancelling...")

    # ----- evidence -----

    def rescan(self, quiet: bool = False) -> None:
        folder = self.workspace.evidence_dir
        if self._scanning:
            return
        if not folder.is_dir():
            self.items, self._scan_signature, self.scope = [], None, None
            self.broadcast("evidence_changed")
            return
        self._scanning = True
        if not quiet:
            self.set_status(f"Scanning {folder}...")

        def done(items, error):
            self._scanning = False
            if error:
                self.set_status(f"Could not scan the evidence folder: {error}")
                if not quiet:
                    messagebox.showerror("Scan failed", f"Could not scan {folder}:\n{error}")
                return
            signature = tuple((item.rel, item.size, item.mtime_ns) for item in items)
            if signature != self._scan_signature:
                self._scan_signature = signature
                self.items = items
                if self.scope is not None:
                    current = {item.rel: item for item in items}
                    self.scope = [current[item.rel] for item in self.scope if item.rel in current] or None
                self.broadcast("evidence_changed")
            if not quiet:
                recognised = sum(1 for item in items if item.artifact)
                self.set_status(f"{plural(len(items), 'evidence file')}, {recognised:,} recognised.")

        self.worker.background(lambda: self.scanner.scan(folder), done)

    def scope_items(self) -> list[EvidenceItem]:
        return list(self.items) if self.scope is None else list(self.scope)

    def set_scope(self, items: list[EvidenceItem] | None) -> None:
        self.scope = items or None
        self.broadcast("evidence_changed")

    def change_folder(self, key: str) -> None:
        if self.worker.busy_label:
            messagebox.showinfo("Change folder", "Wait until the current task finishes.")
            return
        current = self.workspace.evidence_dir if key == "evidence" else self.workspace.output_dir
        chosen = filedialog.askdirectory(initialdir=str(current), title=f"Choose the {key} folder")
        if not chosen:
            return
        evidence = Path(chosen) if key == "evidence" else self.workspace.evidence_dir
        output = Path(chosen) if key == "output" else self.workspace.output_dir
        try:
            self.workspace.change_folders(evidence, output)
        except ValueError as error:
            messagebox.showerror("Change folder", str(error))
            return
        self.scope = None
        self._scan_signature = None
        self.rescan()
        self.broadcast("folders_changed")

    # ----- tools -----

    def install_tools(self, tools: list[Tool], then=None) -> None:
        """Install tools after asking for any licence not yet accepted; `then` runs once they are done."""
        if self.worker.busy_label:
            messagebox.showinfo("Install", f"Wait until the current task finishes ({self.worker.busy_label}).")
            return
        tools = self._accept_licences(tools)
        if not tools:
            return

        def done(failures, error):
            self.broadcast("tools_changed")
            installed = len(tools) - len(failures or {})
            self.end_busy(f"Installed {installed} of {plural(len(tools), 'tool')}.")
            if error:
                messagebox.showerror("Install", f"Installation stopped: {error}")
            elif failures:
                details = "\n\n".join(f"{tool_id}: {reason}" for tool_id, reason in failures.items())
                messagebox.showwarning("Install", f"{plural(len(failures), 'tool')} could not be installed:\n\n{details}")
            if then and not error:
                then()

        self.worker.start("Installing tools", install_work(tools, self.workspace.tools_dir), done)
        self.begin_busy(f"Installing {plural(len(tools), 'tool')}...")

    def _accept_licences(self, tools: list[Tool]) -> list[Tool]:
        pending: dict[str, list[Tool]] = {}
        for tool in tools:
            if tool.license and tool.license not in self.workspace.accepted_licenses:
                pending.setdefault(tool.license, []).append(tool)
        declined = set()
        for url, group in pending.items():
            if LicenceDialog(self, url, [tool.id for tool in group]).accepted:
                self.workspace.accepted_licenses.add(url)
                self.workspace.save()
            else:
                declined.update(tool.id for tool in group)
        return [tool for tool in tools if tool.id not in declined]

    def launch(self, tool: Tool) -> None:
        status = self.toolbox.status(tool)
        if status.problem or status.gui is None:
            messagebox.showerror("Launch", status.problem or f"{tool.id} has no window to open.")
            return
        subprocess.Popen([str(status.gui)], cwd=str(status.gui.parent))

    # ----- runs -----

    def start_run(self, choices: list[Choice], task_ids: list[str], items: list[EvidenceItem], offer_install: bool = True) -> None:
        """Plan and run the choices over `items`, installing missing tools first if the user agrees."""
        if self.worker.busy_label:
            messagebox.showinfo("Run", f"Wait until the current task finishes ({self.worker.busy_label}).")
            return
        jobs = plan(self.catalog, choices, items, self.items)
        if not jobs:
            messagebox.showinfo("Run", "None of the chosen tools apply to the files in scope.")
            return
        needed = list(dict.fromkeys(self.catalog.tool(job.action.tool_id) for job in jobs))
        statuses = [self.toolbox.status(tool) for tool in needed]
        missing = [status.tool for status in statuses if not status.installed]
        if missing and offer_install:
            names = "\n".join(f"  {tool.id}" for tool in missing)
            if not messagebox.askyesno("Download tools", f"These tools are needed and not installed yet:\n\n{names}\n\nDownload them now and then start?"):
                return
            self.install_tools(missing, then=lambda: self.start_run(choices, task_ids, items, offer_install=False))
            return
        for requirement in {status.missing_requirement for status in statuses if status.installed and status.missing_requirement}:
            users = ", ".join(status.tool.id for status in statuses if status.missing_requirement == requirement)
            if messagebox.askyesno(
                "Runtime missing",
                f"{users} need the {requirement.label}, which is not installed. Their tasks will fail until it is.\n\n"
                f"Open the Microsoft download page now?",
            ):
                open_url(requirement.download)
        if not self.workspace.output_dir.is_dir():
            messagebox.showerror("Run", f"The output folder does not exist: {self.workspace.output_dir}\nChoose another one in Settings.")
            return

        run_folder = new_run_folder(self.workspace.output_dir)
        binaries = self.toolbox.binaries()
        evidence_dir = self.workspace.evidence_dir
        self.pages["results"].begin_run(run_folder, jobs, task_ids)
        self.navigate("results")

        def work(report, cancel):
            return run_jobs(jobs, binaries, run_folder, evidence_dir, task_ids, report, cancel)

        def done(results, error):
            if error:
                self.end_busy("The run stopped because of an error.")
                messagebox.showerror("Run", f"The run stopped: {error}")
            else:
                ok = sum(1 for result in results if result.status == STATUS_OK)
                self.end_busy(f"Analysis finished: {ok} of {plural(len(results), 'task')} OK.")
            self.broadcast("runs_changed")

        self.worker.start("Analysis", work, done)
        self.begin_busy(f"Running {plural(len(jobs), 'task')}...")

    # ----- opening files -----

    def open_output(self, path: Path) -> None:
        """Open a result file in its viewer, its default application if harmless, or Explorer."""
        viewer = self.toolbox.viewer_for(path)
        if viewer:
            subprocess.Popen([str(viewer.gui), str(path)], cwd=str(viewer.gui.parent))
        elif path.suffix.lower() in _DOCUMENT_EXTENSIONS:
            open_path(path)
        else:
            reveal(path)

    def open_evidence(self, item: EvidenceItem) -> None:
        """Open a working copy of an evidence file in its viewer, never the evidence itself.

        Viewers such as Registry Explorer offer to save replayed hives; on a
        copy that can never touch the original. Without a viewer the file is
        shown in Explorer rather than started, since evidence may be malware.
        """
        viewer = self.toolbox.viewer_for(item.path, item.artifact.id if item.artifact else None)
        if viewer is None:
            reveal(item.path)
            return
        folder = self.workspace.output_dir / "_viewer" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        copies = [item] + [other for other in self.items if other.folder == item.folder and other.name.casefold().startswith(item.name.casefold() + ".log")]
        for source in copies:
            copy_evidence(source.path, folder / source.name)
        subprocess.Popen([str(viewer.gui), str(folder / item.name)], cwd=str(viewer.gui.parent))
        self.set_status(f"Opened a working copy of {item.name} in {viewer.tool.id}: {folder}")

    def preview(self, path: Path) -> None:
        self.pages["preview"].load(path)
        self.navigate("preview")

    # ----- events -----

    def broadcast(self, event: str) -> None:
        """Tell every page about a change, by calling its hook of that name."""
        for page in self.pages.values():
            getattr(page, event)()

    def _dispatch(self, event) -> None:
        if isinstance(event, (InstallProgress, InstallFinished, UpdateFound)):
            self.pages["tools"].on_install_event(event)
            if isinstance(event, InstallProgress) and event.total:
                self.set_progress(event.done / event.total, f"Downloading {event.tool_id}... {event.done * 100 // event.total}%")
        else:
            self.pages["results"].on_run_event(event)

    def _on_focus(self, event) -> None:
        # Files are usually copied into the evidence folder with Explorer; rescan when the window comes back.
        if event.widget is self:
            self.rescan(quiet=True)

    def _on_close(self) -> None:
        if not self.worker.busy_label:
            self.destroy()
            return
        if messagebox.askyesno("Quit", f"{self.worker.busy_label} is still in progress. Stop it and quit?"):
            self.worker.cancel()
            self._close_when_idle()

    def _close_when_idle(self) -> None:
        if self.worker.busy_label:
            self.after(200, self._close_when_idle)
        else:
            self.destroy()


class _NavItem(tk.Frame):
    """One sidebar entry: icon and label, highlighted on hover and when active."""

    def __init__(self, parent: tk.Misc, label: str, glyph: str, command):
        super().__init__(parent, bg=SIDEBAR, cursor="hand2")
        current = theme.get()
        px = current.px
        self.active = False
        self.marker = tk.Frame(self, bg=SIDEBAR, width=px(3))
        self.marker.pack(side="left", fill="y")
        self.icon = tk.Label(self, text=current.fonts.glyph(glyph), font=current.fonts.icon, fg=SIDEBAR_TEXT, bg=SIDEBAR, width=2)
        self.icon.pack(side="left", padx=(px(10), px(6)), pady=px(9))
        self.label = tk.Label(self, text=label, font=current.fonts.body, fg=SIDEBAR_TEXT, bg=SIDEBAR, anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        for widget in (self, self.icon, self.label, self.marker):
            widget.bind("<Button-1>", lambda _: command())
            widget.bind("<Enter>", lambda _: self._paint(hover=True))
            widget.bind("<Leave>", lambda _: self._paint(hover=False))

    def set_active(self, active: bool) -> None:
        self.active = active
        self._paint(hover=False)

    def _paint(self, hover: bool) -> None:
        background = SIDEBAR_ACTIVE if self.active else (SIDEBAR_HOVER if hover else SIDEBAR)
        foreground = "#ffffff" if self.active or hover else SIDEBAR_TEXT
        for widget in (self, self.icon, self.label):
            widget.configure(bg=background)
        self.icon.configure(fg="#8fb0ff" if self.active else foreground)
        self.label.configure(fg=foreground, font=theme.get().fonts.strong if self.active else theme.get().fonts.body)
        self.marker.configure(bg=theme.ACCENT if self.active else background)


def _rounded_rectangle(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **options) -> None:
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    canvas.create_polygon(points, smooth=True, **options)
