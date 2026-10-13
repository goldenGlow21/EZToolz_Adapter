import json
import os
import unittest
from pathlib import Path

from eztadapter.catalog import Catalog, Source, Tool
from eztadapter.history import group_by_task, list_runs
from eztadapter.installer import RECORD_NAME
from eztadapter.toolbox import Toolbox
from eztadapter.workspace import Workspace

from helpers import catalog, hive_header, temp_folder


def job(action: str) -> dict:
    return {"action": action, "title": action, "status": "ok", "outputs": [], "folder": action}


class GroupByTaskTests(unittest.TestCase):
    def test_jobs_sit_under_the_first_chosen_task_that_uses_them(self):
        jobs = [job("pecmd"), job("recmd-batch"), job("strings")]
        groups = group_by_task(catalog(), ["program-execution", "accounts-logons", "registry-deep-dive"], jobs)
        self.assertEqual([(task.id if task else None, indexes) for task, indexes in groups],
                         [("program-execution", [0]), ("accounts-logons", [1]), (None, [2])])

    def test_individual_tool_runs_have_no_task(self):
        self.assertEqual(group_by_task(catalog(), [], [job("pecmd")]), [(None, [0])])


class RunHistoryTests(unittest.TestCase):
    def test_runs_are_listed_newest_first_and_broken_manifests_are_reported(self):
        output = temp_folder(self)
        for name in ("2026-10-13_090000", "2026-10-14_090000"):
            os.makedirs(output / name)
            (output / name / "run.json").write_text(json.dumps({"jobs": [job("pecmd")], "finished": "x"}), encoding="utf-8")
        os.makedirs(output / "2026-10-15_090000")
        (output / "2026-10-15_090000" / "run.json").write_text("{not json", encoding="utf-8")
        runs = list_runs(output)
        self.assertEqual([run.name for run in runs], ["2026-10-15_090000", "2026-10-14_090000", "2026-10-13_090000"])
        self.assertIsNotNone(runs[0].error)
        self.assertEqual(runs[1].counts["ok"], 1)


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.home = temp_folder(self)
        workspace = Workspace.load(self.home)
        viewers = (
            Tool("Sheets", "v", "", "", Source("url", url="u"), "s.exe", (), False, gui="s.exe", views=(".csv",)),
            Tool("Hives", "v", "", "", Source("url", url="u"), "h.exe", (), False, gui="h.exe", views=("hive_system",)),
        )
        for tool in viewers:
            folder = workspace.tools_dir / tool.id
            os.makedirs(folder)
            (folder / tool.exe).write_bytes(b"MZ")
            record = {"version": "1", "fingerprint": "1", "url": "u", "sha256": "0", "installed": "now", "exe": tool.exe, "gui": tool.gui}
            (folder / RECORD_NAME).write_text(json.dumps(record), encoding="utf-8")
        self.toolbox = Toolbox(Catalog(catalog().artifacts, viewers, ()), workspace)

    def test_viewer_by_extension(self):
        self.assertEqual(self.toolbox.viewer_for(Path("results.CSV")).tool.id, "Sheets")

    def test_viewer_by_content_for_files_without_extension(self):
        hive = self.home / "SYSTEM"
        hive.write_bytes(hive_header("SYSTEM"))
        self.assertEqual(self.toolbox.viewer_for(hive).tool.id, "Hives")

    def test_no_viewer_for_other_files(self):
        other = self.home / "notes.txt"
        other.write_text("x", encoding="utf-8")
        self.assertIsNone(self.toolbox.viewer_for(other))


if __name__ == "__main__":
    unittest.main()
