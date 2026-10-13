"""Preview: a quick look at a result file without leaving the window.

CSV files show as a sortable, filterable table and text files as searchable
text. Only the beginning of a large file is loaded; Timeline Explorer or the
default application opens the whole file.
"""

from __future__ import annotations

import csv
import io
import locale
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ...fsutil import long_path
from .. import theme
from ..theme import BORDER, SURFACE
from ..widgets import PageHeader, human_size, reveal, text
from .base import Page

TABLE_EXTENSIONS = {".csv", ".tsv"}
TEXT_EXTENSIONS = {".txt", ".log", ".json", ".jsonl", ".xml", ".md"}
PREVIEWABLE = TABLE_EXTENSIONS | TEXT_EXTENSIONS

_MAX_ROWS = 20_000
_MAX_TEXT_BYTES = 5_000_000


class PreviewPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        px = app.theme.px
        self.path: Path | None = None
        self.rows: list[list[str]] = []
        self.columns: list[str] = []
        self.sort_column: int | None = None
        self.sort_descending = False
        self._filter_job = None

        self.header = PageHeader(self.content, "Preview", "")
        self.header.pack(fill="x")
        self.header.button("Back to results", lambda: app.navigate("results"))
        self.header.button("Show in folder", lambda: self.path and reveal(self.path))
        self.open_button = self.header.button("Open", lambda: self.path and app.open_output(self.path), style="Primary.TButton")

        self.toolbar = tk.Frame(self.content, bg=self.content.cget("bg"))
        self.toolbar.pack(fill="x", pady=(px(16), px(10)))
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self._schedule_filter())
        self.entry = ttk.Entry(self.toolbar, textvariable=self.query, width=40)
        self.entry.pack(side="left")
        self.entry.bind("<Return>", lambda _: self._find_next())
        self.hint = text(self.toolbar, "", "faint")
        self.hint.pack(side="left", padx=(px(8), 0))
        self.info = text(self.toolbar, "", "muted")
        self.info.pack(side="right")

        self.area = tk.Frame(self.content, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        self.area.pack(fill="both", expand=True)
        self.table = ttk.Treeview(self.area, show="headings", selectmode="extended")
        self.table_y = ttk.Scrollbar(self.area, orient="vertical", command=self.table.yview)
        self.table_x = ttk.Scrollbar(self.area, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=self.table_y.set, xscrollcommand=self.table_x.set)
        self.text = ScrolledText(self.area, wrap="none", font=app.theme.fonts.mono, relief="flat", borderwidth=0,
                                 background=SURFACE, foreground=theme.TEXT, state="disabled")
        self.text.tag_configure("match", background="#ffe58f")
        self.text.tag_configure("current", background="#ffc53d")

    def load(self, path: Path) -> None:
        self.path = path
        self.header.subtitle.configure(text=str(path.parent))
        self.header.title.configure(text=path.name)
        viewer = self.app.toolbox.viewer_for(path)
        self.open_button.configure(text=f"Open in {viewer.tool.id}" if viewer else "Open")
        self.query.set("")
        for widget in (self.table, self.table_y, self.table_x, self.text):
            widget.pack_forget()
        size = os.path.getsize(long_path(path)) if os.path.exists(long_path(path)) else 0
        if path.suffix.lower() in TABLE_EXTENSIONS:
            self._load_table(path, size)
        else:
            self._load_text(path, size)

    # ----- tables -----

    def _load_table(self, path: Path, size: int) -> None:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        reader = csv.reader(io.StringIO(_read_text(path, limit=None if size < 50_000_000 else 50_000_000)), delimiter=delimiter)
        self.columns = next(reader, [])
        self.rows = []
        for row in reader:
            if len(self.rows) >= _MAX_ROWS:
                break
            self.rows.append(row)
        complete = len(self.rows) < _MAX_ROWS
        self.sort_column, self.sort_descending = None, False
        self.hint.configure(text="Filter rows")
        note = f"{len(self.rows):,} rows" if complete else f"first {_MAX_ROWS:,} rows; open the file for all of it"
        self.info.configure(text=f"{len(self.columns)} columns, {note}, {human_size(size)}")
        self.table.configure(columns=[str(index) for index in range(len(self.columns))])
        sample = self.rows[:200]
        for index, name in enumerate(self.columns):
            longest = max([len(name)] + [len(row[index]) for row in sample if index < len(row)])
            self.table.heading(str(index), text=name, anchor="w", command=lambda index=index: self._sort(index))
            self.table.column(str(index), width=self.app.theme.px(min(max(longest * 7 + 16, 70), 420)), stretch=False, anchor="w")
        self.table_y.pack(side="right", fill="y")
        self.table_x.pack(side="bottom", fill="x")
        self.table.pack(side="left", fill="both", expand=True)
        self._fill_rows()

    def _fill_rows(self) -> None:
        self.table.delete(*self.table.get_children())
        needle = self.query.get().strip().casefold()
        rows = self.rows
        if needle:
            rows = [row for row in rows if any(needle in cell.casefold() for cell in row)]
        if self.sort_column is not None:
            rows = sorted(rows, key=lambda row: row[self.sort_column] if self.sort_column < len(row) else "", reverse=self.sort_descending)
        for row in rows:
            self.table.insert("", "end", values=row)
        if needle:
            self.hint.configure(text=f"{len(rows):,} matching rows")
        else:
            self.hint.configure(text="Filter rows; click a column heading to sort")

    def _sort(self, index: int) -> None:
        self.sort_descending = self.sort_column == index and not self.sort_descending
        self.sort_column = index
        self._fill_rows()

    # ----- text -----

    def _load_text(self, path: Path, size: int) -> None:
        content = _read_text(path, limit=_MAX_TEXT_BYTES)
        self.hint.configure(text="Find text, Enter for the next match")
        shown = "" if size <= _MAX_TEXT_BYTES else f"first {human_size(_MAX_TEXT_BYTES)} shown, "
        self.info.configure(text=f"{shown}{human_size(size)}")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", content)
        self.text.configure(state="disabled")
        self.text.pack(fill="both", expand=True)

    def _highlight(self) -> None:
        self.text.tag_remove("match", "1.0", "end")
        self.text.tag_remove("current", "1.0", "end")
        needle = self.query.get()
        if not needle:
            return
        start = "1.0"
        count = 0
        while count < 5000:
            start = self.text.search(needle, start, stopindex="end", nocase=True)
            if not start:
                break
            end = f"{start}+{len(needle)}c"
            self.text.tag_add("match", start, end)
            start = end
            count += 1
        self.hint.configure(text=f"{count:,} matches" + (" (first 5,000)" if count == 5000 else ""))
        self._find_next(from_start=True)

    def _find_next(self, from_start: bool = False) -> None:
        if self.path is None or self.path.suffix.lower() in TABLE_EXTENSIONS:
            return
        needle = self.query.get()
        if not needle:
            return
        current = self.text.tag_ranges("current")
        start = "1.0" if from_start or not current else current[1]
        found = self.text.search(needle, start, stopindex="end", nocase=True) or self.text.search(needle, "1.0", stopindex="end", nocase=True)
        self.text.tag_remove("current", "1.0", "end")
        if found:
            self.text.tag_add("current", found, f"{found}+{len(needle)}c")
            self.text.see(found)

    def _schedule_filter(self) -> None:
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(300, self._apply_query)

    def _apply_query(self) -> None:
        self._filter_job = None
        if self.path is None:
            return
        if self.path.suffix.lower() in TABLE_EXTENSIONS:
            self._fill_rows()
        else:
            self._highlight()


def _read_text(path: Path, limit: int | None) -> str:
    """Decode a tool's output: UTF-8 (with or without BOM) as most tools write, else the ANSI code page."""
    with open(long_path(path), "rb") as handle:
        data = handle.read() if limit is None else handle.read(limit)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        # A read cut short can split the last UTF-8 character; that is not a different encoding.
        if limit is not None and len(data) == limit and error.start >= len(data) - 4:
            return data[: error.start].decode("utf-8-sig")
        return data.decode(locale.getpreferredencoding(False), errors="replace")
