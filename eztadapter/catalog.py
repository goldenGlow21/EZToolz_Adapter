"""Typed, validated view of the JSON catalog in the data/ folder.

The JSON files hold the knowledge: artifact signatures, download sources,
command lines and the analysis menu. This module only turns them into
immutable objects and checks them strictly, so a mistake in the catalog stops
the program at startup with the offending entry named, instead of failing
halfway through a run.
"""

from __future__ import annotations

import codecs
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

CATALOG_DIR = Path(__file__).with_name("data")

# An action listing this artifact id accepts every file, recognised or not.
ANY_ARTIFACT = "*"

INPUT_FOLDER = "folder"
INPUT_FILE = "file"

PLACEHOLDERS = frozenset({"input", "output", "exe_dir", "pair", "name"})
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]+)\}")


class CatalogError(ValueError):
    """The catalog JSON is malformed or inconsistent."""


@dataclass(frozen=True)
class Magic:
    """A byte signature expected at a fixed offset from the start of a file."""

    offset: int
    signature: bytes


@dataclass(frozen=True)
class Rule:
    """Conditions that must all hold for a file to be of an artifact type.

    An empty tuple means the condition is not part of the rule.
    """

    names: tuple[str, ...] = ()
    magic: tuple[Magic, ...] = ()
    hive: tuple[str, ...] = ()


@dataclass(frozen=True)
class Artifact:
    id: str
    label: str
    category: str
    about: str
    rules: tuple[Rule, ...]
    # Suffixes such as ".LOG1": a file named <artifact file name><suffix> in
    # the same folder belongs with the artifact and is staged next to it.
    sidecars: tuple[str, ...] = ()


@dataclass(frozen=True)
class Source:
    """Where a tool is downloaded from. See tools.json for the kinds."""

    kind: str
    url: str = ""
    repo: str = ""
    asset: str = ""
    version_url: str = ""
    file: str = ""
    sha256_url: str = ""
    exclude: tuple[str, ...] = ()
    rename: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Step:
    """One command line of an action."""

    args: tuple[str, ...]
    stdout: str | None = None
    stdout_encoding: str | None = None
    # A staged file fed to the tool as standard input, for tools that read their input there.
    stdin: str | None = None
    # True when a failing command prints its error message, not results, to stdout:
    # the captured text then goes to the job log instead of a result file.
    stdout_to_log_on_failure: bool = False
    # New name for the single file the command writes, for tools whose own naming
    # misleads (rla names user hives after the first "Users\<name>" in the path).
    rename_output: str | None = None


@dataclass(frozen=True)
class Pair:
    """A companion artifact some parsers use to enrich their output.

    Example: a $MFT lets MFTECmd turn the parent record numbers in a $J into
    full paths.
    """

    artifact: str
    required: bool
    args: tuple[str, ...]


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    tool_id: str
    artifacts: tuple[str, ...]
    input: str
    steps: tuple[Step, ...]
    pair: Pair | None = None
    dirty_hive_args: tuple[str, ...] = ()

    def applies_to(self, artifact_id: str | None) -> bool:
        return ANY_ARTIFACT in self.artifacts or artifact_id in self.artifacts


@dataclass(frozen=True)
class Requirement:
    """A shared runtime some tools need, located by framework name and major version."""

    id: str
    label: str
    framework: str
    major: int
    download: str


@dataclass(frozen=True)
class Tool:
    id: str
    group: str
    about: str
    homepage: str
    source: Source
    exe: str
    actions: tuple[Action, ...]
    recommended: bool
    gui: str | None = None
    views: tuple[str, ...] = ()
    requires: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class TaskStep:
    """One action inside an investigation task."""

    action_id: str
    default: bool
    # Artifact types this task feeds the action; None means every type the action accepts.
    artifacts: frozenset[str] | None = None


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    about: str


@dataclass(frozen=True)
class InvestigationTask:
    """A menu entry: one investigative question and the actions that answer it."""

    id: str
    section: str
    title: str
    question: str
    about: str
    # Where to start reading the results.
    reading: str
    icon: str
    steps: tuple[TaskStep, ...]


@dataclass(frozen=True)
class Catalog:
    artifacts: tuple[Artifact, ...]
    tools: tuple[Tool, ...]
    requirements: tuple[Requirement, ...]
    sections: tuple[Section, ...] = ()
    tasks: tuple[InvestigationTask, ...] = ()

    def task(self, task_id: str) -> InvestigationTask:
        return _find(self.tasks, task_id, "task")

    def artifact(self, artifact_id: str) -> Artifact:
        return _find(self.artifacts, artifact_id, "artifact")

    def tool(self, tool_id: str) -> Tool:
        return _find(self.tools, tool_id, "tool")

    def requirement(self, requirement_id: str) -> Requirement:
        return _find(self.requirements, requirement_id, "requirement")

    @property
    def actions(self) -> tuple[Action, ...]:
        return tuple(action for tool in self.tools for action in tool.actions)

    def action(self, action_id: str) -> Action:
        return _find(self.actions, action_id, "action")

