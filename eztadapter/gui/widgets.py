"""Building blocks shared by the pages: text, cards, pills, scroll areas, dialogs.

Containers are plain tk widgets so each can take its own background colour;
interactive controls (buttons, tables, entries) are ttk widgets styled in
theme.py. Every helper reads fonts and spacing from theme.get().
"""

from __future__ import annotations

import os
import subprocess
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from . import theme
from .theme import ACCENT, BORDER, MUTED, SURFACE, TEXT

_TEXT_KINDS = {
    "body": ("body", TEXT),
    "muted": ("body", MUTED),
    "small": ("small", MUTED),
    "faint": ("small", theme.FAINT),
    "strong": ("strong", TEXT),
    "h3": ("h3", TEXT),
    "h2": ("h2", TEXT),
    "title": ("title", TEXT),
    "stat": ("stat", TEXT),
    "link": ("body", ACCENT),
}


# Pass as `wrap` to make a label wrap at whatever width it is given; pack it with fill="x".
FILL = -1


def text(parent: tk.Misc, value: str = "", kind: str = "body", wrap: int = 0, **options) -> tk.Label:
    """A label in one of the text styles, on its parent's background.

    `wrap` is a line width in 96-DPI pixels, or FILL to wrap at the label's own width.
    """
    font_name, colour = _TEXT_KINDS[kind]
    label = tk.Label(
        parent, text=value, font=getattr(theme.get().fonts, font_name), fg=options.pop("fg", colour),
        bg=options.pop("bg", parent.cget("bg")), anchor=options.pop("anchor", "w"), justify=options.pop("justify", "left"),
        wraplength=theme.get().px(wrap) if wrap > 0 else 0, **options,
    )
    if wrap == FILL:
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(event.width - 4, 40)))
    if kind == "link":
        label.configure(cursor="hand2")
    return label


def icon(parent: tk.Misc, name: str, size: str = "icon", fg: str = MUTED, **options) -> tk.Label:
    fonts = theme.get().fonts
    return tk.Label(parent, text=fonts.glyph(name), font=getattr(fonts, size), fg=fg, bg=options.pop("bg", parent.cget("bg")), **options)


def pill(parent: tk.Misc, value: str, fg: str = MUTED, bg: str = theme.NEUTRAL_SOFT) -> tk.Label:
    px = theme.get().px
    return tk.Label(parent, text=value, font=theme.get().fonts.small, fg=fg, bg=bg, padx=px(8), pady=px(1))


def status_pill(parent: tk.Misc, status: str) -> tk.Label:
    label, fg, bg = theme.STATUS_LOOK[status]
    return pill(parent, label, fg, bg)


def separator(parent: tk.Misc, colour: str = BORDER) -> tk.Frame:
    return tk.Frame(parent, bg=colour, height=1)


class Card(tk.Frame):
    """A white panel with a hairline border; put content in `body`."""

    def __init__(self, parent: tk.Misc, padding: int = 18, **options):
        super().__init__(parent, bg=SURFACE, highlightbackground=BORDER, highlightcolor=BORDER, highlightthickness=1, **options)
        pad = theme.get().px(padding)
        self.body = tk.Frame(self, bg=SURFACE)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)


class PageHeader(tk.Frame):
    """Title and subtitle of a page, with room for buttons on the right (`actions`)."""

    def __init__(self, parent: tk.Misc, title: str, subtitle: str = ""):
        super().__init__(parent, bg=parent.cget("bg"))
        # The buttons are packed first so a long subtitle wraps instead of pushing them out of view.
        self.actions = tk.Frame(self, bg=self.cget("bg"))
        self.actions.pack(side="right", anchor="s")
        left = tk.Frame(self, bg=self.cget("bg"))
        left.pack(side="left", fill="x", expand=True, padx=(0, theme.get().px(16)))
        self.title = text(left, title, "title")
        self.title.pack(anchor="w")
        self.subtitle = text(left, subtitle, "muted", wrap=FILL)
        self.subtitle.pack(anchor="w", fill="x", pady=(theme.get().px(2), 0))

    def button(self, label: str, command, style: str = "Secondary.TButton") -> ttk.Button:
        button = ttk.Button(self.actions, text=label, command=command, style=style)
        button.pack(side="left", padx=(theme.get().px(8), 0))
        return button


