"""Turn chosen investigation tasks and the evidence in scope into jobs.

Tasks from the menu are first merged into one choice per action, so an action
shared by two tasks runs once. A job is then one unit of tool work: an action
plus the evidence it will receive.
A 'folder' action gets a single job holding every selected file it applies
to, so PECmd writes one combined CSV for all prefetch files. A 'file' action
gets one job per file. Planning also gathers what each job needs beyond its
inputs: transaction logs of registry hives, and companion files such as the
$MFT that resolves paths in a $J.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Iterable, Sequence

from .catalog import INPUT_FILE, Action, Catalog, InvestigationTask, TaskStep
from .evidence import EvidenceItem


@dataclass(frozen=True)
class Choice:
    """An action to run, and which artifact types to feed it."""

    action: Action
    # None means every artifact type the action accepts.
    artifacts: frozenset[str] | None = None
    # Give the action every readable file, whatever its type. The user asked
    # for it explicitly; files the tool cannot parse fail with its own message.
    force: bool = False

    def accepts(self, item: EvidenceItem) -> bool:
        if item.error is not None:
            return False
        if self.force:
            return True
        artifact_id = _artifact_id(item)
        return self.action.applies_to(artifact_id) and (self.artifacts is None or artifact_id in self.artifacts)


@dataclass(frozen=True)
class Job:
    action: Action
    inputs: tuple[EvidenceItem, ...]
    # Registry transaction logs, staged in the same folder as their hive.
    sidecars: tuple[EvidenceItem, ...] = ()
    pair: EvidenceItem | None = None
    pair_sidecars: tuple[EvidenceItem, ...] = ()
    # Dirty hives with no logs: parsers read them as-is and miss the newest changes.
    hives_without_logs: tuple[EvidenceItem, ...] = ()
    # Inputs of a forced choice that are not the action's usual artifact types.
    unexpected_inputs: tuple[EvidenceItem, ...] = ()
    skip_reason: str | None = None

    @property
    def title(self) -> str:
        head = f"{self.action.tool_id}: {self.action.label}"
        if self.action.input == INPUT_FILE:
            return f"{head} - {self.inputs[0].name}"
        count = len(self.inputs)
        return f"{head} ({count} file{'s' if count != 1 else ''})"

    @property
    def staged_items(self) -> tuple[EvidenceItem, ...]:
        pair = (self.pair,) if self.pair else ()
        return self.inputs + self.sidecars + pair + self.pair_sidecars


def step_choice(catalog: Catalog, step: TaskStep) -> Choice:
    return Choice(catalog.action(step.action_id), step.artifacts)


def merge_choices(catalog: Catalog, picks: Iterable[tuple[InvestigationTask, Iterable[str]]]) -> list[Choice]:
    """One choice per action from (task, ticked action ids) pairs, widening the artifacts to their union."""
    merged: dict[str, frozenset[str] | None] = {}
    for task, ticked in picks:
        ticked = set(ticked)
        for step in task.steps:
            if step.action_id not in ticked:
                continue
            so_far = merged.get(step.action_id, frozenset())
            # None (every artifact type) absorbs any narrower list.
            merged[step.action_id] = None if so_far is None or step.artifacts is None else so_far | step.artifacts
    return [Choice(action, merged[action.id]) for action in catalog.actions if action.id in merged]


def coverage(choices: Iterable[Choice], items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
    """The items at least one of the choices would process."""
    choices = list(choices)
    return [item for item in items if any(choice.accepts(item) for choice in choices)]


def plan(
    catalog: Catalog,
    choices: Iterable[Choice],
    selected: Sequence[EvidenceItem],
    everything: Sequence[EvidenceItem],
) -> list[Job]:
    """Build jobs for the choices over the selected items.

    `everything` is the whole evidence folder; sidecars and companion files
    are looked up there, so they are used even when not selected themselves.
    """
    usable = [item for item in everything if item.error is None]
    by_location = {(item.folder, item.name.casefold()): item for item in usable}
    jobs = []
    for choice in choices:
        action = choice.action
        inputs = [item for item in selected if choice.accepts(item)]
        if not inputs:
            continue
        groups = [[item] for item in inputs] if action.input == INPUT_FILE else [inputs]
        for group in groups:
            job = _job(catalog, action, group, usable, by_location)
            unexpected = tuple(item for item in group if not action.applies_to(_artifact_id(item)))
            jobs.append(replace(job, unexpected_inputs=unexpected) if unexpected else job)
    return jobs


def _job(catalog, action: Action, inputs: list[EvidenceItem], usable, by_location) -> Job:
    sidecars = []
    missing_logs = []
    for item in inputs:
        logs = _sidecars(item, by_location)
        # A log that is itself an input of this job is staged once, as an input.
        sidecars.extend(log for log in logs if log not in inputs and log not in sidecars)
        if item.dirty_hive and not logs:
            missing_logs.append(item)

    pair = pair_logs = None
    skip_reason = None
    if action.pair:
        pair = _nearest(inputs[0], [item for item in usable if _artifact_id(item) == action.pair.artifact])
        if pair is not None:
            pair_logs = _sidecars(pair, by_location)
        elif action.pair.required:
            label = catalog.artifact(action.pair.artifact).label
            skip_reason = f"Needs a {label} in the evidence folder, and none was found."

    return Job(
        action=action,
        inputs=tuple(inputs),
        sidecars=tuple(sidecars),
        pair=pair,
        pair_sidecars=tuple(pair_logs or ()),
        hives_without_logs=tuple(missing_logs),
        skip_reason=skip_reason,
    )


def _sidecars(item: EvidenceItem, by_location) -> list[EvidenceItem]:
    """Non-empty companion files of an item; empty logs carry nothing to replay."""
    if item.artifact is None:
        return []
    found = []
    for suffix in item.artifact.sidecars:
        candidate = by_location.get((item.folder, (item.name + suffix).casefold()))
        if candidate is not None and candidate.size > 0:
            found.append(candidate)
    return found


def _nearest(anchor: EvidenceItem, candidates: list[EvidenceItem]) -> EvidenceItem | None:
    """The candidate sharing the longest folder prefix with the anchor.

    This picks the $MFT of the same volume for a $J, and the SOFTWARE hive of
    the same machine for a SRUM database, even when one evidence folder holds
    collections from several machines.
    """
    anchor_parts = PurePosixPath(anchor.folder).parts
    best = None
    best_key = None
    for candidate in candidates:
        if candidate.path == anchor.path:
            continue
        parts = PurePosixPath(candidate.folder).parts
        shared = 0
        for left, right in zip(anchor_parts, parts):
            if left.casefold() != right.casefold():
                break
            shared += 1
        key = (-shared, len(candidate.rel), candidate.rel)
        if best_key is None or key < best_key:
            best, best_key = candidate, key
    return best


def _artifact_id(item: EvidenceItem) -> str | None:
    return item.artifact.id if item.artifact else None
