"""Copy a job's evidence into a private working folder before any tool sees it.

Tools are never given an original file. Some parsers write next to their
input (cleaned hives, temporary files), and a parser bug could damage what
it reads; working on copies makes it impossible for either to alter the
evidence. Each copy is hashed as it is written, and the SHA-256 is recorded
in the run manifest as the identity of the evidence behind the results.

Layout under the job's staging folder:

    in/<relative path>     inputs of a 'folder' action, keeping the evidence tree
    in/<file name>         the input of a 'file' action and its transaction logs
    pair/<file name>       the companion file and its transaction logs
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .catalog import INPUT_FILE
from .evidence import EvidenceItem
from .fsutil import copy_timestamps, long_path
from .planner import Job

_CHUNK = 1024 * 1024

ROLE_INPUT = "input"
ROLE_SIDECAR = "sidecar"
ROLE_PAIR = "pair"


class StagingError(OSError):
    """The evidence could not be copied for a job."""


@dataclass(frozen=True)
class StagedFile:
    source: EvidenceItem
    staged: Path
    role: str
    sha256: str


@dataclass(frozen=True)
class StagedJob:
    root: Path
    # What the tool receives as {input}: the folder of a 'folder' action, the file of a 'file' action.
    input: Path
    pair: Path | None
    files: tuple[StagedFile, ...]


def stage(job: Job, root: Path) -> StagedJob:
    needed = sum(item.size for item in job.staged_items)
    os.makedirs(long_path(root), exist_ok=True)
    free = shutil.disk_usage(long_path(root)).free
    if needed > free:
        raise StagingError(
            f"Not enough free space next to the output folder to copy the evidence for this job: "
            f"needs {needed:,} bytes, {free:,} available. Choose an output folder on a larger drive."
        )

    inbox = root / "in"
    files = []
    if job.action.input == INPUT_FILE:
        item = job.inputs[0]
        files.append(_copy(item, inbox / item.name, ROLE_INPUT))
        files += [_copy(log, inbox / log.name, ROLE_SIDECAR) for log in job.sidecars]
        tool_input = inbox / item.name
    else:
        files += [_copy(item, inbox / item.rel, ROLE_INPUT) for item in job.inputs]
        files += [_copy(log, inbox / log.rel, ROLE_SIDECAR) for log in job.sidecars]
        tool_input = inbox

    pair_path = None
    if job.pair is not None:
        pair_path = root / "pair" / job.pair.name
        files.append(_copy(job.pair, pair_path, ROLE_PAIR))
        files += [_copy(log, root / "pair" / log.name, ROLE_SIDECAR) for log in job.pair_sidecars]
    return StagedJob(root=root, input=tool_input, pair=pair_path, files=tuple(files))


def _copy(item: EvidenceItem, destination: Path, role: str) -> StagedFile:
    return StagedFile(source=item, staged=destination, role=role, sha256=copy_evidence(item.path, destination))


def copy_evidence(source: Path, destination: Path) -> str:
    """Copy one file with its timestamps and return the SHA-256 of what was read.

    The source is only ever opened for reading. The destination must not
    exist yet, so a planning mistake can never overwrite an earlier copy.
    """
    os.makedirs(long_path(destination.parent), exist_ok=True)
    # Taken before reading: reading may advance the access time, depending on system policy.
    source_stat = os.stat(long_path(source))
    digest = hashlib.sha256()
    with open(long_path(source), "rb") as reader, open(long_path(destination), "xb") as writer:
        while chunk := reader.read(_CHUNK):
            digest.update(chunk)
            writer.write(chunk)
    copy_timestamps(source_stat, long_path(destination))
    return digest.hexdigest()
