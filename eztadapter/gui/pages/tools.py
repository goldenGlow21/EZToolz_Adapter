"""Tools: what is installed, install or update tools, start the interactive viewers."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ...catalog import ANY_ARTIFACT, Tool
from ...installer import InstallError, Release, uninstall
from ..installing import InstallFinished, InstallProgress, UpdateFound, update_work
from ..theme import ACCENT, ACCENT_SOFT, MUTED, NEUTRAL_SOFT, OK, OK_SOFT, SURFACE, WARN, WARN_SOFT
from ..widgets import FILL, Banner, Card, PageHeader, open_path, open_url, pill, separator, table, text
from .base import Page


class ToolsPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        px = app.theme.px
        self.latest: dict[str, Release] = {}
        self.progress: dict[str, str] = {}

        self.header = PageHeader(self.content, "Tools", "")
        self.header.pack(fill="x")
        self.header.button("Open tools folder", lambda: open_path(app.workspace.tools_dir))
        self.header.button("Check for updates", self._check_updates)
        self.header.button("Install all", self._install_all)
        self.header.button("Install recommended", self._install_recommended, style="Primary.TButton")
        self.banners = tk.Frame(self.content, bg=self.content.cget("bg"))
        self.banners.pack(fill="x", pady=(px(14), 0))
        self.summary = text(self.content, "", "muted")
        self.summary.pack(anchor="w", pady=(px(12), px(8)))

        split = tk.Frame(self.content, bg=self.content.cget("bg"))
        split.pack(fill="both", expand=True)
        self.details = Card(split, width=px(360))
        self.details.pack(side="right", fill="y", padx=(px(16), 0))
        self.details.pack_propagate(False)
        self.tree = table(split, {"status": ("Status", 180, False), "version": ("Version", 110, False),
                                  "recommended": ("Recommended", 120, True)},
                          tree_heading="Tool", selectmode="browse")
        self.tree.holder.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("ready", foreground=OK)
        self.tree.tag_configure("attention", foreground=WARN)
        self.tree.tag_configure("busy", foreground=ACCENT)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._fill_details())
        self.tree.bind("<Double-1>", lambda _: self._launch_selected())
        self.used_in = {tool.id: [] for tool in app.catalog.tools}
        for task in app.catalog.tasks:
            for step in task.steps:
                tool_id = app.catalog.action(step.action_id).tool_id
                if task.title not in self.used_in[tool_id]:
                    self.used_in[tool_id].append(task.title)
        self._fill_table()

    # ----- hooks -----

    def shown(self) -> None:
        self.header.subtitle.configure(text=f"Downloaded from their official sources into {self.app.workspace.tools_dir}")
        self._fill_table()

    def tools_changed(self) -> None:
        self._fill_table()

    def on_install_event(self, event) -> None:
        if isinstance(event, InstallProgress):
            share = f"{event.done * 100 // event.total}%" if event.total else f"{event.done // 1_000_000} MB"
            self.progress[event.tool_id] = f"Downloading {share}"
            if self.tree.exists(event.tool_id):
                self.tree.set(event.tool_id, "status", self.progress[event.tool_id])
                self.tree.item(event.tool_id, tags=("busy",))
        elif isinstance(event, InstallFinished):
            self.progress.pop(event.tool_id, None)
            self._fill_table()
        elif isinstance(event, UpdateFound):
            self.latest[event.tool_id] = event.release

    # ----- table -----

    def _status(self, tool: Tool) -> tuple[str, str]:
        if tool.id in self.progress:
            return self.progress[tool.id], "busy"
        status = self.app.toolbox.status(tool)
        if not status.installed:
            return "Not installed", "muted"
        if status.missing_requirement:
            return f"Needs {status.missing_requirement.label}", "attention"
        latest = self.latest.get(tool.id)
        if latest and status.record and latest.fingerprint and latest.fingerprint != status.record.fingerprint:
            return f"Update: {latest.version}", "attention"
        return "Installed", "ready"

    def _fill_table(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        groups = {}
        installed = 0
        for tool in self.app.catalog.tools:
            if tool.group not in groups:
                groups[tool.group] = f"group:{len(groups)}"
                self.tree.insert("", "end", iid=groups[tool.group], text=tool.group, open=True, tags=("group",))
            label, tag = self._status(tool)
            record = self.app.toolbox.status(tool).record
            installed += record is not None
            self.tree.insert(groups[tool.group], "end", iid=tool.id, text=tool.id,
                             values=(label, record.version if record else "", "Yes" if tool.recommended else ""), tags=(tag,))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        recommended = [tool for tool in self.app.catalog.tools if tool.recommended]
        ready = sum(1 for tool in recommended if self.app.toolbox.status(tool).installed)
        self.summary.configure(text=f"{installed} of {len(self.app.catalog.tools)} tools installed; "
                                    f"{ready} of {len(recommended)} recommended. Double-click a viewer to start it.")
        self._fill_banners()
        self._fill_details()

    def _fill_banners(self) -> None:
        for child in self.banners.winfo_children():
            child.destroy()
        for requirement, version in self.app.toolbox.requirement_versions():
            if version is None:
                users = sum(1 for tool in self.app.catalog.tools if tool.requires == requirement.id)
                Banner(self.banners, "warning", f"The {requirement.label} is not installed; {users} tools cannot run without it.",
                       "Download from Microsoft", lambda url=requirement.download: open_url(url)).pack(fill="x", pady=(0, self.app.theme.px(6)))

    def _selected_tool(self) -> Tool | None:
        selection = self.tree.selection()
        if not selection or selection[0].startswith("group:"):
            return None
        return self.app.catalog.tool(selection[0])

    def _fill_details(self) -> None:
        body = self.details.body
        for child in body.winfo_children():
            child.destroy()
        px = self.app.theme.px
        tool = self._selected_tool()
        if tool is None:
            text(body, "Tool details", "h3").pack(anchor="w")
            text(body, "Select a tool to see what it does, which analyses use it, and to install, update, start or remove it.",
                 "muted", wrap=FILL).pack(anchor="w", fill="x", pady=(px(6), 0))
            return
        status = self.app.toolbox.status(tool)
        text(body, tool.id, "h2").pack(anchor="w")
        text(body, tool.group, "faint").pack(anchor="w")
        label, _ = self._status(tool)
        if label == "Installed":
            look = (OK, OK_SOFT)
        elif tool.id in self.progress:
            look = (ACCENT, ACCENT_SOFT)
        elif status.installed:
            look = (WARN, WARN_SOFT)
        else:
            look = (MUTED, NEUTRAL_SOFT)
        pill(body, label, *look).pack(anchor="w", pady=(px(8), px(10)))
        text(body, tool.about, "body", wrap=FILL).pack(anchor="w", fill="x")
        link = text(body, tool.homepage, "link", wrap=310)
        link.pack(anchor="w", pady=(px(6), 0))
        link.bind("<Button-1>", lambda _: open_url(tool.homepage))

        rows = []
        if self.used_in[tool.id]:
            rows.append(("Used in", ", ".join(self.used_in[tool.id])))
        reads = sorted({"any file" if artifact_id == ANY_ARTIFACT else self.app.catalog.artifact(artifact_id).label
                        for action in tool.actions for artifact_id in action.artifacts})
        if reads:
            rows.append(("Reads", ", ".join(reads)))
        if status.record:
            rows.append(("Installed", f"{status.record.version}, {status.record.installed[:10]}"))
        if tool.requires:
            rows.append(("Needs", self.app.catalog.requirement(tool.requires).label))
        if tool.license:
            rows.append(("Licence", "Terms must be accepted before download"))
        separator(body).pack(fill="x", pady=px(12))
        for name, value in rows:
            text(body, name, "faint").pack(anchor="w")
            text(body, value, "body", wrap=FILL).pack(anchor="w", fill="x", pady=(0, px(6)))

        buttons = tk.Frame(body, bg=SURFACE)
        buttons.pack(fill="x", side="bottom")
        if status.gui and status.installed:
            ttk.Button(buttons, text="Start", style="Primary.TButton", command=lambda: self.app.launch(tool)).pack(fill="x", pady=(0, px(6)))
        install_label = "Install" if not status.installed else ("Update" if label.startswith("Update") else "Reinstall")
        ttk.Button(buttons, text=install_label, style="Secondary.TButton" if status.installed else "Primary.TButton",
                   command=lambda: self.app.install_tools([tool])).pack(fill="x", pady=(0, px(6)))
        if status.installed:
            ttk.Button(buttons, text="Remove", style="Danger.TButton", command=lambda: self._remove(tool)).pack(fill="x")

    # ----- commands -----

    def _install_recommended(self) -> None:
        wanted = [tool for tool in self.app.catalog.tools if tool.recommended and not self.app.toolbox.status(tool).installed]
        if not wanted:
            messagebox.showinfo("Install recommended", "All recommended tools are already installed.")
            return
        self.app.install_tools(wanted)

    def _install_all(self) -> None:
        wanted = [tool for tool in self.app.catalog.tools if not self.app.toolbox.status(tool).installed]
        if not wanted:
            messagebox.showinfo("Install all", "Every tool is already installed.")
            return
        if messagebox.askyesno("Install all", f"Download and install {len(wanted)} tools? The viewers are about 90 MB each."):
            self.app.install_tools(wanted)

    def _check_updates(self) -> None:
        installed = [tool for tool in self.app.catalog.tools if self.app.toolbox.status(tool).installed]
        if not installed:
            messagebox.showinfo("Check for updates", "No tools are installed yet.")
            return

        def done(failures, error):
            self.app.end_busy()
            self._fill_table()
            outdated = [tool.id for tool in installed if self._status(tool)[0].startswith("Update")]
            message = (f"Updates are available for: {', '.join(outdated)}. Select a tool and press Update."
                       if outdated else "All installed tools are up to date.")
            if failures or error:
                problems = "\n".join(f"{tool_id}: {reason}" for tool_id, reason in (failures or {}).items())
                message += f"\n\nSome lookups failed:\n{problems or error}"
            messagebox.showinfo("Check for updates", message)

        if self.app.worker.start("Checking for updates", update_work(installed), done):
            self.app.begin_busy("Checking for updates...")
        else:
            messagebox.showinfo("Check for updates", f"Wait until the current task finishes ({self.app.worker.busy_label}).")

    def _remove(self, tool: Tool) -> None:
        if not messagebox.askyesno("Remove", f"Delete {tool.id} from the tools folder? It can be installed again later."):
            return
        try:
            uninstall(tool, self.app.workspace.tools_dir)
        except InstallError as error:
            messagebox.showerror("Remove", str(error))
        self.app.broadcast("tools_changed")

    def _launch_selected(self) -> None:
        tool = self._selected_tool()
        if tool and self.app.toolbox.status(tool).gui:
            self.app.launch(tool)
