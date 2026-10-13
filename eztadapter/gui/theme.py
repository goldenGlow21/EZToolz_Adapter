"""Colours, fonts, icons and ttk styles shared by every page.

The look is a light workspace with a dark navigation sidebar. ttk's 'clam'
theme is the base because, unlike the native Windows theme, it lets buttons,
tables and progress bars take custom colours.

Icons are glyphs of the Windows icon font (Segoe Fluent Icons on Windows 11,
Segoe MDL2 Assets on Windows 10), so they scale with the text and need no
image files. Without either font the icons are left out.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

BG = "#f3f5f9"
SURFACE = "#ffffff"
SURFACE_ALT = "#f7f8fb"
BORDER = "#e3e7ef"
BORDER_STRONG = "#cfd6e3"
TEXT = "#1b2130"
MUTED = "#667085"
FAINT = "#98a2b3"
SIDEBAR = "#121826"
SIDEBAR_HOVER = "#1b2335"
SIDEBAR_ACTIVE = "#232e47"
SIDEBAR_TEXT = "#a9b2c4"
ACCENT = "#3a6df0"
ACCENT_HOVER = "#2f5bd3"
ACCENT_SOFT = "#eaf0fe"
OK = "#15803d"
OK_SOFT = "#e5f5ea"
WARN = "#b45309"
WARN_SOFT = "#fdf1dc"
DANGER = "#c62828"
DANGER_SOFT = "#fdeaea"
NEUTRAL_SOFT = "#eef1f6"

# Glyph code points in the Windows icon fonts.
ICONS = {
    "home": "\ue80f",
    "evidence": "\ue8b7",
    "folder": "\ue838",
    "analyze": "\ue9d9",
    "results": "\ue9f9",
    "tools": "\uec7a",
    "settings": "\ue713",
    "play": "\ue768",
    "person": "\ue77b",
    "drive": "\ueda2",
    "delete": "\ue74d",
    "chart": "\ue9d2",
    "globe": "\ue774",
    "shield": "\uea18",
    "list": "\ue8fd",
    "bug": "\uebe8",
    "chip": "\ueea1",
    "registry": "\ue8f1",
    "image": "\ue8b9",
    "text": "\ue8d2",
    "document": "\ue8a5",
    "search": "\ue721",
    "refresh": "\ue72c",
    "download": "\ue896",
    "check": "\ue73e",
    "close": "\ue711",
    "chevron": "\ue76c",
    "open": "\ue8a7",
    "view": "\ue890",
    "info": "\ue946",
    "warning": "\ue7ba",
    "error": "\ue783",
    "history": "\ue81c",
    "filter": "\ue71c",
    "wrench": "\ue90f",
}

# Status of a job, as shown in pills: (label, foreground, background).
STATUS_LOOK = {
    "ok": ("OK", OK, OK_SOFT),
    "warning": ("Warnings", WARN, WARN_SOFT),
    "empty": ("No output", WARN, WARN_SOFT),
    "failed": ("Failed", DANGER, DANGER_SOFT),
    "skipped": ("Skipped", MUTED, NEUTRAL_SOFT),
    "cancelled": ("Cancelled", MUTED, NEUTRAL_SOFT),
    "running": ("Running", ACCENT, ACCENT_SOFT),
    "queued": ("Queued", MUTED, NEUTRAL_SOFT),
}


class Fonts:
    """Named fonts, created once the Tk root exists."""

    def __init__(self, root: tk.Misc):
        families = set(tkfont.families(root))
        icon_family = next((name for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if name in families), None)
        mono_family = "Cascadia Mono" if "Cascadia Mono" in families else "Consolas"
        self.has_icons = icon_family is not None
        self.body = tkfont.Font(root, family="Segoe UI", size=10)
        self.small = tkfont.Font(root, family="Segoe UI", size=9)
        self.strong = tkfont.Font(root, family="Segoe UI Semibold", size=10)
        self.h3 = tkfont.Font(root, family="Segoe UI Semibold", size=11)
        self.h2 = tkfont.Font(root, family="Segoe UI Semibold", size=13)
        self.title = tkfont.Font(root, family="Segoe UI Semibold", size=19)
        self.stat = tkfont.Font(root, family="Segoe UI Semibold", size=22)
        self.mono = tkfont.Font(root, family=mono_family, size=9)
        self.icon = tkfont.Font(root, family=icon_family or "Segoe UI", size=13)
        self.icon_large = tkfont.Font(root, family=icon_family or "Segoe UI", size=18)
        self.icon_small = tkfont.Font(root, family=icon_family or "Segoe UI", size=10)

    def glyph(self, name: str) -> str:
        return ICONS[name] if self.has_icons else ""


class Theme:
    def __init__(self, root: tk.Tk):
        self.fonts = Fonts(root)
        # Paddings are written for a 96 DPI screen and scaled to the real one.
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self._style(root)

    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    def _style(self, root: tk.Tk) -> None:
        fonts = self.fonts
        root.configure(background=BG)
        root.option_add("*Font", fonts.body)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=fonts.body, bordercolor=BORDER, focuscolor=ACCENT)

        def button(name, background, foreground, border, hover, pressed, disabled_bg, disabled_fg):
            # Buttons whose border differs from their fill draw it, so they stay visible on white cards.
            style.configure(
                name, background=background, foreground=foreground, bordercolor=border, lightcolor=background,
                darkcolor=background, focuscolor=background, padding=(self.px(14), self.px(7)), font=fonts.strong,
                relief="flat" if border == background else "solid", borderwidth=1,
            )
            style.map(
                name,
                background=[("disabled", disabled_bg), ("pressed", pressed), ("active", hover)],
                lightcolor=[("disabled", disabled_bg), ("pressed", pressed), ("active", hover)],
                darkcolor=[("disabled", disabled_bg), ("pressed", pressed), ("active", hover)],
                foreground=[("disabled", disabled_fg)],
                bordercolor=[("disabled", disabled_bg if border == background else BORDER)],
            )

        button("Primary.TButton", ACCENT, "#ffffff", ACCENT, ACCENT_HOVER, "#284fbd", "#b8c8f6", "#ffffff")
        button("Secondary.TButton", SURFACE, TEXT, BORDER_STRONG, SURFACE_ALT, NEUTRAL_SOFT, SURFACE, FAINT)
        button("Ghost.TButton", SURFACE, ACCENT, SURFACE, ACCENT_SOFT, ACCENT_SOFT, SURFACE, FAINT)
        button("Danger.TButton", SURFACE, DANGER, BORDER_STRONG, DANGER_SOFT, DANGER_SOFT, SURFACE, FAINT)
        style.configure("Large.Primary.TButton", padding=(self.px(20), self.px(11)), font=fonts.h3)

        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, rowheight=self.px(30),
            borderwidth=0, font=fonts.body,
        )
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])
        style.configure(
            "Treeview.Heading", background=SURFACE_ALT, foreground=MUTED, font=fonts.small, relief="flat",
            bordercolor=BORDER, lightcolor=SURFACE_ALT, darkcolor=SURFACE_ALT, padding=(self.px(8), self.px(6)),
        )
        style.map("Treeview.Heading", background=[("active", NEUTRAL_SOFT)])

        for orient in ("Vertical", "Horizontal"):
            style.configure(
                f"{orient}.TScrollbar", troughcolor=SURFACE, background=BORDER_STRONG, bordercolor=SURFACE,
                lightcolor=BORDER_STRONG, darkcolor=BORDER_STRONG, arrowcolor=MUTED, gripcount=0,
                arrowsize=self.px(12),
            )
            style.map(f"{orient}.TScrollbar", background=[("active", FAINT)])

        style.configure(
            "TEntry", fieldbackground=SURFACE, bordercolor=BORDER_STRONG, lightcolor=SURFACE, darkcolor=SURFACE,
            padding=(self.px(8), self.px(6)), insertcolor=TEXT,
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
        style.configure(
            "TCombobox", fieldbackground=SURFACE, background=SURFACE, bordercolor=BORDER_STRONG, arrowcolor=MUTED,
            lightcolor=SURFACE, darkcolor=SURFACE, padding=(self.px(8), self.px(5)),
        )
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)], selectbackground=[("readonly", SURFACE)],
                  selectforeground=[("readonly", TEXT)])
        style.configure(
            "TCheckbutton", background=SURFACE, foreground=TEXT, indicatorbackground=SURFACE,
            indicatorforeground=ACCENT, indicatormargin=(0, 0, self.px(6), 0), focuscolor=SURFACE,
        )
        style.map("TCheckbutton", background=[("active", SURFACE)], indicatorbackground=[("selected", ACCENT_SOFT)])
        style.configure(
            "Accent.Horizontal.TProgressbar", troughcolor=NEUTRAL_SOFT, background=ACCENT, bordercolor=NEUTRAL_SOFT,
            lightcolor=ACCENT, darkcolor=ACCENT, thickness=self.px(6),
        )


_current: Theme | None = None


def install(root: tk.Tk) -> Theme:
    """Create the theme for this window; widgets then reach it through get()."""
    global _current
    _current = Theme(root)
    return _current


def get() -> Theme:
    if _current is None:
        raise RuntimeError("theme.install() must run before any widget is built")
    return _current
