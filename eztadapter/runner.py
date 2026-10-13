"""Execute planned jobs: stage the evidence, run the tool, collect and record results.

One run produces this layout inside the output folder:

    <output>/<run id>/
        run.json                    manifest: evidence hashes, commands, statuses
        <action id>/                results of a 'folder' action
            job.log                 everything the tool printed
        <action id>/<file name>/    results of a 'file' action, one folder per input

Exit codes alone cannot be trusted: several parsers exit with 0 after
refusing a file (for example a dirty hive without logs). A job therefore
only counts as successful when it also produced output files.
"""

from __future__ import annotations

import json
import locale
import os
import re
import subprocess
import threading
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from . import __version__
from .catalog import INPUT_FILE, Step
from .fsutil import long_path, remove_tree
from .planner import Job
from .staging import StagedJob, stage

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_CANCELLED = "cancelled"

STATUS_TEXT = {
    STATUS_OK: "OK",
    STATUS_WARNING: "WARNINGS",
    STATUS_EMPTY: "NO OUTPUT",
    STATUS_FAILED: "FAILED",
    STATUS_SKIPPED: "SKIPPED",
    STATUS_CANCELLED: "CANCELLED",
}

MANIFEST_NAME = "run.json"
JOB_LOG_NAME = "job.log"
STAGING_DIR_NAME = "_staging"

_PATH_PLACEHOLDERS = ("{input}", "{output}", "{exe_dir}", "{pair}")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]+)\}")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class JobResult:
    title: str
    action_id: str
    tool_id: str
    folder: Path
    tool_version: str = ""
    status: str = STATUS_FAILED
    message: str = ""
    started: str = ""
    finished: str = ""
    commands: list[dict] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)

    def to_json(self, run_folder: Path) -> dict:
        return {
            "title": self.title,
            "action": self.action_id,
            "tool": self.tool_id,
            "tool_version": self.tool_version,
            "folder": self.folder.relative_to(run_folder).as_posix(),
            "status": self.status,
            "message": self.message,
            "started": self.started,
            "finished": self.finished,
            "commands": self.commands,
            "inputs": self.inputs,
            "warnings": self.warnings,
            "outputs": self.outputs,
        }


@dataclass(frozen=True)
class ToolBinary:
    """A tool's executable and installed version, or the reason it cannot run."""

    exe: Path | None
    version: str
    problem: str | None = None


class Cancelled(Exception):
    pass


# Events reported while a run progresses, in this order per job.
@dataclass(frozen=True)
class JobStarted:
    index: int
    total: int
    title: str


@dataclass(frozen=True)
class LogText:
    index: int
    text: str


@dataclass(frozen=True)
class JobFinished:
    index: int
    result: JobResult


@dataclass(frozen=True)
class RunFinished:
    folder: Path
    results: list[JobResult]


Reporter = Callable[[object], None]


def new_run_folder(output_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder = output_root / stamp
    suffix = 2
    while folder.exists():
        folder = output_root / f"{stamp}_{suffix}"
        suffix += 1
    os.makedirs(long_path(folder))
    return folder


def run_jobs(
    jobs: list[Job],
    binaries: dict[str, ToolBinary],
    run_folder: Path,
    evidence_root: Path,
    task_ids: Sequence[str],
    report: Reporter,
    cancel: threading.Event,
) -> list[JobResult]:
    """Run every job in order, writing the manifest after each one.

    `binaries` maps tool id to the installed executable; a job whose tool
    cannot run fails with the reason instead of stopping the run. `task_ids`
    are the menu tasks the jobs came from, kept so results can be shown per task.
    """
    manifest = {
        "adapter_version": __version__,
        "run": run_folder.name,
        "evidence_folder": str(evidence_root),
        "tasks": list(task_ids),
        "started": _now(),
        "finished": None,
        "jobs": [],
    }
    results = []
    used_folders: set[Path] = set()
    for index, job in enumerate(jobs):
        report(JobStarted(index, len(jobs), job.title))
        folder = _job_folder(run_folder, job, used_folders)
        if cancel.is_set():
            result = JobResult(job.title, job.action.id, job.action.tool_id, folder, STATUS_CANCELLED, "Run was cancelled.")
        else:
            result = _run_one(job, index, binaries.get(job.action.tool_id), folder, run_folder, report, cancel)
        results.append(result)
        manifest["jobs"].append(result.to_json(run_folder))
        _write_manifest(run_folder, manifest)
        report(JobFinished(index, result))
    remove_tree(run_folder / STAGING_DIR_NAME)
    manifest["finished"] = _now()
    _write_manifest(run_folder, manifest)
    report(RunFinished(run_folder, results))
    return results


def _run_one(job, index, binary, folder, run_folder, report, cancel) -> JobResult:
    result = JobResult(job.title, job.action.id, job.action.tool_id, folder, started=_now())
    log_lines: list[str] = []

    def log(text: str) -> None:
        log_lines.append(text)
        report(LogText(index, text))

    os.makedirs(long_path(folder), exist_ok=True)
    staging_root = run_folder / STAGING_DIR_NAME / str(index + 1)
    try:
        if job.skip_reason:
            result.status, result.message = STATUS_SKIPPED, job.skip_reason
            log(f"Skipped: {job.skip_reason}")
            return result
        if binary is None or binary.problem:
            raise RuntimeError(binary.problem if binary else f"{job.action.tool_id} is not installed.")
        result.tool_version = binary.version

        log(f"Copying {len(job.staged_items)} evidence file(s) to a working folder...")
        staged = stage(job, staging_root)
        result.inputs = [_input_record(entry) for entry in staged.files]
        for hive in job.hives_without_logs:
            warning = (
                f"{hive.rel} is a dirty hive and its transaction logs (.LOG1/.LOG2) are not in the evidence "
                f"folder; it is parsed as-is and the newest changes may be missing."
            )
            result.warnings.append(warning)
            log(f"WARNING: {warning}")
        if job.unexpected_inputs:
            expected = ", ".join(sorted(job.action.artifacts))
            for item in job.unexpected_inputs:
                kind = item.artifact.label if item.artifact else "an unrecognised file"
                warning = (
                    f"{item.rel} is {kind}, not a usual input of this tool ({expected}); "
                    f"it was given anyway as requested, and the tool may reject it."
                )
                result.warnings.append(warning)
                log(f"WARNING: {warning}")
        if job.pair is not None:
            log(f"Using {job.pair.rel} as companion file.")

        # Tools that write temporary files (some copy their whole input) write them
        # into the job's staging folder, which is deleted with everything in it.
        temp = staged.root / "temp"
        os.makedirs(long_path(temp), exist_ok=True)
        environment = dict(os.environ, TEMP=str(temp), TMP=str(temp))
        exit_codes = []
        for step in job.action.steps:
            argv = build_command(job, step, staged, binary.exe, folder)
            stdin = _stdin_path(step, staged)
            exit_codes.append(_run_step(argv, step, stdin, environment, binary.exe.parent, folder, job, log, cancel, result))
        result.outputs = _collect_outputs(folder)
        failed_steps = sum(1 for code in exit_codes if code != 0)
        if not result.outputs:
            result.status = STATUS_FAILED if failed_steps else STATUS_EMPTY
            result.message = "The tool produced no output files. The log shows what it reported."
        elif failed_steps:
            result.status = STATUS_WARNING
            result.message = f"{failed_steps} of {len(exit_codes)} command(s) ended with an error code; output may be partial."
        else:
            result.status = STATUS_OK
            result.message = f"{len(result.outputs)} output file(s)."
    except Cancelled:
        result.status, result.message = STATUS_CANCELLED, "Cancelled while running."
        result.outputs = _collect_outputs(folder)
    except Exception as error:
        # One job's failure must not end the run. It is recorded as FAILED with
        # its message in the log and the manifest, so nothing is hidden.
        result.status, result.message = STATUS_FAILED, str(error)
        log(f"ERROR: {error}")
    finally:
        remove_tree(staging_root)
        result.finished = _now()
        log(f"Finished: {STATUS_TEXT[result.status]} - {result.message}")
        Path(long_path(folder / JOB_LOG_NAME)).write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return result


def build_command(job: Job, step: Step, staged: StagedJob, exe: Path, output: Path) -> list[str]:
    values = {
        "input": str(staged.input),
        "output": str(output),
        "exe_dir": str(exe.parent),
        "pair": str(staged.pair) if staged.pair else "",
        "name": job.inputs[0].name if job.action.input == INPUT_FILE else "",
    }
    args = list(step.args)
    if staged.pair is not None and job.action.pair:
        args += job.action.pair.args
    if job.hives_without_logs:
        args += job.action.dirty_hive_args
    return [str(exe)] + [_expand(arg, values) for arg in args]


def _expand(arg: str, values: dict[str, str]) -> str:
    expanded = _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], arg)
    if arg.startswith(_PATH_PLACEHOLDERS):
        expanded = os.path.normpath(expanded)
    return expanded


def _stdin_path(step: Step, staged: StagedJob) -> Path | None:
    if step.stdin == "{input}":
        return staged.input
    if step.stdin == "{pair}":
        return staged.pair
    return None


def _run_step(argv, step: Step, stdin: Path | None, environment, cwd: Path, folder: Path, job: Job, log, cancel, result: JobResult) -> int:
    log("> " + subprocess.list2cmdline(argv) + (f" < {stdin.name}" if stdin else ""))
    capture_path = None
    existing = set(_collect_outputs(folder))
    with ExitStack() as handles:
        stdout_target = subprocess.PIPE
        if step.stdout:
            capture_path = folder / _safe_name(step.stdout.replace("{name}", job.inputs[0].name))
            stdout_target = handles.enter_context(open(long_path(capture_path), "wb"))
        stdin_source = handles.enter_context(open(long_path(stdin), "rb")) if stdin else subprocess.DEVNULL
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=environment,
                stdin=stdin_source,
                stdout=stdout_target,
                stderr=subprocess.PIPE if capture_path else subprocess.STDOUT,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as error:
            raise RuntimeError(f"Could not start {argv[0]}: {error}") from error

        stream = process.stderr if capture_path else process.stdout
        pump = threading.Thread(target=_pump, args=(stream, log), daemon=True)
        pump.start()
        try:
            while process.poll() is None:
                if cancel.wait(0.2):
                    _kill_tree(process)
                    raise Cancelled()
        finally:
            pump.join()
    code = process.returncode
    result.commands.append({"argv": argv, "exit_code": code})
    if code != 0:
        log(f"Exit code {code}")

    if capture_path:
        size = os.path.getsize(long_path(capture_path))
        if size == 0:
            os.remove(long_path(capture_path))
            log(f"{capture_path.name}: no output, file not kept.")
        elif code != 0 and step.stdout_to_log_on_failure:
            for line in _decode(Path(long_path(capture_path)).read_bytes()).splitlines():
                if line.strip():
                    log(line)
            os.remove(long_path(capture_path))
            log(f"{capture_path.name}: not kept, it held the error message above instead of results.")
        else:
            if step.stdout_encoding:
                _reencode(capture_path, step.stdout_encoding)
            log(f"Saved output to {capture_path.name}")
    if step.rename_output:
        _rename_single_output(folder, existing, step.rename_output.replace("{name}", job.inputs[0].name), log)
    return code


def _rename_single_output(folder: Path, existing: set[str], new_name: str, log) -> None:
    written = sorted(set(_collect_outputs(folder)) - existing)
    if len(written) != 1:
        log(f"Expected one output file to name {new_name}, found {len(written)}; names left as the tool wrote them.")
        return
    source = folder / written[0]
    target = folder / _safe_name(new_name)
    if source != target:
        os.replace(long_path(source), long_path(target))
        log(f"Renamed {written[0]} to {target.name}")


def _kill_tree(process: subprocess.Popen) -> None:
    """Stop a tool and any processes it started; several tools are launchers for a child process."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    else:
        process.kill()
    process.wait()


def _pump(stream, log) -> None:
    for raw in iter(stream.readline, b""):
        text = _decode(raw).rstrip("\r\n")
        text = _ANSI_RE.sub("", text).split("\r")[-1]
        if text.strip():
            log(text)
    stream.close()


def _decode(raw: bytes) -> str:
    # Console tools print UTF-8 or the ANSI code page depending on how they were built.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


def _reencode(path: Path, encoding: str) -> None:
    """Rewrite a captured file as UTF-8 with a byte order mark, which Excel and Timeline Explorer read."""
    text = Path(long_path(path)).read_bytes().decode(encoding, errors="replace").lstrip("\ufeff")
    Path(long_path(path)).write_text(text, encoding="utf-8-sig", newline="")


def _collect_outputs(folder: Path) -> list[str]:
    outputs = []
    top = long_path(folder)
    for current, _, files in os.walk(top):
        for file_name in files:
            full = os.path.join(current, file_name)
            relative = Path(os.path.relpath(full, top)).as_posix()
            if relative != JOB_LOG_NAME and os.path.getsize(full) > 0:
                outputs.append(relative)
    return sorted(outputs)


def _job_folder(run_folder: Path, job: Job, used: set[Path]) -> Path:
    base = run_folder / job.action.id
    if job.action.input == INPUT_FILE:
        base = base / _safe_name(job.inputs[0].name)
    folder = base
    suffix = 2
    while folder in used:
        folder = base.with_name(f"{base.name} ({suffix})")
        suffix += 1
    used.add(folder)
    return folder


def _safe_name(name: str) -> str:
    cleaned = _UNSAFE_NAME_RE.sub("_", name).strip(" .")
    return cleaned or "_"


def _input_record(entry) -> dict:
    item = entry.source
    return {
        "path": str(item.path),
        "relative": item.rel,
        "role": entry.role,
        "artifact": item.artifact.id if item.artifact else None,
        "size": item.size,
        "modified": datetime.fromtimestamp(item.mtime_ns / 1e9).isoformat(timespec="seconds"),
        "sha256": entry.sha256,
    }


def _write_manifest(run_folder: Path, manifest: dict) -> None:
    target = run_folder / MANIFEST_NAME
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