def _find(items, item_id: str, kind: str):
    for item in items:
        if item.id == item_id:
            return item
    raise KeyError(f"Unknown {kind}: {item_id}")


def load_catalog(directory: Path = CATALOG_DIR) -> Catalog:
    artifacts_doc = _read_json(directory / "artifacts.json")
    tools_doc = _read_json(directory / "tools.json")
    tasks_doc = _read_json(directory / "tasks.json")
    _keys(artifacts_doc, "artifacts.json", required={"artifacts"}, optional={"_comment"})
    _keys(tools_doc, "tools.json", required={"tools", "requirements"}, optional={"_comment"})
    _keys(tasks_doc, "tasks.json", required={"sections", "tasks"}, optional={"_comment"})

    catalog = Catalog(
        artifacts=tuple(_artifact(entry) for entry in artifacts_doc["artifacts"]),
        tools=tuple(_tool(entry) for entry in tools_doc["tools"]),
        requirements=tuple(_requirement(entry) for entry in tools_doc["requirements"]),
        sections=tuple(_section(entry) for entry in tasks_doc["sections"]),
        tasks=tuple(_task(entry) for entry in tasks_doc["tasks"]),
    )
    _check_references(catalog)
    _check_tasks(catalog)
    # Recommended tools are those the menu ticks by default, plus any marked in tools.json (viewers).
    default_tools = {catalog.action(step.action_id).tool_id for task in catalog.tasks for step in task.steps if step.default}
    tools = tuple(replace(tool, recommended=tool.recommended or tool.id in default_tools) for tool in catalog.tools)
    return replace(catalog, tools=tools)


def _read_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as error:
        raise CatalogError(f"{path.name} is not valid JSON: {error}") from error


def _keys(entry: dict, where: str, required: set[str], optional: set[str] = frozenset()) -> None:
    if not isinstance(entry, dict):
        raise CatalogError(f"{where}: expected an object, got {type(entry).__name__}")
    missing = required - entry.keys()
    unknown = entry.keys() - required - optional
    if missing:
        raise CatalogError(f"{where}: missing {', '.join(sorted(missing))}")
    if unknown:
        raise CatalogError(f"{where}: unknown {', '.join(sorted(unknown))}")


def _artifact(entry: dict) -> Artifact:
    where = f"artifact {entry.get('id', '?')}"
    _keys(entry, where, required={"id", "label", "category", "about", "rules"}, optional={"sidecars"})
    rules = tuple(_rule(rule, where) for rule in entry["rules"])
    if not rules:
        raise CatalogError(f"{where}: needs at least one rule")
    return Artifact(
        id=entry["id"],
        label=entry["label"],
        category=entry["category"],
        about=entry["about"],
        rules=rules,
        sidecars=tuple(entry.get("sidecars", ())),
    )


def _rule(entry: dict, where: str) -> Rule:
    _keys(entry, where, required=set(), optional={"names", "magic", "hive"})
    if not entry:
        raise CatalogError(f"{where}: a rule needs at least one condition")
    return Rule(
        names=tuple(entry.get("names", ())),
        magic=tuple(_magic(magic, where) for magic in entry.get("magic", ())),
        hive=tuple(entry.get("hive", ())),
    )


def _magic(entry: dict, where: str) -> Magic:
    _keys(entry, where, required={"offset", "hex"})
    try:
        signature = bytes.fromhex(entry["hex"])
    except ValueError as error:
        raise CatalogError(f"{where}: bad hex signature {entry['hex']!r}") from error
    if not signature or entry["offset"] < 0:
        raise CatalogError(f"{where}: empty signature or negative offset")
    return Magic(offset=entry["offset"], signature=signature)


def _requirement(entry: dict) -> Requirement:
    _keys(entry, f"requirement {entry.get('id', '?')}", required={"id", "label", "framework", "major", "download"})
    return Requirement(**entry)


def _tool(entry: dict) -> Tool:
    where = f"tool {entry.get('id', '?')}"
    _keys(
        entry,
        where,
        required={"id", "group", "about", "homepage", "source", "exe", "actions"},
        optional={"gui", "views", "requires", "license", "recommended"},
    )
    actions = tuple(_action(action, entry["id"]) for action in entry["actions"])
    if not actions and "gui" not in entry:
        raise CatalogError(f"{where}: a tool needs actions or a gui to launch")
    return Tool(
        id=entry["id"],
        group=entry["group"],
        about=entry["about"],
        homepage=entry["homepage"],
        source=_source(entry["source"], where),
        exe=entry["exe"],
        actions=actions,
        recommended=entry.get("recommended", False),
        gui=entry.get("gui"),
        views=tuple(view.lower() for view in entry.get("views", ())),
        requires=entry.get("requires"),
        license=entry.get("license"),
    )


def _source(entry: dict, where: str) -> Source:
    kind = entry.get("kind")
    shared = {"exclude", "rename"}
    if kind == "url":
        _keys(entry, where, required={"kind", "url"}, optional=shared)
    elif kind == "github":
        _keys(entry, where, required={"kind", "repo", "asset"}, optional=shared)
        try:
            re.compile(entry["asset"])
        except re.error as error:
            raise CatalogError(f"{where}: asset pattern does not compile: {error}") from error
    elif kind == "versioned":
        _keys(entry, where, required={"kind", "version_url", "url", "file"}, optional=shared | {"sha256_url"})
    else:
        raise CatalogError(f"{where}: unknown source kind {kind!r}")
    return Source(
        kind=kind,
        url=entry.get("url", ""),
        repo=entry.get("repo", ""),
        asset=entry.get("asset", ""),
        version_url=entry.get("version_url", ""),
        file=entry.get("file", ""),
        sha256_url=entry.get("sha256_url", ""),
        exclude=tuple(entry.get("exclude", ())),
        rename=tuple(entry.get("rename", {}).items()),
    )


def _action(entry: dict, tool_id: str) -> Action:
    where = f"action {entry.get('id', '?')} of {tool_id}"
    _keys(
        entry,
        where,
        required={"id", "label", "artifacts", "input", "steps"},
        optional={"pair", "dirty_hive_args"},
    )
    if entry["input"] not in (INPUT_FOLDER, INPUT_FILE):
        raise CatalogError(f"{where}: input must be {INPUT_FOLDER!r} or {INPUT_FILE!r}")
    steps = tuple(_step(step, where) for step in entry["steps"])
    if not steps:
        raise CatalogError(f"{where}: needs at least one step")

    pair = None
    if "pair" in entry:
        _keys(entry["pair"], where, required={"artifact", "required", "args"})
        pair = Pair(entry["pair"]["artifact"], entry["pair"]["required"], tuple(entry["pair"]["args"]))
        if entry["input"] != INPUT_FILE:
            raise CatalogError(f"{where}: a pair is only supported for 'file' actions")
        if "{pair}" not in "".join(pair.args):
            raise CatalogError(f"{where}: pair args must use {{pair}}")

    action = Action(
        id=entry["id"],
        label=entry["label"],
        tool_id=tool_id,
        artifacts=tuple(entry["artifacts"]),
        input=entry["input"],
        steps=steps,
        pair=pair,
        dirty_hive_args=tuple(entry.get("dirty_hive_args", ())),
    )
    _check_placeholders(action, where)
    return action


def _step(entry: dict, where: str) -> Step:
    _keys(
        entry,
        where,
        required={"args"},
        optional={"stdout", "stdout_encoding", "stdin", "stdout_on_failure", "rename_output"},
    )
    if "rename_output" in entry and "stdout" in entry:
        raise CatalogError(f"{where}: rename_output is for files the tool writes itself, not for stdout")
    if entry.get("stdin") not in (None, "{input}", "{pair}"):
        raise CatalogError(f"{where}: stdin must be {{input}} or {{pair}}, got {entry['stdin']!r}")
    on_failure = entry.get("stdout_on_failure", "keep")
    if on_failure not in ("keep", "log") or (on_failure == "log" and "stdout" not in entry):
        raise CatalogError(f"{where}: stdout_on_failure must be 'keep' or 'log', and 'log' needs stdout")
    encoding = entry.get("stdout_encoding")
    if encoding is not None:
        if "stdout" not in entry:
            raise CatalogError(f"{where}: stdout_encoding needs stdout")
        try:
            codecs.lookup(encoding)
        except LookupError as error:
            raise CatalogError(f"{where}: unknown encoding {encoding!r}") from error
    return Step(
        args=tuple(entry["args"]),
        stdout=entry.get("stdout"),
        stdout_encoding=encoding,
        stdin=entry.get("stdin"),
        stdout_to_log_on_failure=on_failure == "log",
        rename_output=entry.get("rename_output"),
    )


def _check_placeholders(action: Action, where: str) -> None:
    texts = [arg for step in action.steps for arg in step.args]
    file_names = [name for step in action.steps for name in (step.stdout, step.rename_output) if name]
    texts += file_names
    texts += [step.stdin for step in action.steps if step.stdin]
    texts += list(action.pair.args) if action.pair else []
    if any(step.stdin == "{input}" for step in action.steps) and action.input != INPUT_FILE:
        raise CatalogError(f"{where}: only a 'file' action can feed its input as stdin")
    for text in texts:
        for name in _PLACEHOLDER_RE.findall(text):
            if name not in PLACEHOLDERS:
                raise CatalogError(f"{where}: unknown placeholder {{{name}}} in {text!r}")
            if name == "name" and action.input != INPUT_FILE:
                raise CatalogError(f"{where}: {{name}} is only defined for 'file' actions")
            if name == "pair" and action.pair is None:
                raise CatalogError(f"{where}: {{pair}} used without a pair")
    for file_name in file_names:
        if "/" in file_name or "\\" in file_name:
            raise CatalogError(f"{where}: output file names must be plain names, got {file_name!r}")
        if set(_PLACEHOLDER_RE.findall(file_name)) - {"name"}:
            raise CatalogError(f"{where}: output file names may only use {{name}}, got {file_name!r}")


def _check_references(catalog: Catalog) -> None:
    for kind, items in (("artifact", catalog.artifacts), ("tool", catalog.tools), ("action", catalog.actions)):
        seen = set()
        for item in items:
            if item.id in seen:
                raise CatalogError(f"Duplicate {kind} id: {item.id}")
            seen.add(item.id)
    artifact_ids = {artifact.id for artifact in catalog.artifacts}
    requirement_ids = {requirement.id for requirement in catalog.requirements}
    for tool in catalog.tools:
        if tool.requires and tool.requires not in requirement_ids:
            raise CatalogError(f"tool {tool.id}: unknown requirement {tool.requires!r}")
        for view in tool.views:
            if not view.startswith(".") and view not in artifact_ids:
                raise CatalogError(f"tool {tool.id}: views entry {view!r} is neither an extension nor an artifact id")
            if not tool.gui:
                raise CatalogError(f"tool {tool.id}: views needs a gui to open files with")
        for action in tool.actions:
            for artifact_id in action.artifacts:
                if artifact_id != ANY_ARTIFACT and artifact_id not in artifact_ids:
                    raise CatalogError(f"action {action.id}: unknown artifact {artifact_id!r}")
            if action.pair and action.pair.artifact not in artifact_ids:
                raise CatalogError(f"action {action.id}: unknown pair artifact {action.pair.artifact!r}")


def _section(entry: dict) -> Section:
    _keys(entry, f"section {entry.get('id', '?')}", required={"id", "title", "about"})
    return Section(**entry)


def _task(entry: dict) -> InvestigationTask:
    where = f"task {entry.get('id', '?')}"
    _keys(entry, where, required={"id", "section", "title", "question", "about", "reading", "icon", "steps"})
    steps = []
    for step in entry["steps"]:
        _keys(step, where, required={"action", "default"}, optional={"artifacts"})
        narrowed = frozenset(step["artifacts"]) if "artifacts" in step else None
        steps.append(TaskStep(action_id=step["action"], default=step["default"], artifacts=narrowed))
    if not any(step.default for step in steps):
        raise CatalogError(f"{where}: at least one step must be ticked by default")
    return InvestigationTask(
        id=entry["id"],
        section=entry["section"],
        title=entry["title"],
        question=entry["question"],
        about=entry["about"],
        reading=entry["reading"],
        icon=entry["icon"],
        steps=tuple(steps),
    )


def _check_tasks(catalog: Catalog) -> None:
    section_ids = {section.id for section in catalog.sections}
    action_ids = {action.id for action in catalog.actions}
    seen = set()
    for task in catalog.tasks:
        if task.id in seen:
            raise CatalogError(f"Duplicate task id: {task.id}")
        seen.add(task.id)
        if task.section not in section_ids:
            raise CatalogError(f"task {task.id}: unknown section {task.section!r}")
        for step in task.steps:
            if step.action_id not in action_ids:
                raise CatalogError(f"task {task.id}: unknown action {step.action_id!r}")
            action = catalog.action(step.action_id)
            if step.artifacts and ANY_ARTIFACT not in action.artifacts and not step.artifacts <= set(action.artifacts):
                raise CatalogError(f"task {task.id}: {step.action_id} does not accept {sorted(step.artifacts - set(action.artifacts))}")
    # An action no task lists could never be chosen from the menu.
    unreachable = action_ids - {step.action_id for task in catalog.tasks for step in task.steps}
    if unreachable:
        raise CatalogError(f"Actions not used by any task: {', '.join(sorted(unreachable))}")
