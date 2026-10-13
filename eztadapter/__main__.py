"""Entry point of `python -m eztadapter` and of EZToolzAdapter.exe: opens the adapter window."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path

from . import __version__
from .catalog import CatalogError, load_catalog
from .workspace import DEFAULT_HOME, Workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eztadapter",
        description=(
            "Download forensic tools (Eric Zimmerman's tools, Sysinternals, Hayabusa, Chainsaw, "
            "Volatility and more), recognise the artifacts in an evidence folder, and run the "
            "matching tools on copies of them. Opens a window; no other arguments are needed."
        ),
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=DEFAULT_HOME,
        help=f"folder that holds tools/, evidence/, output/ and settings.json (default: {DEFAULT_HOME})",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    arguments = parser.parse_args(argv)

    if os.name != "nt":
        parser.error("the tools this adapter runs are Windows programs, so it needs Windows")

    _sharp_text_on_high_dpi_screens()
    try:
        workspace = Workspace.load(arguments.home)
        catalog = load_catalog()
    except OSError as error:
        _show_startup_error(
            f"EZToolz Adapter could not start:\n\n{error}\n\nIt keeps its tools, evidence and results next to the "
            f"program, in {arguments.home}. Put it in a folder you can write to, such as Documents or a USB drive."
        )
        return 1
    except (CatalogError, ValueError) as error:
        _show_startup_error(f"EZToolz Adapter could not start:\n\n{error}")
        return 1

    from .gui.app import App

    App(workspace, catalog).mainloop()
    return 0


def _show_startup_error(message: str) -> None:
    """Report in a dialog as well, because the windowed exe has no console."""
    if sys.stderr:
        print(message, file=sys.stderr)
    import tkinter
    from tkinter import messagebox

    root = tkinter.Tk()
    root.withdraw()
    messagebox.showerror("EZToolz Adapter", message)
    root.destroy()


def _sharp_text_on_high_dpi_screens() -> None:
    """Tell Windows the window scales itself, so text is not rendered blurry and stretched."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        # shcore is missing before Windows 8.1; the window still works, only less sharp.
        pass


if __name__ == "__main__":
    sys.exit(main())
