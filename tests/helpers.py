"""Shared builders for the tests: the real catalog, evidence items and file headers."""

from __future__ import annotations

import struct
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path, PurePosixPath

from eztadapter.catalog import Catalog, load_catalog
from eztadapter.evidence import EvidenceItem
from eztadapter.fsutil import remove_tree

EVIDENCE_ROOT = Path("E:/evidence")


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    return load_catalog()


def item(rel: str, artifact_id: str | None, size: int = 100, dirty: bool = False, root: Path = EVIDENCE_ROOT) -> EvidenceItem:
    artifact = catalog().artifact(artifact_id) if artifact_id else None
    return EvidenceItem(
        path=root.joinpath(*PurePosixPath(rel).parts),
        rel=rel,
        size=size,
        mtime_ns=1_700_000_000_000_000_000,
        artifact=artifact,
        dirty_hive=dirty,
    )


def hive_header(embedded_path: str = "", dirty: bool = False) -> bytes:
    """A registry base block with the given self-recorded path."""
    header = bytearray(4096)
    header[0:4] = b"regf"
    struct.pack_into("<II", header, 4, 5, 4 if dirty else 5)
    name = embedded_path[-31:].encode("utf-16-le")
    header[0x30 : 0x30 + len(name)] = name
    return bytes(header)


def padded(prefix: bytes, offset: int = 0) -> bytes:
    return bytes(offset) + prefix + bytes(512)


def temp_folder(test: unittest.TestCase) -> Path:
    """A fresh folder deleted when the test ends."""
    folder = Path(tempfile.mkdtemp(prefix="eztadapter-test-"))
    test.addCleanup(remove_tree, folder)
    return folder
