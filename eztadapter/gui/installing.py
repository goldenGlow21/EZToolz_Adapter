"""Background bodies for installing and update checks, and the events they report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..catalog import Tool
from ..installer import InstallError, Release, install, resolve


@dataclass(frozen=True)
class InstallProgress:
    tool_id: str
    done: int
    total: int | None


@dataclass(frozen=True)
class InstallFinished:
    tool_id: str
    error: str | None


@dataclass(frozen=True)
class UpdateFound:
    tool_id: str
    release: Release


def install_work(tools: list[Tool], tools_dir: Path):
    """Install tools one after another; the result maps tool id to the reason it failed."""

    def work(report, cancel):
        failures = {}
        for tool in tools:
            if cancel.is_set():
                failures[tool.id] = "Cancelled."
                continue
            report(InstallProgress(tool.id, 0, None))
            try:
                release = resolve(tool.source)
                install(tool, release, tools_dir, lambda done, total, tool_id=tool.id: report(InstallProgress(tool_id, done, total)), cancel)
                report(InstallFinished(tool.id, None))
            except InstallError as error:
                failures[tool.id] = str(error)
                report(InstallFinished(tool.id, str(error)))
        return failures

    return work


def update_work(tools: list[Tool]):
    """Look up the newest release of each tool; the result maps tool id to the reason a lookup failed."""

    def work(report, cancel):
        failures = {}
        for tool in tools:
            if cancel.is_set():
                break
            try:
                report(UpdateFound(tool.id, resolve(tool.source)))
            except InstallError as error:
                failures[tool.id] = str(error)
        return failures

    return work
