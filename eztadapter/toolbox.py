"""The installed state of every catalog tool, as the GUI and the runner need it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .catalog import Catalog, Requirement, Tool
from .fsutil import long_path
from .identify import HEADER_SIZE, classify
from .installer import InstallRecord, read_record
from .requirements import runtime_version
from .runner import ToolBinary
from .workspace import Workspace


@dataclass(frozen=True)
class ToolStatus:
    tool: Tool
    record: InstallRecord | None
    exe: Path | None
    gui: Path | None
    # Set when the tool needs a runtime that is not installed.
    missing_requirement: Requirement | None

    @property
    def installed(self) -> bool:
        return self.exe is not None

    @property
    def ready(self) -> bool:
        return self.installed and self.missing_requirement is None

    @property
    def problem(self) -> str | None:
        if not self.installed:
            return f"{self.tool.id} is not installed. Install it on the Tools tab."
        if self.missing_requirement:
            return f"{self.tool.id} needs the {self.missing_requirement.label}: {self.missing_requirement.download}"
        return None


class Toolbox:
    def __init__(self, catalog: Catalog, workspace: Workspace):
        self.catalog = catalog
        self.workspace = workspace

    def folder(self, tool: Tool) -> Path:
        return self.workspace.tools_dir / tool.id

    def status(self, tool: Tool) -> ToolStatus:
        record = read_record(tool, self.workspace.tools_dir)
        exe = gui = None
        if record is not None:
            exe = self._existing(tool, record.exe)
            gui = self._existing(tool, record.gui)
        requirement = self.catalog.requirement(tool.requires) if tool.requires else None
        missing = requirement if requirement and runtime_version(requirement) is None else None
        return ToolStatus(tool=tool, record=record, exe=exe, gui=gui, missing_requirement=missing)

    def binaries(self) -> dict[str, ToolBinary]:
        result = {}
        for tool in self.catalog.tools:
            status = self.status(tool)
            result[tool.id] = ToolBinary(
                exe=status.exe,
                version=status.record.version if status.record else "",
                problem=status.problem,
            )
        return result

    def viewer_for(self, path: Path, artifact_id: str | None = None) -> ToolStatus | None:
        """The installed viewer for a file: Timeline Explorer for a CSV, Registry Explorer for a hive.

        Files are matched by extension first, then by artifact type, which is
        read from the file itself when not given (rla writes hives without one).
        """
        extension = path.suffix.lower()
        if artifact_id is None and not any(extension in tool.views for tool in self.catalog.tools):
            artifact_id = self._identify(path)
        for tool in self.catalog.tools:
            if extension in tool.views or (artifact_id is not None and artifact_id in tool.views):
                status = self.status(tool)
                if status.ready and status.gui:
                    return status
        return None

    def _identify(self, path: Path) -> str | None:
        try:
            with open(long_path(path), "rb") as handle:
                header = handle.read(HEADER_SIZE)
        except OSError:
            # An unreadable file simply has no viewer; opening it will report the error.
            return None
        artifact = classify(self.catalog, path.name, header)
        return artifact.id if artifact else None

    def requirement_versions(self) -> list[tuple[Requirement, str | None]]:
        return [(requirement, runtime_version(requirement)) for requirement in self.catalog.requirements]

    def _existing(self, tool: Tool, relative: str | None) -> Path | None:
        if not relative:
            return None
        path = self.folder(tool) / relative
        return path if path.is_file() else None
