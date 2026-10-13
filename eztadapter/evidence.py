"""Scan the evidence folder and recognise each file in it.

Scanning only reads. Files are opened read-only and only their first few
kilobytes are read, so a scan is safe to repeat whenever the folder changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .catalog import Artifact, Catalog
from .fsutil import long_path, plain_path
from .identify import HEADER_SIZE, classify, hive_is_dirty


@dataclass(frozen=True)
class EvidenceItem:
    """One file in the evidence folder and what it was recognised as."""

    path: Path
    # Path relative to the evidence folder with forward slashes, e.g. "C/Windows/Prefetch/CMD.EXE-1.pf".
    rel: str
    size: int
    mtime_ns: int
    artifact: Artifact | None
    dirty_hive: bool = False
    # Set when the file could not be read; such items are listed but never run.
    error: str | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def folder(self) -> str:
        """Relative folder of the file, "" for the evidence root."""
        parent = str(PurePosixPath(self.rel).parent)
        return "" if parent == "." else parent


class Scanner:
    """Recognises files, remembering results for files that have not changed."""

    def __init__(self, catalog: Catalog):
        self._catalog = catalog
        self._known: dict[tuple[str, int, int], tuple[str | None, bool]] = {}

    def scan(self, root: Path) -> list[EvidenceItem]:
        if not root.is_dir():
            raise FileNotFoundError(f"Evidence folder does not exist: {root}")
        items = []
        top = long_path(root)
        for folder, subfolders, files in os.walk(top):
            subfolders.sort()
            for file_name in sorted(files):
                full = os.path.join(folder, file_name)
                items.append(self._item(Path(plain_path(full)), os.path.relpath(full, top)))
        return items

    def _item(self, path: Path, rel_native: str) -> EvidenceItem:
        rel = PurePosixPath(*Path(rel_native).parts).as_posix()
        try:
            stat = os.stat(long_path(path))
        except OSError as error:
            return EvidenceItem(path, rel, 0, 0, None, error=error.strerror or str(error))
        key = (rel, stat.st_size, stat.st_mtime_ns)
        if key not in self._known:
            try:
                with open(long_path(path), "rb") as handle:
                    header = handle.read(HEADER_SIZE)
            except OSError as error:
                return EvidenceItem(path, rel, stat.st_size, stat.st_mtime_ns, None, error=error.strerror or str(error))
            artifact = classify(self._catalog, path.name, header)
            self._known[key] = (artifact.id if artifact else None, hive_is_dirty(header))
        artifact_id, dirty = self._known[key]
        artifact = self._catalog.artifact(artifact_id) if artifact_id else None
        return EvidenceItem(path, rel, stat.st_size, stat.st_mtime_ns, artifact, dirty_hive=dirty)
