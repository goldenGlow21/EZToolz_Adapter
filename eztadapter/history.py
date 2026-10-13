"""Past runs, read back from the run.json manifests in the output folder.

Reading the manifests rather than keeping state means the history survives
restarts, and an output folder copied from another machine can be browsed.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .catalog import Catalog, InvestigationTask
from .runner import MANIFEST_NAME


@dataclass(frozen=True)
class RunRecord:
    folder: Path
    manifest: dict
    # Why the manifest could not be read; such runs are listed but cannot be opened.
    error: str | None = None

    @property
    def name(self) -> str:
        return self.folder.name

    @property
    def jobs(self) -> list[dict]:
        return self.manifest.get("jobs", [])

    @property
    def finished(self) -> bool:
        return bool(self.manifest.get("finished"))

    @property
    def counts(self) -> Counter:
        return Counter(job["status"] for job in self.jobs)


def list_runs(output_dir: Path) -> list[RunRecord]:
    """All runs, newest first."""
    if not output_dir.is_dir():
        return []
    records = []
    for manifest_path in sorted(output_dir.glob(f"*/{MANIFEST_NAME}"), key=lambda path: path.parent.name, reverse=True):
        records.append(read_run(manifest_path.parent))
    return records


def read_run(folder: Path) -> RunRecord:
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return RunRecord(folder=folder, manifest={}, error=f"run.json cannot be read: {error}")
    return RunRecord(folder=folder, manifest=manifest)


def group_by_task(catalog: Catalog, task_ids: Sequence[str], jobs: Sequence[dict]) -> list[tuple[InvestigationTask | None, list[int]]]:
    """Job indexes under the analysis task each came from, in menu order.

    A job whose action serves several chosen tasks is listed under the first.
    Jobs from tools run individually, or from tasks no longer in the catalog,
    come last under None.
    """
    known = {task.id: task for task in catalog.tasks}
    placed: set[int] = set()
    groups = []
    for task_id in task_ids:
        task = known.get(task_id)
        if task is None:
            continue
        actions = {step.action_id for step in task.steps}
        indexes = [index for index, job in enumerate(jobs) if index not in placed and job["action"] in actions]
        placed.update(indexes)
        if indexes:
            groups.append((task, indexes))
    rest = [index for index in range(len(jobs)) if index not in placed]
    if rest:
        groups.append((None, rest))
    return groups
