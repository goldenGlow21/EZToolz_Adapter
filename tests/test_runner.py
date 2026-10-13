import hashlib
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

from eztadapter.catalog import Action, Pair, Step
from eztadapter.evidence import Scanner
from eztadapter.planner import Job
from eztadapter.runner import (
    MANIFEST_NAME,
    STAGING_DIR_NAME,
    STATUS_CANCELLED,
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_WARNING,
    LogText,
    ToolBinary,
    build_command,
    new_run_folder,
    run_jobs,
)
from eztadapter.staging import StagedJob

from helpers import catalog, item, temp_folder

FAKE_TOOL = str(Path(__file__).with_name("fake_tool.py"))
PYTHON = ToolBinary(exe=Path(sys.executable), version="test")


def fake_action(behaviour: str, input_kind: str = "folder", stdout: str | None = None, encoding: str | None = None) -> Action:
    return Action(
        id=f"fake-{behaviour}",
        label=f"Fake {behaviour}",
        tool_id="Fake",
        artifacts=("prefetch",),
        input=input_kind,
        steps=(Step(args=(FAKE_TOOL, behaviour, "{input}", "{output}"), stdout=stdout, stdout_encoding=encoding),),
    )


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.root = temp_folder(self)
        self.evidence = self.root / "evidence"
        os.makedirs(self.evidence / "C" / "Windows" / "Prefetch")
        for name in ("A.EXE-1.pf", "B.EXE-2.pf"):
            (self.evidence / "C" / "Windows" / "Prefetch" / name).write_bytes(b"MAM\x04" + os.urandom(300))
        self.items = Scanner(catalog()).scan(self.evidence)
        self.events = []

    def run_job(self, job: Job, binary: ToolBinary = PYTHON, cancel: threading.Event | None = None):
        run_folder = new_run_folder(self.root / "output")
        results = run_jobs([job], {"Fake": binary}, run_folder, self.evidence, ["fake-task"], self.events.append, cancel or threading.Event())
        return run_folder, results[0]

    def test_successful_job_records_outputs_and_evidence_hashes(self):
        run_folder, result = self.run_job(Job(fake_action("write"), tuple(self.items)))
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual(result.outputs, ["result.csv"])
        self.assertIn("fake tool saw 2 file(s)", (result.folder / "job.log").read_text(encoding="utf-8"))
        manifest = json.loads((run_folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        recorded = {entry["relative"]: entry["sha256"] for entry in manifest["jobs"][0]["inputs"]}
        for evidence in self.items:
            self.assertEqual(recorded[evidence.rel], hashlib.sha256(evidence.path.read_bytes()).hexdigest())
        self.assertIsNotNone(manifest["finished"])
        self.assertEqual(manifest["tasks"], ["fake-task"])
        self.assertFalse((run_folder / STAGING_DIR_NAME).exists())

    def test_tool_that_writes_nothing_is_reported_as_no_output(self):
        _, result = self.run_job(Job(fake_action("nothing"), tuple(self.items)))
        self.assertEqual(result.status, STATUS_EMPTY)

    def test_error_exit_without_output_is_a_failure(self):
        _, result = self.run_job(Job(fake_action("fail"), tuple(self.items)))
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertIn("something broke", (result.folder / "job.log").read_text(encoding="utf-8"))

    def test_error_exit_with_output_is_a_warning(self):
        _, result = self.run_job(Job(fake_action("partial"), tuple(self.items)))
        self.assertEqual(result.status, STATUS_WARNING)
        self.assertEqual(result.outputs, ["partial.csv"])

    def test_stdout_is_saved_under_the_input_name(self):
        _, result = self.run_job(Job(fake_action("stdout", "file", stdout="{name}.txt"), (self.items[0],)))
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual(result.folder.name, "A.EXE-1.pf")
        self.assertEqual((result.folder / "A.EXE-1.pf.txt").read_text(encoding="utf-8").splitlines(), ["line one", "line two"])

    def test_utf16_stdout_is_rewritten_as_utf8_with_bom(self):
        action = fake_action("stdout-utf16", stdout="sigcheck.csv", encoding="utf-16-le")
        _, result = self.run_job(Job(action, tuple(self.items)))
        raw = (result.folder / "sigcheck.csv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbfPath,Verified"))

    def test_a_tool_that_writes_to_its_input_cannot_touch_the_evidence(self):
        before = {evidence.path: evidence.path.read_bytes() for evidence in self.items}
        _, result = self.run_job(Job(fake_action("tamper"), tuple(self.items)))
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_error_message_on_stdout_goes_to_the_log_not_a_result_file(self):
        step = Step(args=(FAKE_TOOL, "stdout-error", "{input}", "{output}"), stdout="windows.info.csv", stdout_to_log_on_failure=True)
        action = Action("fake-vol", "Fake vol", "Fake", ("prefetch",), "file", (step,))
        _, result = self.run_job(Job(action, (self.items[0],)))
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse((result.folder / "windows.info.csv").exists())
        self.assertIn("Unsatisfied requirement", (result.folder / "job.log").read_text(encoding="utf-8"))

    def test_error_exit_keeps_stdout_when_it_is_still_a_result(self):
        step = Step(args=(FAKE_TOOL, "stdout-error", "{input}", "{output}"), stdout="exiftool.csv")
        action = Action("fake-exif", "Fake exif", "Fake", ("prefetch",), "folder", (step,))
        _, result = self.run_job(Job(action, tuple(self.items)))
        self.assertEqual(result.status, STATUS_WARNING)
        self.assertEqual(result.outputs, ["exiftool.csv"])

    def test_single_output_is_renamed_after_the_input(self):
        step = Step(args=(FAKE_TOOL, "misnamed", "{input}", "{output}"), rename_output="{name}")
        action = Action("fake-rla", "Fake rla", "Fake", ("prefetch",), "file", (step,))
        _, result = self.run_job(Job(action, (self.items[0],)))
        self.assertEqual(result.outputs, ["A.EXE-1.pf"])

    def test_input_can_be_fed_as_stdin(self):
        action = Action(
            id="fake-stdin", label="Fake stdin", tool_id="Fake", artifacts=("prefetch",), input="file",
            steps=(Step(args=(FAKE_TOOL, "stdin", "{input}", "{output}"), stdin="{input}"),),
        )
        _, result = self.run_job(Job(action, (self.items[0],)))
        size = self.items[0].size
        self.assertEqual((result.folder / "stdin.txt").read_text(encoding="utf-8"), f"{size} bytes, starts 4d414d04\n")

    def test_temporary_files_of_tools_stay_inside_the_run_and_are_removed(self):
        run_folder, result = self.run_job(Job(fake_action("temp"), tuple(self.items)))
        temp = Path((result.folder / "temp.txt").read_text(encoding="utf-8"))
        self.assertIn(run_folder / STAGING_DIR_NAME, temp.parents)
        self.assertFalse(temp.exists())

    def test_cancel_stops_a_running_tool(self):
        cancel = threading.Event()

        def stop_when_working():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if any(isinstance(event, LogText) and "working" in event.text for event in list(self.events)):
                    cancel.set()
                    return
                time.sleep(0.05)

        watcher = threading.Thread(target=stop_when_working)
        watcher.start()
        started = time.monotonic()
        _, result = self.run_job(Job(fake_action("sleep"), tuple(self.items)), cancel=cancel)
        watcher.join()
        self.assertEqual(result.status, STATUS_CANCELLED)
        self.assertLess(time.monotonic() - started, 20)

    def test_tool_that_cannot_run_fails_with_the_reason(self):
        broken = ToolBinary(exe=None, version="", problem="Fake needs the .NET 9 Runtime")
        _, result = self.run_job(Job(fake_action("write"), tuple(self.items)), binary=broken)
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertIn(".NET 9", result.message)

    def test_forced_inputs_of_another_type_are_reported_as_warnings(self):
        job = Job(fake_action("write"), tuple(self.items), unexpected_inputs=(self.items[1],))
        _, result = self.run_job(job)
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn(self.items[1].rel, result.warnings[0])
        self.assertIn("may reject it", result.warnings[0])

    def test_skipped_job_says_why(self):
        _, result = self.run_job(Job(fake_action("write"), tuple(self.items), skip_reason="Needs a SOFTWARE hive"))
        self.assertEqual(result.status, STATUS_SKIPPED)
        self.assertEqual(result.message, "Needs a SOFTWARE hive")


class BuildCommandTests(unittest.TestCase):
    def test_pair_and_dirty_hive_arguments_are_appended(self):
        action = Action(
            id="x",
            label="x",
            tool_id="X",
            artifacts=("hive_system",),
            input="file",
            steps=(Step(args=("-f", "{input}", "--csv", "{output}", "--bn", "{exe_dir}/Batch/k.reb")),),
            pair=Pair("hive_software", False, ("-r", "{pair}")),
            dirty_hive_args=("--nl",),
        )
        hive = item("C/SYSTEM", "hive_system", dirty=True)
        job = Job(action, (hive,), pair=item("C/SOFTWARE", "hive_software"), hives_without_logs=(hive,))
        staged = StagedJob(Path("S"), Path("S/in/SYSTEM"), Path("S/pair/SOFTWARE"), ())
        argv = build_command(job, action.steps[0], staged, Path("T/x.exe"), Path("O"))
        self.assertEqual(
            argv,
            [str(Path("T/x.exe")), "-f", str(Path("S/in/SYSTEM")), "--csv", "O", "--bn",
             os.path.normpath("T/Batch/k.reb"), "-r", str(Path("S/pair/SOFTWARE")), "--nl"],
        )

    def test_nothing_is_appended_for_a_clean_hive_without_pair(self):
        action = catalog().action("appcompatcacheparser")
        hive = item("C/SYSTEM", "hive_system")
        job = Job(action, (hive,))
        staged = StagedJob(Path("S"), Path("S/in/SYSTEM"), None, ())
        argv = build_command(job, action.steps[0], staged, Path("T/a.exe"), Path("O"))
        self.assertNotIn("--nl", argv)


if __name__ == "__main__":
    unittest.main()
