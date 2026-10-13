"""Where the adapter keeps its tools, evidence, results and settings.

Everything lives under one home folder, by default the folder holding the
program, so the whole kit can be copied to a USB drive:

    <home>/tools/          downloaded tools, one folder each
    <home>/evidence/       default place to drop evidence files
    <home>/output/         default place for results, one folder per run
    <home>/settings.json   chosen folders and accepted licences

The evidence and output folders can point anywhere else.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .fsutil import long_path

SETTINGS_NAME = "settings.json"
# The packaged EZToolzAdapter.exe keeps its kit beside itself; from source, the repository folder is home.
DEFAULT_HOME = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


@dataclass
class Workspace:
    home: Path
    evidence_dir: Path
    output_dir: Path
    # Licence URLs the user agreed to; tools under such a licence install without asking again.
    accepted_licenses: set[str] = field(default_factory=set)

    @property
    def tools_dir(self) -> Path:
        return self.home / "tools"

    @classmethod
    def load(cls, home: Path = DEFAULT_HOME) -> Workspace:
        home = home.resolve()
        settings_path = home / SETTINGS_NAME
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
        workspace = cls(
            home=home,
            evidence_dir=Path(settings.get("evidence_dir", home / "evidence")),
            output_dir=Path(settings.get("output_dir", home / "output")),
            accepted_licenses=set(settings.get("accepted_licenses", [])),
        )
        os.makedirs(long_path(workspace.tools_dir), exist_ok=True)
        # Folders chosen elsewhere are left alone: a missing USB drive is reported, not recreated.
        for folder in (workspace.evidence_dir, workspace.output_dir):
            if folder in (home / "evidence", home / "output"):
                os.makedirs(long_path(folder), exist_ok=True)
        return workspace

    def save(self) -> None:
        settings = {
            "evidence_dir": str(self.evidence_dir),
            "output_dir": str(self.output_dir),
            "accepted_licenses": sorted(self.accepted_licenses),
        }
        (self.home / SETTINGS_NAME).write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def change_folders(self, evidence_dir: Path, output_dir: Path) -> None:
        """Switch folders after checking they cannot feed results or tools back in as evidence."""
        evidence_dir, output_dir = evidence_dir.resolve(), output_dir.resolve()
        problem = folder_conflict(evidence_dir, output_dir, self.tools_dir.resolve())
        if problem:
            raise ValueError(problem)
        os.makedirs(long_path(evidence_dir), exist_ok=True)
        os.makedirs(long_path(output_dir), exist_ok=True)
        self.evidence_dir, self.output_dir = evidence_dir, output_dir
        self.save()


def folder_conflict(evidence_dir: Path, output_dir: Path, tools_dir: Path) -> str | None:
    """Explain why a folder layout is unsafe, or return None when it is fine."""
    if _inside(output_dir, evidence_dir) or _inside(evidence_dir, output_dir):
        return "The evidence folder and the output folder must not be the same or inside each other."
    if _inside(tools_dir, evidence_dir):
        return "The evidence folder must not contain the tools folder."
    return None


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents
