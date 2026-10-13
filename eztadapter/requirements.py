"""Detect shared runtimes that some tools need, such as the .NET 9 runtime.

Eric Zimmerman's tools are framework-dependent .NET builds: their small exe
starts the shared .NET runtime installed on the machine, and exits with an
error dialog when the runtime is missing. Checking up front lets the adapter
explain the problem and link the download instead.
"""

from __future__ import annotations

import os
from pathlib import Path

from .catalog import Requirement


def runtime_version(requirement: Requirement) -> str | None:
    """Newest installed version of the runtime with the required major version, or None."""
    for root in _dotnet_roots():
        shared = root / "shared" / requirement.framework
        if not shared.is_dir():
            continue
        versions = [entry.name for entry in shared.iterdir() if entry.is_dir() and _major(entry.name) == requirement.major]
        if versions:
            return max(versions, key=_version_key)
    return None


def _dotnet_roots() -> list[Path]:
    """Install locations the .NET host itself searches, in the same order."""
    roots = []
    if os.environ.get("DOTNET_ROOT"):
        roots.append(Path(os.environ["DOTNET_ROOT"]))
    for variable in ("ProgramW6432", "ProgramFiles"):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / "dotnet")
    if os.environ.get("LOCALAPPDATA"):
        roots.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "dotnet")
    return roots


def _major(version: str) -> int | None:
    head = version.split(".", 1)[0]
    return int(head) if head.isdigit() else None


def _version_key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in version.replace("-", ".").split("."))