class Banner(tk.Frame):
    """A coloured notice across a page, such as a missing runtime."""

    LOOK = {
        "info": (ACCENT, theme.ACCENT_SOFT, "info"),
        "warning": (theme.WARN, theme.WARN_SOFT, "warning"),
        "error": (theme.DANGER, theme.DANGER_SOFT, "error"),
        "ok": (theme.OK, theme.OK_SOFT, "check"),
    }

    def __init__(self, parent: tk.Misc, kind: str, message: str, action: str | None = None, command=None):
        fg, bg, glyph = self.LOOK[kind]
        super().__init__(parent, bg=bg)
        px = theme.get().px
        icon(self, glyph, fg=fg, bg=bg).pack(side="left", padx=(px(12), px(8)), pady=px(10))
        text(self, message, "body", wrap=700, fg=TEXT, bg=bg).pack(side="left", fill="x", expand=True, pady=px(10))
        if action:
            link = text(self, action, "link", bg=bg)
            link.configure(font=theme.get().fonts.strong)
            link.pack(side="right", padx=px(14))
            link.bind("<Button-1>", lambda _: command())


class ScrollArea(tk.Frame):
    """A vertically scrolling region; put content in `body`."""

    def __init__(self, parent: tk.Misc, bg: str | None = None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body.bind("<Configure>", lambda _: self._content_changed())
        self.canvas.bind("<Configure>", self._resized)
        self.bind("<Enter>", lambda _: self.bind_all("<MouseWheel>", self._on_wheel))
        self.bind("<Leave>", lambda _: self.unbind_all("<MouseWheel>"))

    def _resized(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._content_changed()

    def _content_changed(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        # The scrollbar only appears when there is something to scroll.
        if self.body.winfo_reqheight() > self.canvas.winfo_height() > 1:
            if not self.scrollbar.winfo_ismapped():
                self.scrollbar.pack(side="right", fill="y", before=self.canvas)
        elif self.scrollbar.winfo_ismapped():
            self.scrollbar.pack_forget()
            self.canvas.yview_moveto(0)

    def _on_wheel(self, event) -> None:
        if self.body.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

    def clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)


class CheckBox(tk.Canvas):
    """A square tick box drawn to match the theme; `selected` holds its state."""

    def __init__(self, parent: tk.Misc, selected: bool = False, command=None, size: int = 18):
        px = theme.get().px
        self.size = px(size)
        super().__init__(parent, width=self.size, height=self.size, bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self.selected = selected
        self.command = command
        self.bind("<Button-1>", lambda _: self.toggle())
        self.draw()

    def toggle(self) -> None:
        self.set(not self.selected)
        if self.command:
            self.command(self.selected)

    def set(self, selected: bool) -> None:
        self.selected = selected
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        s = self.size
        if self.selected:
            self.create_rectangle(1, 1, s - 1, s - 1, fill=ACCENT, outline=ACCENT)
            self.create_line(s * 0.25, s * 0.52, s * 0.43, s * 0.70, s * 0.76, s * 0.32, fill="#ffffff", width=max(2, s // 9))
        else:
            self.create_rectangle(1, 1, s - 1, s - 1, fill=SURFACE, outline=theme.BORDER_STRONG, width=1.5)


def empty_state(parent: tk.Misc, glyph: str, title: str, message: str, action: str | None = None, command=None) -> tk.Frame:
    frame = tk.Frame(parent, bg=parent.cget("bg"))
    px = theme.get().px
    icon(frame, glyph, size="icon_large", fg=theme.FAINT).pack(pady=(px(30), px(8)))
    text(frame, title, "h3").pack()
    text(frame, message, "muted", wrap=420, justify="center").pack(pady=(px(4), px(12)))
    if action:
        ttk.Button(frame, text=action, style="Primary.TButton", command=command).pack()
    return frame


def table(parent: tk.Misc, columns: dict[str, tuple[str, int, bool]], tree_heading: str | None = None, **options) -> ttk.Treeview:
    """A styled Treeview inside `parent` with a vertical scrollbar.

    `columns` maps column id to (heading, width, stretch). With `tree_heading`
    the first column is the tree column showing nested rows.
    """
    px = theme.get().px
    holder = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
    tree = ttk.Treeview(holder, columns=list(columns), show="tree headings" if tree_heading else "headings", **options)
    if tree_heading:
        tree.heading("#0", text=tree_heading, anchor="w")
        tree.column("#0", width=px(280), stretch=True)
    for column, (heading, width, stretch) in columns.items():
        tree.heading(column, text=heading, anchor="w")
        tree.column(column, width=px(width), stretch=stretch, anchor="w")
    scrollbar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    tree.holder = holder
    tree.tag_configure("group", font=theme.get().fonts.strong)
    tree.tag_configure("muted", foreground=MUTED)
    for status, (_, fg, _) in theme.STATUS_LOOK.items():
        tree.tag_configure(f"status-{status}", foreground=fg)
    return tree


class LicenceDialog(tk.Toplevel):
    """Asks once whether the user accepts a tool licence before it is downloaded."""

    def __init__(self, parent: tk.Misc, url: str, tool_names: list[str]):
        super().__init__(parent, bg=SURFACE)
        self.accepted = False
        self.title("Licence terms")
        self.resizable(False, False)
        self.transient(parent)
        px = theme.get().px
        body = tk.Frame(self, bg=SURFACE)
        body.pack(fill="both", expand=True, padx=px(22), pady=px(20))
        text(body, "Licence terms", "h2").pack(anchor="w")
        names = ", ".join(tool_names)
        message = (
            f"{names} {'is' if len(tool_names) == 1 else 'are'} distributed under licence terms that must be accepted "
            f"before use. Once you accept here, the adapter passes the tool's -accepteula switch on your behalf."
        )
        text(body, message, "body", wrap=440).pack(anchor="w", pady=(px(8), px(8)))
        link = text(body, url, "link", wrap=440)
        link.pack(anchor="w", pady=(0, px(16)))
        link.bind("<Button-1>", lambda _: open_url(url))
        buttons = tk.Frame(body, bg=SURFACE)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Decline", style="Secondary.TButton", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Accept", style="Primary.TButton", command=self._accept).pack(side="right", padx=(0, px(8)))
        self.grab_set()
        self.wait_window()

    def _accept(self) -> None:
        self.accepted = True
        self.destroy()


def plural(count: int, word: str, many: str | None = None) -> str:
    """'1 file', '3 files'; `many` for irregular plurals such as 'analyses'."""
    return f"{count:,} {word if count == 1 else (many or word + 's')}"


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def run_time(run_name: str) -> str:
    """'2026-10-14_153012' as '2026-10-14 15:30:12', or the name itself when it is not a run stamp."""
    try:
        return datetime.strptime(run_name[:17], "%Y-%m-%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return run_name


def open_path(path: Path) -> None:
    """Open a file with its default application, or a folder in Explorer."""
    if not path.exists():
        messagebox.showerror("Not found", f"{path} does not exist.")
        return
    os.startfile(str(path))


def reveal(path: Path) -> None:
    """Open Explorer with the file selected."""
    # Explorer parses its own command line and wants the path glued to "/select,".
    subprocess.Popen(f'explorer /select,"{path}"')


def open_url(url: str) -> None:
    webbrowser.open(url)
