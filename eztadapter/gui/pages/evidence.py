"""Evidence: browse what was recognised, narrow the analysis, or run any tool on chosen files."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

from ...catalog import ANY_ARTIFACT
from ...evidence import EvidenceItem
from ...planner import Choice
from .. import theme
from ..theme import ACCENT, ACCENT_SOFT, SURFACE
from ..widgets import FILL, plural, Banner, Card, CheckBox, PageHeader, human_size, open_path, pill, reveal, separator, table, text
from .base import Page

_ALL_TYPES = "All types"
_UNRECOGNISED = "Not recognised"
_UNREADABLE = "Cannot be read"


class EvidencePage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        px = app.theme.px
        self.header = PageHeader(self.content, "Evidence", "")
        self.header.pack(fill="x")
        self.header.button("Open folder", lambda: open_path(app.workspace.evidence_dir))
        self.header.button("Change folder", lambda: app.change_folder("evidence"))
        self.header.button("Rescan", app.rescan, style="Primary.TButton")

        self.banner_area = tk.Frame(self.content, bg=self.content.cget("bg"))
        self.banner_area.pack(fill="x", pady=(px(14), 0))

        filters = tk.Frame(self.content, bg=self.content.cget("bg"))
        filters.pack(fill="x", pady=(px(14), px(10)))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_table())
        entry = ttk.Entry(filters, textvariable=self.search, width=36)
        entry.pack(side="left")
        text(filters, "Filter by name or location", "faint").pack(side="left", padx=(px(8), px(20)))
        self.type_filter = tk.StringVar(value=_ALL_TYPES)
        self.type_box = ttk.Combobox(filters, textvariable=self.type_filter, state="readonly", width=32)
        self.type_box.pack(side="left")
        self.type_box.bind("<<ComboboxSelected>>", lambda _: self._fill_table())
        self.summary = text(filters, "", "muted")
        self.summary.pack(side="right")

        split = tk.Frame(self.content, bg=self.content.cget("bg"))
        split.pack(fill="both", expand=True)
        self.details = Card(split, padding=18, width=px(340))
        self.details.pack(side="right", fill="y", padx=(px(16), 0))
        self.details.pack_propagate(False)
        self.tree = table(
            split,
            {"size": ("Size", 90, False), "modified": ("Modified", 140, False), "location": ("Location", 300, True)},
            tree_heading="Artifact / file",
            selectmode="extended",
        )
        self.tree.holder.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._selection_changed())
        self.tree.bind("<Double-1>", lambda _: self._open_selected())

        self.action_bar = tk.Frame(self.content, bg=SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        self.action_bar.pack(fill="x", pady=(px(12), 0))
        inner = tk.Frame(self.action_bar, bg=SURFACE)
        inner.pack(fill="x", padx=px(16), pady=px(10))
        self.selection_text = text(inner, "", "body")
        self.selection_text.pack(side="left")
        self.analyse_button = ttk.Button(inner, text="Analyse these files", style="Primary.TButton", command=self._analyse_selection)
        self.analyse_button.pack(side="right")
        self.tool_button = ttk.Button(inner, text="Run a tool...", style="Secondary.TButton", command=self._run_tool)
        self.tool_button.pack(side="right", padx=(0, px(8)))
        self.clear_button = ttk.Button(inner, text="Clear selection", style="Ghost.TButton", command=self._clear_selection)
        self.clear_button.pack(side="right", padx=(0, px(8)))
        self.by_iid: dict[str, EvidenceItem] = {}

    # ----- hooks -----

    def shown(self) -> None:
        self.header.subtitle.configure(text=str(self.app.workspace.evidence_dir))

    def evidence_changed(self) -> None:
        types = sorted({item.artifact.label for item in self.app.items if item.artifact})
        extra = ([_UNRECOGNISED] if any(not item.artifact and not item.error for item in self.app.items) else [])
        extra += [_UNREADABLE] if any(item.error for item in self.app.items) else []
        self.type_box.configure(values=[_ALL_TYPES] + types + extra)
        if self.type_filter.get() not in self.type_box.cget("values"):
            self.type_filter.set(_ALL_TYPES)
        self._fill_table()
        self._show_scope()

    def folders_changed(self) -> None:
        self.shown()

    def tools_changed(self) -> None:
        self._selection_changed()

    # ----- table -----

    def _visible_items(self) -> list[EvidenceItem]:
        needle = self.search.get().strip().casefold()
        wanted = self.type_filter.get()
        result = []
        for item in self.app.items:
            label = _UNREADABLE if item.error else (item.artifact.label if item.artifact else _UNRECOGNISED)
            if wanted != _ALL_TYPES and label != wanted:
                continue
            if needle and needle not in item.rel.casefold():
                continue
            result.append(item)
        return result

    def _fill_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.by_iid = {}
        items = self._visible_items()
        all_items = self.app.items
        recognised = sum(1 for item in all_items if item.artifact)
        self.summary.configure(text=f"{len(all_items)} files, {human_size(sum(i.size for i in all_items))}, {recognised} recognised")
        if not all_items:
            folder = self.app.workspace.evidence_dir
            message = (
                f"The evidence folder is empty. Copy collected files into {folder}; the list refreshes when you come back."
                if folder.is_dir() else f"The evidence folder {folder} does not exist. Choose another with Change folder."
            )
            self.tree.insert("", "end", iid="hint", text=message, tags=("muted",))
        groups: dict[str, list[EvidenceItem]] = {}
        for item in items:
            key = "_unreadable" if item.error else (item.artifact.id if item.artifact else "_unrecognised")
            groups.setdefault(key, []).append(item)
        order = [artifact.id for artifact in self.app.catalog.artifacts] + ["_unrecognised", "_unreadable"]
        for key in order:
            members = groups.get(key)
            if not members:
                continue
            label = {"_unrecognised": _UNRECOGNISED, "_unreadable": _UNREADABLE}.get(key) or members[0].artifact.label
            group_iid = f"group:{key}"
            self.tree.insert("", "end", iid=group_iid, text=f"{label}   {len(members)}", open=len(members) <= 12,
                             values=(human_size(sum(i.size for i in members)), "", ""), tags=("group",))
            for item in members:
                iid = f"file:{len(self.by_iid)}"
                self.by_iid[iid] = item
                note = f"   [{item.error}]" if item.error else ("   [dirty hive]" if item.dirty_hive else "")
                modified = datetime.fromtimestamp(item.mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M")
                self.tree.insert(group_iid, "end", iid=iid, text=item.name + note,
                                 values=(human_size(item.size), modified, item.folder or "."),
                                 tags=("muted",) if key.startswith("_") else ())
        self._selection_changed()

    def selected_items(self) -> list[EvidenceItem]:
        chosen = {}
        for iid in self.tree.selection():
            rows = self.tree.get_children(iid) if iid.startswith("group:") else (iid,)
            for row in rows:
                if row in self.by_iid:
                    chosen[row] = self.by_iid[row]
        return list(chosen.values())

    # ----- selection -----

    def _selection_changed(self) -> None:
        items = self.selected_items()
        usable = [item for item in items if item.error is None]
        state = "normal" if usable else "disabled"
        for button in (self.analyse_button, self.tool_button):
            button.configure(state=state)
        self.clear_button.configure(state="normal" if items else "disabled")
        if items:
            self.selection_text.configure(text=f"{plural(len(items), 'file')} selected, {human_size(sum(i.size for i in items))}")
        else:
            self.selection_text.configure(text="Select files or whole groups to analyse only those, or to run a tool of your choice on them.")
        self._fill_details(items)

    def _fill_details(self, items: list[EvidenceItem]) -> None:
        body = self.details.body
        for child in body.winfo_children():
            child.destroy()
        px = self.app.theme.px
        selection = self.tree.selection()
        if not items:
            text(body, "Details", "h3").pack(anchor="w")
            text(body, "Select a file to see what it is and which tools read it.", "muted", wrap=FILL).pack(anchor="w", fill="x", pady=(px(6), 0))
            return
        if len(items) == 1:
            item = items[0]
            text(body, item.name, "h3", wrap=FILL).pack(anchor="w", fill="x")
            label = item.artifact.label if item.artifact else ("Cannot be read" if item.error else "Not recognised")
            pill(body, label, ACCENT if item.artifact else theme.MUTED, ACCENT_SOFT if item.artifact else theme.NEUTRAL_SOFT).pack(anchor="w", pady=(px(6), px(10)))
            if item.artifact:
                text(body, item.artifact.about, "muted", wrap=FILL).pack(anchor="w", fill="x")
            rows = [("Location", item.folder or "."), ("Size", f"{human_size(item.size)} ({item.size:,} bytes)"),
                    ("Modified", datetime.fromtimestamp(item.mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S"))]
            if item.dirty_hive:
                rows.append(("Registry", "Dirty hive: its .LOG1/.LOG2 files hold newer changes."))
            if item.error:
                rows.append(("Error", item.error))
            separator(body).pack(fill="x", pady=px(12))
            for name, value in rows:
                text(body, name, "faint").pack(anchor="w")
                text(body, value, "body", wrap=FILL).pack(anchor="w", fill="x", pady=(0, px(6)))
            self._readers(body, [item])
            buttons = tk.Frame(body, bg=SURFACE)
            buttons.pack(fill="x", side="bottom")
            viewer = self.app.toolbox.viewer_for(item.path, item.artifact.id if item.artifact else None)
            if viewer:
                ttk.Button(buttons, text=f"Open copy in {viewer.tool.id}", style="Primary.TButton",
                           command=lambda: self.app.open_evidence(item)).pack(fill="x", pady=(0, px(6)))
            ttk.Button(buttons, text="Show in folder", style="Secondary.TButton", command=lambda: reveal(item.path)).pack(fill="x")
            return
        groups = [iid for iid in selection if iid.startswith("group:")]
        title = self.tree.item(groups[0], "text").rsplit("   ", 1)[0] if len(groups) == 1 and len(selection) == 1 else f"{len(items)} files"
        text(body, title, "h3", wrap=FILL).pack(anchor="w", fill="x")
        kinds = {item.artifact.id for item in items if item.artifact}
        if len(kinds) == 1:
            text(body, self.app.catalog.artifact(next(iter(kinds))).about, "muted", wrap=FILL).pack(anchor="w", fill="x", pady=(px(6), 0))
        text(body, f"{len(items)} files, {human_size(sum(i.size for i in items))}", "body").pack(anchor="w", pady=(px(10), 0))
        self._readers(body, items)

    def _readers(self, body: tk.Frame, items: list[EvidenceItem]) -> None:
        """Which tools read these files, from the catalog."""
        px = self.app.theme.px
        kinds = {item.artifact.id for item in items if item.artifact}
        tools = sorted({action.tool_id for action in self.app.catalog.actions if kinds & set(action.artifacts)})
        if not tools:
            return
        separator(body).pack(fill="x", pady=px(12))
        text(body, "Read by", "faint").pack(anchor="w")
        text(body, ", ".join(tools), "body", wrap=FILL).pack(anchor="w", fill="x")

    def _open_selected(self) -> None:
        items = self.selected_items()
        if len(items) == 1 and not self.tree.selection()[0].startswith("group:"):
            self.app.open_evidence(items[0])

    def _clear_selection(self) -> None:
        self.tree.selection_remove(*self.tree.selection())

    # ----- scope and manual runs -----

    def _show_scope(self) -> None:
        for child in self.banner_area.winfo_children():
            child.destroy()
        if self.app.scope is not None:
            Banner(self.banner_area, "info", f"Analyses run on {plural(len(self.app.scope), 'selected file')}, not the whole folder.",
                   "Use all evidence", lambda: self.app.set_scope(None)).pack(fill="x")

    def _analyse_selection(self) -> None:
        items = [item for item in self.selected_items() if item.error is None]
        if items:
            self.app.set_scope(items)
            self.app.navigate("analyze")

    def _run_tool(self) -> None:
        items = [item for item in self.selected_items() if item.error is None]
        if items:
            ToolPicker(self.app, items)


class ToolPicker(tk.Toplevel):
    """Choose any tools to run on chosen files, including files that are not their usual input."""

    def __init__(self, app, items: list[EvidenceItem]):
        super().__init__(app, bg=theme.BG)
        self.app = app
        self.items = items
        px = app.theme.px
        self.title("Run a tool")
        self.geometry(f"{px(900)}x{px(640)}")
        self.minsize(px(760), px(520))
        self.transient(app)

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=px(22), pady=px(18))
        text(body, f"Run a tool on {plural(len(items), 'file')}", "h2").pack(anchor="w")
        text(body, "Pick one or more tools. Files that are not a tool's usual input can be given to it anyway; "
                   "if it cannot read them, its task reports the error.", "muted", wrap=820).pack(anchor="w", pady=(px(4), px(12)))

        self.tree = table(body, {"usual": ("Usual input", 300, True), "match": ("Matching", 90, False)},
                          tree_heading="Tool and task", selectmode="extended")
        self.tree.holder.pack(fill="both", expand=True)
        self.actions = {}
        groups = {}
        for tool in app.catalog.tools:
            for action in tool.actions:
                if tool.group not in groups:
                    groups[tool.group] = f"g{len(groups)}"
                    self.tree.insert("", "end", iid=groups[tool.group], text=tool.group, open=True, tags=("group",))
                matching = sum(1 for item in items if action.applies_to(item.artifact.id if item.artifact else None))
                usual = "Any file" if ANY_ARTIFACT in action.artifacts else ", ".join(
                    app.catalog.artifact(artifact_id).label for artifact_id in action.artifacts)
                iid = f"a{len(self.actions)}"
                self.actions[iid] = action
                self.tree.insert(groups[tool.group], "end", iid=iid, text=f"{tool.id}: {action.label}",
                                 values=(usual, f"{matching} of {len(items)}"), tags=() if matching else ("muted",))
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._update())

        footer = tk.Frame(body, bg=theme.BG)
        footer.pack(fill="x", pady=(px(12), 0))
        self.force = CheckBox(footer, selected=False, command=lambda _: self._update())
        self.force.pack(side="left")
        self.force_text = text(footer, "", "body")
        self.force_text.pack(side="left", padx=(px(8), 0))
        self.note = text(body, "", "small", wrap=820)
        self.note.pack(anchor="w", pady=(px(8), 0))
        buttons = tk.Frame(body, bg=theme.BG)
        buttons.pack(fill="x", pady=(px(12), 0))
        self.run_button = ttk.Button(buttons, text="Run", style="Primary.TButton", command=self._run)
        self.run_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=self.destroy).pack(side="right", padx=(0, px(8)))
        self._update()
        self.grab_set()

    def _chosen(self):
        return [self.actions[iid] for iid in self.tree.selection() if iid in self.actions]

    def _update(self) -> None:
        actions = self._chosen()
        self.run_button.configure(state="normal" if actions else "disabled")
        self.force_text.configure(text="Also give each tool the selected files that are not its usual input")
        if not actions:
            self.note.configure(text="Select a tool on the list.", fg=theme.MUTED)
            return
        notes = []
        for action in actions:
            matching = sum(1 for item in self.items if action.applies_to(item.artifact.id if item.artifact else None))
            if matching == 0:
                notes.append(f"{action.tool_id}: none of the files are its usual input, so it gets all of them; expect errors if the format does not fit.")
            elif matching < len(self.items) and not self.force.selected:
                notes.append(f"{action.tool_id}: runs on {matching} of {len(self.items)} files.")
        self.note.configure(text="\n".join(notes) or "Every selected file is a usual input of the chosen tools.",
                            fg=theme.WARN if notes else theme.MUTED)

    def _run(self) -> None:
        choices = []
        for action in self._chosen():
            matching = sum(1 for item in self.items if action.applies_to(item.artifact.id if item.artifact else None))
            choices.append(Choice(action, force=self.force.selected or matching == 0))
        self.destroy()
        self.app.start_run(choices, [], self.items)
